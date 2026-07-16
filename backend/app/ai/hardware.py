"""
Hardware detection and GPU offload planning for GGUF models.

Answers one question: "given this machine, this model file, and this context
size, how many transformer layers should go on the GPU?"

The plan is a descending ladder of n_gpu_layers values. The model worker
tries each rung in order, so an optimistic estimate that turns out not to
fit degrades gracefully instead of failing the whole request. On machines
without a dedicated GPU the plan is simply [0] (pure CPU).
"""

import os
import struct
import subprocess

# ---------------------------------------------------------------------------
# GPU detection
# ---------------------------------------------------------------------------

def get_gpu_info() -> dict | None:
    """Detect an NVIDIA GPU and return {'name', 'free_mb', 'total_mb'}.

    Tries nvidia-smi first (works without torch), then torch.cuda.
    Returns None when no usable GPU is found — callers treat that as CPU-only.
    """
    # 1. nvidia-smi — cheapest and most accurate "free right now" reading
    try:
        result = subprocess.run(
            ["nvidia-smi", "--query-gpu=memory.free,memory.total,name",
             "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=10,
        )
        if result.returncode == 0 and result.stdout.strip():
            free_mb, total_mb, name = result.stdout.strip().split("\n")[0].split(", ", 2)
            return {"name": name.strip(), "free_mb": int(free_mb), "total_mb": int(total_mb)}
    except (FileNotFoundError, subprocess.TimeoutExpired, ValueError, OSError):
        pass

    # 2. torch.cuda fallback
    try:
        import torch
        if torch.cuda.is_available():
            free_b, total_b = torch.cuda.mem_get_info(0)
            return {
                "name": torch.cuda.get_device_name(0),
                "free_mb": free_b // (1024 * 1024),
                "total_mb": total_b // (1024 * 1024),
            }
    except Exception:
        pass

    return None


# ---------------------------------------------------------------------------
# Minimal GGUF metadata reader
# ---------------------------------------------------------------------------

# GGUF scalar value types -> (struct format, byte size)
_GGUF_SIMPLE_TYPES = {
    0: ("B", 1), 1: ("b", 1), 2: ("H", 2), 3: ("h", 2),
    4: ("I", 4), 5: ("i", 4), 6: ("f", 4), 7: ("?", 1),
    10: ("Q", 8), 11: ("q", 8), 12: ("d", 8),
}


def _read_gguf_string(f) -> str:
    (length,) = struct.unpack("<Q", f.read(8))
    return f.read(length).decode("utf-8", errors="replace")


def _read_gguf_value(f, vtype: int):
    if vtype in _GGUF_SIMPLE_TYPES:
        fmt, size = _GGUF_SIMPLE_TYPES[vtype]
        return struct.unpack("<" + fmt, f.read(size))[0]
    if vtype == 8:  # string
        return _read_gguf_string(f)
    if vtype == 9:  # array
        (etype,) = struct.unpack("<I", f.read(4))
        (count,) = struct.unpack("<Q", f.read(8))
        return [_read_gguf_value(f, etype) for _ in range(count)]
    raise ValueError(f"Unknown GGUF value type: {vtype}")


def read_gguf_metadata(model_path: str, wanted_suffixes: tuple = ()) -> dict:
    """Read key/value metadata from a GGUF file header (no tensor data).

    If wanted_suffixes is given, stops early once a key ending with each
    suffix has been seen — avoids decoding the (huge) tokenizer vocab arrays.
    """
    meta = {}
    remaining = set(wanted_suffixes)
    with open(model_path, "rb") as f:
        if f.read(4) != b"GGUF":
            raise ValueError(f"Not a GGUF file: {model_path}")
        struct.unpack("<I", f.read(4))   # version
        struct.unpack("<Q", f.read(8))   # tensor count
        (kv_count,) = struct.unpack("<Q", f.read(8))

        for _ in range(kv_count):
            key = _read_gguf_string(f)
            (vtype,) = struct.unpack("<I", f.read(4))
            value = _read_gguf_value(f, vtype)
            meta[key] = value
            if remaining:
                remaining = {s for s in remaining if not key.endswith(s)}
                if not remaining:
                    break
    return meta


def describe_gguf_model(model_path: str) -> dict:
    """Return the numbers needed for offload planning, with safe defaults."""
    info = {
        "file_size_mb": os.path.getsize(model_path) // (1024 * 1024),
        "arch": "unknown",
        "block_count": 36,        # sensible default for 8B-class models
        "kv_heads": 8,
        "head_dim": 128,
    }
    try:
        meta = read_gguf_metadata(
            model_path,
            wanted_suffixes=(
                ".block_count", ".attention.head_count_kv",
                ".attention.key_length", ".embedding_length",
                ".attention.head_count",
            ),
        )
        arch = meta.get("general.architecture", "unknown")
        info["arch"] = arch
        info["block_count"] = int(meta.get(f"{arch}.block_count", info["block_count"]))
        info["kv_heads"] = int(meta.get(f"{arch}.attention.head_count_kv", info["kv_heads"]))

        head_dim = meta.get(f"{arch}.attention.key_length")
        if not head_dim:
            embd = meta.get(f"{arch}.embedding_length")
            heads = meta.get(f"{arch}.attention.head_count")
            if embd and heads:
                head_dim = int(embd) // int(heads)
        info["head_dim"] = int(head_dim or info["head_dim"])
    except Exception as e:
        print(f"[hardware] Could not parse GGUF metadata ({e}) — using defaults.")
    return info


# ---------------------------------------------------------------------------
# Offload planning
# ---------------------------------------------------------------------------

def plan_gpu_layers(
    model_path: str,
    n_ctx: int,
    mmproj_path: str | None = None,
    reserve_mb: int = 800,
    override: str = "auto",
) -> dict:
    """Compute a descending ladder of n_gpu_layers values to try.

    Returns {"plan": [int, ...], "gpu": dict|None, "model": dict, "reason": str}.
    """
    model = describe_gguf_model(model_path)
    gpu = get_gpu_info()

    # Explicit user override via LLM_N_GPU_LAYERS
    if override != "auto":
        forced = int(override)
        plan = [forced] if forced == 0 else [forced, 0]
        return {"plan": plan, "gpu": gpu, "model": model,
                "reason": f"forced by LLM_N_GPU_LAYERS={override}"}

    if gpu is None:
        return {"plan": [0], "gpu": None, "model": model,
                "reason": "no NVIDIA GPU detected — CPU-only"}

    block_count = model["block_count"]

    # Per-layer cost = weights slice + KV cache slice (fp16 K and V).
    # Embedding + output tensors are approximated as 2 extra layer-equivalents.
    weights_per_layer_mb = model["file_size_mb"] / (block_count + 2)
    kv_per_layer_mb = (2 * n_ctx * model["kv_heads"] * model["head_dim"] * 2) / (1024 * 1024)
    per_layer_mb = weights_per_layer_mb + kv_per_layer_mb

    # Reserve headroom for llama.cpp compute buffers and, when the vision
    # projector is loaded, its weights plus its (large) image compute buffer.
    total_reserve_mb = reserve_mb
    if mmproj_path and os.path.exists(mmproj_path):
        total_reserve_mb += os.path.getsize(mmproj_path) // (1024 * 1024) + 700

    usable_mb = gpu["free_mb"] - total_reserve_mb
    best = max(0, min(block_count + 1, int(usable_mb / per_layer_mb)))

    # Ladder: optimistic -> conservative -> CPU
    ladder = []
    for n in (best, int(best * 0.6), int(best * 0.3), 0):
        if n not in ladder:
            ladder.append(n)

    reason = (
        f"{gpu['name']}: {gpu['free_mb']}MB free, reserving {total_reserve_mb}MB, "
        f"~{per_layer_mb:.0f}MB/layer ({model['arch']}, {block_count} layers) "
        f"-> {best}/{block_count} layers on GPU"
    )
    return {"plan": ladder, "gpu": gpu, "model": model, "reason": reason}
