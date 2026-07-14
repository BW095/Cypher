import gc
import torch
from llama_cpp import Llama


class LLMWrapper:
    def __init__(self, model_path: str = "./models/qwen2.5-7b-instruct-q4_k_m.gguf"):
        self.model_path = model_path

    def extract_entities(self, text: str) -> str:
        print("Loading Text LLM into VRAM...")

        # 1. Load the model with GPU offloading (-1 means offload all layers)
        llm = Llama(
            model_path=self.model_path,
            n_gpu_layers=-1,
            n_ctx=4096,
            verbose=False
        )

        prompt = f"Extract key industrial entities from the following text and format as JSON:\n\n{text}"

        try:
            # 2. Generate response using OpenAI-compatible format
            output = llm.create_chat_completion(
                messages=[
                    {"role": "system", "content": "You are a helpful industrial AI assistant. Return valid JSON only."},
                    {"role": "user", "content": prompt}
                ],
                max_tokens=512,
                temperature=0.1
            )
            return output["choices"][0]["message"]["content"]

        except Exception as e:
            print(f"LLM Generation failed: {e}")
            return ""

        finally:
            # 3. Flush Memory
            del llm
            if torch.cuda.is_available():
                torch.cuda.empty_cache()
            gc.collect()