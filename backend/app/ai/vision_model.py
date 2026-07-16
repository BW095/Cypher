"""
Vision model interface (Qwen3VL + CLIP projector).

Delegates to the shared ModelManager: the same resident Qwen3VL weights
serve text and vision, and the mmproj/CLIP handler is loaded on demand
(the manager restarts its worker with vision enabled and re-plans GPU
offload to account for the projector's VRAM).
"""

from app.ai.model_manager import get_model_manager


class QwenVLWrapper:
    def __init__(self, model_path=None, clip_path=None):
        self.manager = get_model_manager()
        if model_path:
            self.manager.model_path = model_path
        if clip_path:
            self.manager.mmproj_path = clip_path

    def analyze_image(self, image_path: str, prompt: str) -> str:
        """Describe an image. Returns '' on failure."""
        print(f"Analyzing image with Vision LLM: {image_path}")
        return self.manager.analyze_image(image_path, prompt)
