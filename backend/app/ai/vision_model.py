import gc
import os
import sys
import json
import torch
import base64
import subprocess
import tempfile

# Resolve the project root (two levels up from this file: ai/ -> app/ -> backend/)
_BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_PROJECT_ROOT = os.path.dirname(_BACKEND_DIR)
_DEFAULT_MODEL_PATH = os.path.join(_PROJECT_ROOT, "models", "Qwen3VL-8B-Instruct-Q4_K_M.gguf")
_DEFAULT_CLIP_PATH = os.path.join(_PROJECT_ROOT, "models", "mmproj-Qwen3VL-8B-Instruct-Q8_0.gguf")

# Standalone script run in a subprocess so a native crash can't kill the main process
_VISION_WORKER_SCRIPT = '''
import sys, json, gc, base64, torch
from llama_cpp import Llama
from llama_cpp.llama_chat_format import Qwen3VLChatHandler

args = json.loads(sys.argv[1])
model_path = args["model_path"]
clip_path = args["clip_path"]
image_path = args["image_path"]
prompt = args["prompt"]

try:
    chat_handler = Qwen3VLChatHandler(mmproj_path=clip_path, verbose=False)
    llm = Llama(
        model_path=model_path,
        chat_handler=chat_handler,
        n_gpu_layers=-1,
        n_ctx=4096,
        verbose=False,
    )

    with open(image_path, "rb") as f:
        encoded = base64.b64encode(f.read()).decode("utf-8")
    image_url = f"data:image/jpeg;base64,{encoded}"

    output = llm.create_chat_completion(
        messages=[
            {"role": "system", "content": "You perfectly describe industrial equipment and environments."},
            {
                "role": "user",
                "content": [
                    {"type": "image_url", "image_url": {"url": image_url}},
                    {"type": "text", "text": prompt},
                ],
            },
        ],
        max_tokens=256,
    )
    result = output["choices"][0]["message"]["content"]
    print(json.dumps({"ok": True, "result": result}))

except Exception as e:
    print(json.dumps({"ok": False, "error": str(e)}))

finally:
    try:
        del llm
    except:
        pass
    if torch.cuda.is_available():
        torch.cuda.empty_cache()
    gc.collect()
'''


class QwenVLWrapper:
    def __init__(self, model_path=None, clip_path=None):
        self.model_path = model_path or _DEFAULT_MODEL_PATH
        self.clip_path = clip_path or _DEFAULT_CLIP_PATH

    def analyze_image(self, image_path: str, prompt: str) -> str:
        """Runs the vision model in a subprocess for crash isolation.

        The Qwen3VL CLIP projector can SIGABRT if VRAM is insufficient.
        Running in a subprocess prevents that from killing the main pipeline.
        """
        print(f"Loading Vision LLM for {image_path} (in subprocess)...")
        sys.stdout.flush()

        args_json = json.dumps({
            "model_path": self.model_path,
            "clip_path": self.clip_path,
            "image_path": image_path,
            "prompt": prompt,
        })

        try:
            result = subprocess.run(
                [sys.executable, "-c", _VISION_WORKER_SCRIPT, args_json],
                capture_output=True,
                text=True,
                timeout=300,  # 5 minute timeout
            )

            if result.returncode != 0:
                print(f"Vision subprocess crashed (exit code {result.returncode}).")
                print(f"  stderr: {result.stderr[-500:] if result.stderr else 'none'}")
                return ""

            # Parse the last line of stdout (the JSON result)
            stdout_lines = result.stdout.strip().split("\n")
            output = json.loads(stdout_lines[-1])

            if output.get("ok"):
                return output["result"]
            else:
                print(f"Vision model error: {output.get('error')}")
                return ""

        except subprocess.TimeoutExpired:
            print("Vision model timed out after 5 minutes.")
            return ""
        except Exception as e:
            print(f"Vision subprocess failed: {e}")
            return ""