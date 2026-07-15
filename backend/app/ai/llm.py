import os
import sys
import json
import subprocess

# Resolve the project root (two levels up from this file: ai/ -> app/ -> backend/)
_BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_PROJECT_ROOT = os.path.dirname(_BACKEND_DIR)
_DEFAULT_MODEL_PATH = os.path.join(_PROJECT_ROOT, "models", "Qwen3VL-8B-Instruct-Q4_K_M.gguf")

# Standalone script run in a subprocess so it gets a clean CUDA context.
# This avoids VRAM conflicts with the BGE embedding model (PyTorch holds onto
# GPU memory even after del + empty_cache, leaving insufficient VRAM for GGML).
_LLM_WORKER_SCRIPT = '''
import sys, json, gc, torch
from llama_cpp import Llama

args = json.loads(sys.argv[1])
model_path = args["model_path"]
prompt = args["prompt"]
system_prompt = args["system_prompt"]
max_tokens = args.get("max_tokens", 1024)

try:
    llm = Llama(
        model_path=model_path,
        n_gpu_layers=-1,
        n_ctx=4096,
        verbose=False,
    )

    output = llm.create_chat_completion(
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": prompt},
        ],
        max_tokens=max_tokens,
        temperature=0.1,
    )
    result = output["choices"][0]["message"]["content"]
    print(json.dumps({"ok": True, "result": result}))

except Exception as e:
    print(json.dumps({"ok": False, "error": str(e)}), file=sys.stderr)
    sys.exit(1)

finally:
    try:
        del llm
    except:
        pass
    if torch.cuda.is_available():
        torch.cuda.empty_cache()
    gc.collect()
'''


class LLMWrapper:
    def __init__(self, model_path: str = None):
        self.model_path = model_path or _DEFAULT_MODEL_PATH

    def generate(self, prompt: str, system_prompt: str = "You are a helpful AI assistant.",
                 max_tokens: int = 1024) -> str:
        """Runs LLM generation in a subprocess for clean VRAM isolation."""
        print(f"Loading Text LLM (subprocess) from: {self.model_path}")
        sys.stdout.flush()

        args_json = json.dumps({
            "model_path": self.model_path,
            "prompt": prompt,
            "system_prompt": system_prompt,
            "max_tokens": max_tokens,
        })

        try:
            result = subprocess.run(
                [sys.executable, "-c", _LLM_WORKER_SCRIPT, args_json],
                capture_output=True,
                text=True,
                timeout=300,  # 5 minute timeout
            )

            if result.returncode != 0:
                print(f"LLM subprocess failed (exit code {result.returncode}).")
                if result.stderr:
                    # Try to parse structured error from stderr
                    try:
                        err_data = json.loads(result.stderr.strip().split('\n')[-1])
                        print(f"  Error: {err_data.get('error', 'unknown')}")
                    except (json.JSONDecodeError, IndexError):
                        print(f"  stderr: {result.stderr[-500:]}")
                return ""

            # Parse the last line of stdout (the JSON result)
            stdout_lines = result.stdout.strip().split("\n")
            output = json.loads(stdout_lines[-1])

            if output.get("ok"):
                return output["result"]
            else:
                print(f"LLM error: {output.get('error')}")
                return ""

        except subprocess.TimeoutExpired:
            print("LLM generation timed out after 5 minutes.")
            return ""
        except Exception as e:
            print(f"LLM subprocess failed: {e}")
            return ""

    def extract_entities(self, text: str) -> str:
        """Legacy method — kept for backward compatibility."""
        system_prompt = "You are a helpful industrial AI assistant. Return valid JSON only."
        prompt = f"Extract key industrial entities from the following text and format as JSON:\n\n{text}"
        return self.generate(prompt, system_prompt)

    def generate_with_history(self, messages: list[dict], max_tokens: int = 1024) -> str:
        """Run LLM generation with a full multi-turn message history.

        `messages` is a list of dicts with keys 'role' and 'content',
        e.g. [{"role": "system", ...}, {"role": "user", ...}, {"role": "assistant", ...}, ...]

        Uses the same subprocess isolation as generate() to keep VRAM clean.
        """
        print(f"Loading Text LLM (subprocess, multi-turn) from: {self.model_path}")
        sys.stdout.flush()

        args_json = json.dumps({
            "model_path": self.model_path,
            "messages": messages,
            "max_tokens": max_tokens,
        })

        try:
            result = subprocess.run(
                [sys.executable, "-c", _LLM_CHAT_WORKER_SCRIPT, args_json],
                capture_output=True,
                text=True,
                timeout=300,
            )

            if result.returncode != 0:
                print(f"LLM chat subprocess failed (exit code {result.returncode}).")
                if result.stderr:
                    try:
                        err_data = json.loads(result.stderr.strip().split('\n')[-1])
                        print(f"  Error: {err_data.get('error', 'unknown')}")
                    except (json.JSONDecodeError, IndexError):
                        print(f"  stderr: {result.stderr[-500:]}")
                return ""

            stdout_lines = result.stdout.strip().split("\n")
            output = json.loads(stdout_lines[-1])

            if output.get("ok"):
                return output["result"]
            else:
                print(f"LLM chat error: {output.get('error')}")
                return ""

        except subprocess.TimeoutExpired:
            print("LLM chat generation timed out after 5 minutes.")
            return ""
        except Exception as e:
            print(f"LLM chat subprocess failed: {e}")
            return ""


# ---------------------------------------------------------------------------
# Subprocess worker script for multi-turn chat
# ---------------------------------------------------------------------------
_LLM_CHAT_WORKER_SCRIPT = '''
import sys, json, gc, torch
from llama_cpp import Llama

args = json.loads(sys.argv[1])
model_path = args["model_path"]
messages = args["messages"]
max_tokens = args.get("max_tokens", 1024)

try:
    llm = Llama(
        model_path=model_path,
        n_gpu_layers=-1,
        n_ctx=4096,
        verbose=False,
    )

    output = llm.create_chat_completion(
        messages=messages,
        max_tokens=max_tokens,
        temperature=0.1,
    )
    result = output["choices"][0]["message"]["content"]
    print(json.dumps({"ok": True, "result": result}))

except Exception as e:
    print(json.dumps({"ok": False, "error": str(e)}), file=sys.stderr)
    sys.exit(1)

finally:
    try:
        del llm
    except:
        pass
    if torch.cuda.is_available():
        torch.cuda.empty_cache()
    gc.collect()
'''