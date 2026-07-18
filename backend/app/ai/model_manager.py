"""
ModelManager — owns the single GGUF model slot on this machine.

Replaces the old one-subprocess-per-request design (which re-read the
~5GB model file from disk for every query and every ingested document)
with one persistent worker process that:

  * loads the model once and keeps it resident across requests,
  * picks n_gpu_layers adaptively from the free-VRAM plan (hardware.py),
    walking down the ladder until a load succeeds — CPU-only is the floor,
  * survives native crashes (a SIGABRT in llama.cpp kills only the worker;
    the manager restarts it with a more conservative plan),
  * serves both text chat and vision requests with the same weights
    (the mmproj/CLIP handler is added on demand),
  * unloads itself after a configurable idle period to give the VRAM back.

The worker speaks JSON-lines over stdin/stdout; its stderr (including
llama.cpp native logs) is streamed to the server console for diagnosis.
"""

import os
import sys
import json
import time
import queue
import threading
import subprocess
from collections import deque

from app.config import ModelConfig, LLMConfig
from app.ai.hardware import plan_gpu_layers

# ---------------------------------------------------------------------------
# Worker script (runs in a separate process)
# ---------------------------------------------------------------------------
_WORKER_SCRIPT = r'''
import sys, os, json, traceback

# fd 1 is reserved for the JSON protocol. Native llama.cpp code can write
# directly to fd 1/2, so hand it a redirect to stderr and keep a private
# copy of the real stdout for protocol replies.
_proto = os.fdopen(os.dup(1), "w", buffering=1)
os.dup2(2, 1)
sys.stdout = os.fdopen(1, "w", buffering=1, closefd=False)

def reply(obj):
    _proto.write(json.dumps(obj) + "\n")
    _proto.flush()

def log(msg):
    sys.stderr.write("[llm-worker] " + str(msg) + "\n")
    sys.stderr.flush()

CFG = json.loads(sys.argv[1])
LLM = None
LOADED_LAYERS = None

def load_model():
    global LLM, LOADED_LAYERS
    if LLM is not None:
        return
    from llama_cpp import Llama
    handler = None
    if CFG.get("with_vision"):
        from llama_cpp.llama_chat_format import Qwen3VLChatHandler
        log("Loading vision projector: " + CFG["mmproj_path"])
        handler = Qwen3VLChatHandler(mmproj_path=CFG["mmproj_path"], verbose=False)

    errors = []
    for n in CFG["plan"]:
        try:
            log(f"Loading model with n_gpu_layers={n} (ctx={CFG['n_ctx']})...")
            LLM = Llama(
                model_path=CFG["model_path"],
                n_gpu_layers=n,
                n_ctx=CFG["n_ctx"],
                n_threads=CFG.get("n_threads") or None,
                chat_handler=handler,
                verbose=False,
            )
            LOADED_LAYERS = n
            log(f"Model loaded successfully with n_gpu_layers={n}.")
            return
        except Exception as e:
            errors.append(f"n_gpu_layers={n}: {e}")
            log(f"Load failed at n_gpu_layers={n}: {e}")
            LLM = None
    raise RuntimeError("All load attempts failed: " + " | ".join(errors))

for line in sys.stdin:
    line = line.strip()
    if not line:
        continue
    try:
        req = json.loads(line)
        op = req.get("op")

        if op == "exit":
            reply({"ok": True})
            break

        elif op == "ping":
            reply({"ok": True, "loaded": LLM is not None, "n_gpu_layers": LOADED_LAYERS})

        elif op == "load":
            load_model()
            reply({"ok": True, "n_gpu_layers": LOADED_LAYERS})

        elif op == "chat":
            load_model()
            out = LLM.create_chat_completion(
                messages=req["messages"],
                max_tokens=req.get("max_tokens", 1024),
                temperature=req.get("temperature", 0.1),
            )
            reply({"ok": True, "result": out["choices"][0]["message"]["content"],
                   "n_gpu_layers": LOADED_LAYERS})

        elif op == "chat_stream":
            load_model()
            stream = LLM.create_chat_completion(
                messages=req["messages"],
                max_tokens=req.get("max_tokens", 1024),
                temperature=req.get("temperature", 0.1),
                stream=True,
            )
            # Emit each token as its own protocol line, then a terminal marker.
            for part in stream:
                delta = part["choices"][0].get("delta", {})
                piece = delta.get("content")
                if piece:
                    reply({"ok": True, "chunk": piece})
            reply({"ok": True, "done": True, "n_gpu_layers": LOADED_LAYERS})

        elif op == "vision":
            load_model()
            import base64
            with open(req["image_path"], "rb") as f:
                encoded = base64.b64encode(f.read()).decode("utf-8")
            out = LLM.create_chat_completion(
                messages=[
                    {"role": "system", "content": req.get(
                        "system_prompt",
                        "You are an industrial inspection assistant. You describe "
                        "equipment, instruments, and plant environments precisely, "
                        "transcribing visible tags, nameplates, and gauge readings "
                        "exactly, and noting visible defects or safety hazards. "
                        "You never invent details that are not visible.")},
                    {"role": "user", "content": [
                        {"type": "image_url",
                         "image_url": {"url": "data:image/jpeg;base64," + encoded}},
                        {"type": "text", "text": req["prompt"]},
                    ]},
                ],
                max_tokens=req.get("max_tokens", 256),
            )
            reply({"ok": True, "result": out["choices"][0]["message"]["content"],
                   "n_gpu_layers": LOADED_LAYERS})

        else:
            reply({"ok": False, "error": f"Unknown op: {op}"})

    except Exception as e:
        reply({"ok": False, "error": str(e),
               "traceback": traceback.format_exc()[-2000:]})
'''


class ModelManagerError(Exception):
    pass


class ModelManager:
    def __init__(self, model_path: str = None, mmproj_path: str = None):
        self.model_path = model_path or ModelConfig.QWEN_MODEL_PATH
        self.mmproj_path = mmproj_path or ModelConfig.CLIP_PROJECTOR_PATH

        self._proc: subprocess.Popen | None = None
        self._stdout_queue: queue.Queue | None = None
        self._stderr_tail: deque = deque(maxlen=40)
        self._with_vision = False
        self._loaded_layers = None
        self._plan_reason = ""
        self._last_used = 0.0
        self._lock = threading.Lock()

        self._idle_thread = threading.Thread(target=self._idle_watchdog, daemon=True)
        self._idle_thread.start()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def chat(self, messages: list[dict], max_tokens: int = None,
             temperature: float = None) -> str:
        """Run a chat completion. Returns the assistant text ('' on failure)."""
        req = {
            "op": "chat",
            "messages": messages,
            "max_tokens": max_tokens or LLMConfig.MAX_TOKENS,
            "temperature": LLMConfig.TEMPERATURE if temperature is None else temperature,
        }
        return self._run_inference(req, vision=False)

    def chat_stream(self, messages: list[dict], max_tokens: int = None,
                    temperature: float = None):
        """Stream a chat completion token-by-token. Yields text chunks.

        Holds the model lock for the whole generation (the single worker can
        only serve one request at a time), so callers should consume it
        promptly. Yields nothing on failure.
        """
        req = {
            "op": "chat_stream",
            "messages": messages,
            "max_tokens": max_tokens or LLMConfig.MAX_TOKENS,
            "temperature": LLMConfig.TEMPERATURE if temperature is None else temperature,
        }
        with self._lock:
            try:
                self._ensure_loaded(False)
            except ModelManagerError as e:
                print(f"[ModelManager] {e}")
                return
            try:
                yield from self._request_stream(req, idle_timeout=LLMConfig.SUBPROCESS_TIMEOUT)
            except ModelManagerError as e:
                print(f"[ModelManager] Streaming inference failed: {e}")
                self._stop_worker()  # fresh start next time
            finally:
                self._last_used = time.time()

    def analyze_image(self, image_path: str, prompt: str,
                      max_tokens: int = 256) -> str:
        """Describe an image using the vision projector. '' on failure."""
        req = {"op": "vision", "image_path": image_path,
               "prompt": prompt, "max_tokens": max_tokens}
        return self._run_inference(req, vision=True)

    def unload(self):
        """Stop the worker and free all VRAM/RAM held by the model."""
        with self._lock:
            self._stop_worker()

    def status(self) -> dict:
        alive = self._proc is not None and self._proc.poll() is None
        return {
            "worker_alive": alive,
            "loaded": alive and self._loaded_layers is not None,
            "n_gpu_layers": self._loaded_layers if alive else None,
            "vision_enabled": self._with_vision if alive else False,
            "plan": self._plan_reason,
        }

    # ------------------------------------------------------------------
    # Inference orchestration
    # ------------------------------------------------------------------

    def _run_inference(self, req: dict, vision: bool) -> str:
        with self._lock:
            try:
                self._ensure_loaded(vision)
            except ModelManagerError as e:
                print(f"[ModelManager] {e}")
                return ""

            try:
                resp = self._request(req, timeout=LLMConfig.SUBPROCESS_TIMEOUT)
            except ModelManagerError as e:
                print(f"[ModelManager] Inference failed: {e}")
                self._stop_worker()  # fresh start next time
                return ""
            finally:
                self._last_used = time.time()

            if resp.get("ok"):
                return resp.get("result", "")
            print(f"[ModelManager] Worker error: {resp.get('error')}")
            return ""

    def _ensure_loaded(self, vision: bool):
        """Make sure a worker with the right capabilities has the model loaded.

        Walks down the offload ladder across worker restarts: if the worker
        process dies during a load attempt (native OOM aborts don't raise
        Python exceptions), retry with the remaining, more conservative rungs.
        """
        alive = self._proc is not None and self._proc.poll() is None
        needs_restart = not alive or (vision and not self._with_vision)
        if alive and not needs_restart:
            return

        if not os.path.exists(self.model_path):
            raise ModelManagerError(
                f"Model file not found: {self.model_path} — set QWEN_MODEL_PATH "
                f"or place the GGUF in the models/ folder.")
        if vision and not os.path.exists(self.mmproj_path):
            raise ModelManagerError(
                f"Vision projector not found: {self.mmproj_path} — set CLIP_PROJECTOR_PATH.")

        plan_info = plan_gpu_layers(
            self.model_path,
            n_ctx=LLMConfig.N_CTX,
            mmproj_path=self.mmproj_path if vision else None,
            reserve_mb=LLMConfig.VRAM_RESERVE_MB,
            override=LLMConfig.N_GPU_LAYERS,
        )
        self._plan_reason = plan_info["reason"]
        plan = plan_info["plan"]
        print(f"[ModelManager] Offload plan: {plan} ({plan_info['reason']})")

        while plan:
            self._stop_worker()
            self._start_worker(vision, plan)
            try:
                resp = self._request({"op": "load"}, timeout=LLMConfig.LOAD_TIMEOUT)
            except ModelManagerError as e:
                # Worker died mid-load (likely a native OOM abort). Drop the
                # most optimistic rung and retry with the rest of the ladder.
                print(f"[ModelManager] Worker died during load ({e}); "
                      f"retrying with more conservative plan {plan[1:]}")
                plan = plan[1:]
                continue

            if resp.get("ok"):
                self._loaded_layers = resp.get("n_gpu_layers")
                print(f"[ModelManager] Model resident (n_gpu_layers={self._loaded_layers}, "
                      f"vision={'on' if vision else 'off'}).")
                return
            # Worker survived but every rung raised a Python exception —
            # a real load error (bad file, unsupported arch), not OOM.
            self._stop_worker()
            raise ModelManagerError(
                f"Model failed to load: {resp.get('error')}\n"
                f"  Recent worker output:\n    " + "\n    ".join(self._stderr_tail))

        self._stop_worker()
        raise ModelManagerError(
            "Model could not be loaded even in CPU-only mode.\n"
            "  Recent worker output:\n    " + "\n    ".join(self._stderr_tail))

    # ------------------------------------------------------------------
    # Worker process management
    # ------------------------------------------------------------------

    def _start_worker(self, vision: bool, plan: list[int]):
        if not os.path.exists(self.model_path):
            raise ModelManagerError(f"Model file not found: {self.model_path}")
        if vision and not os.path.exists(self.mmproj_path):
            raise ModelManagerError(f"Vision projector not found: {self.mmproj_path}")

        cfg = {
            "model_path": self.model_path,
            "mmproj_path": self.mmproj_path,
            "with_vision": vision,
            "plan": plan,
            "n_ctx": LLMConfig.N_CTX,
            "n_threads": LLMConfig.N_THREADS,
        }
        self._proc = subprocess.Popen(
            [sys.executable, "-c", _WORKER_SCRIPT, json.dumps(cfg)],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, encoding="utf-8", errors="replace", bufsize=1,
        )
        self._with_vision = vision
        self._loaded_layers = None
        self._stdout_queue = queue.Queue()
        self._stderr_tail.clear()

        threading.Thread(target=self._drain_stdout,
                         args=(self._proc, self._stdout_queue), daemon=True).start()
        threading.Thread(target=self._drain_stderr,
                         args=(self._proc,), daemon=True).start()

    def _stop_worker(self):
        proc, self._proc = self._proc, None
        self._loaded_layers = None
        if proc is None or proc.poll() is not None:
            return
        try:
            proc.stdin.write(json.dumps({"op": "exit"}) + "\n")
            proc.stdin.flush()
            proc.wait(timeout=10)
            print("[ModelManager] Worker stopped — model unloaded, VRAM freed.")
        except Exception:
            proc.kill()
            print("[ModelManager] Worker killed.")

    def _request(self, req: dict, timeout: int) -> dict:
        proc = self._proc
        if proc is None or proc.poll() is not None:
            raise ModelManagerError("Worker process is not running.")
        try:
            proc.stdin.write(json.dumps(req) + "\n")
            proc.stdin.flush()
        except OSError as e:
            raise ModelManagerError(f"Could not write to worker: {e}")

        deadline = time.time() + timeout
        while True:
            remaining = deadline - time.time()
            if remaining <= 0:
                raise ModelManagerError(f"Worker timed out after {timeout}s (op={req.get('op')}).")
            try:
                line = self._stdout_queue.get(timeout=min(remaining, 1.0))
            except queue.Empty:
                if proc.poll() is not None:
                    raise ModelManagerError(
                        f"Worker exited unexpectedly (code {proc.returncode}).")
                continue
            if line is None:  # stdout closed
                raise ModelManagerError(
                    f"Worker closed unexpectedly (code {proc.poll()}).")
            try:
                return json.loads(line)
            except json.JSONDecodeError:
                continue  # stray non-protocol line; keep reading

    def _request_stream(self, req: dict, idle_timeout: int):
        """Send a streaming request and yield token chunks until the worker
        signals `done`. `idle_timeout` bounds the wait *between* tokens, not the
        whole generation (which is naturally bounded by max_tokens).
        """
        proc = self._proc
        if proc is None or proc.poll() is not None:
            raise ModelManagerError("Worker process is not running.")
        try:
            proc.stdin.write(json.dumps(req) + "\n")
            proc.stdin.flush()
        except OSError as e:
            raise ModelManagerError(f"Could not write to worker: {e}")

        try:
            while True:
                msg = self._read_one(proc, idle_timeout, op=req.get("op"))
                if msg.get("done"):
                    return
                if not msg.get("ok", True):
                    raise ModelManagerError(msg.get("error", "stream error"))
                chunk = msg.get("chunk")
                if chunk:
                    yield chunk
        except GeneratorExit:
            # Consumer stopped early (e.g. client disconnect). The worker is
            # still generating; drain the rest so the leftover lines don't
            # corrupt the next request. If it doesn't finish quickly, restart.
            self._drain_stream(proc, timeout=30)
            raise

    def _read_one(self, proc, timeout: int, op: str = None) -> dict:
        """Block until the next JSON protocol line arrives (or timeout)."""
        deadline = time.time() + timeout
        while True:
            remaining = deadline - time.time()
            if remaining <= 0:
                raise ModelManagerError(f"Worker timed out after {timeout}s (op={op}).")
            try:
                line = self._stdout_queue.get(timeout=min(remaining, 1.0))
            except queue.Empty:
                if proc.poll() is not None:
                    raise ModelManagerError(
                        f"Worker exited unexpectedly (code {proc.returncode}).")
                continue
            if line is None:  # stdout closed
                raise ModelManagerError(f"Worker closed unexpectedly (code {proc.poll()}).")
            try:
                return json.loads(line)
            except json.JSONDecodeError:
                continue  # stray non-protocol line; keep reading

    def _drain_stream(self, proc, timeout: int):
        """Discard remaining stream lines until the terminal marker, so the
        worker is reusable. Restarts the worker if draining doesn't complete."""
        deadline = time.time() + timeout
        while time.time() < deadline:
            try:
                line = self._stdout_queue.get(timeout=min(deadline - time.time(), 1.0))
            except queue.Empty:
                if proc.poll() is not None:
                    return
                continue
            if line is None:
                return
            try:
                msg = json.loads(line)
            except json.JSONDecodeError:
                continue
            if msg.get("done") or not msg.get("ok", True):
                return
        # Never reached the terminal marker — drop the worker so leftover
        # tokens can't be misread as the next request's reply.
        self._stop_worker()

    def _drain_stdout(self, proc, q):
        try:
            for line in proc.stdout:
                q.put(line)
        except Exception:
            pass
        q.put(None)

    def _drain_stderr(self, proc):
        try:
            for line in proc.stderr:
                line = line.rstrip()
                if line:
                    self._stderr_tail.append(line)
                    print(line)
        except Exception:
            pass

    # ------------------------------------------------------------------
    # Idle unload
    # ------------------------------------------------------------------

    def _idle_watchdog(self):
        while True:
            time.sleep(30)
            idle_limit = LLMConfig.IDLE_UNLOAD_SECONDS
            if idle_limit <= 0:
                continue
            alive = self._proc is not None and self._proc.poll() is None
            if not alive or not self._last_used:
                continue
            if time.time() - self._last_used < idle_limit:
                continue
            # Don't unload mid-request; skip this tick if busy.
            if self._lock.acquire(blocking=False):
                try:
                    if self._proc and time.time() - self._last_used >= idle_limit:
                        print(f"[ModelManager] Idle for {idle_limit}s — unloading model.")
                        self._stop_worker()
                finally:
                    self._lock.release()


# ---------------------------------------------------------------------------
# Singleton accessor
# ---------------------------------------------------------------------------
# One manager per distinct model path. The main chat model lives under the
# default key; an optional extraction model gets its own manager (and its own
# worker process), so the two never fight over the same slot. Each manager
# plans its GPU offload from whatever VRAM is free at load time, so they
# coexist safely on a small GPU (the busier one simply spills to CPU).
_managers: dict[str, ModelManager] = {}
_manager_lock = threading.Lock()


def get_model_manager(model_path: str | None = None) -> ModelManager:
    """Return the shared manager for `model_path` (None = the main chat model)."""
    key = model_path or "__default__"
    with _manager_lock:
        m = _managers.get(key)
        if m is None:
            m = ModelManager(model_path=model_path)
            _managers[key] = m
        return m


def shutdown_model_manager():
    """Stop every model worker and free all VRAM/RAM."""
    with _manager_lock:
        for m in _managers.values():
            try:
                m.unload()
            except Exception:
                pass
        _managers.clear()
