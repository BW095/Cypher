import gc
import torch
import base64
from llama_cpp import Llama
from llama_cpp.llama_chat_format import Llava15ChatHandler


class QwenVLWrapper:
    def __init__(self,
                 model_path="./models/llava-v1.5-7b-Q4_K.gguf",
                 clip_path="./models/llava-v1.5-7b-mmproj-f16.gguf"):
        self.model_path = model_path
        self.clip_path = clip_path

    def analyze_image(self, image_path: str, prompt: str) -> str:
        print(f"Loading Vision LLM for {image_path}...")

        # 1. Initialize multimodal support
        chat_handler = Llava15ChatHandler(clip_model_path=self.clip_path)
        llm = Llama(
            model_path=self.model_path,
            chat_handler=chat_handler,
            n_gpu_layers=-1,
            n_ctx=4096,
            verbose=False
        )

        try:
            # 2. Encode the image into base64
            with open(image_path, "rb") as image_file:
                encoded_string = base64.b64encode(image_file.read()).decode('utf-8')
            image_url = f"data:image/jpeg;base64,{encoded_string}"

            # 3. Generate response
            output = llm.create_chat_completion(
                messages=[
                    {"role": "system", "content": "You perfectly describe industrial equipment and environments."},
                    {
                        "role": "user",
                        "content": [
                            {"type": "image_url", "image_url": {"url": image_url}},
                            {"type": "text", "text": prompt}
                        ]
                    }
                ],
                max_tokens=256
            )
            return output["choices"][0]["message"]["content"]

        except Exception as e:
            print(f"Vision Generation failed: {e}")
            return ""

        finally:
            # 4. Flush Memory
            del llm
            if torch.cuda.is_available():
                torch.cuda.empty_cache()
            gc.collect()