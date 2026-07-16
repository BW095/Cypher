"""
Text LLM interface.

Thin wrapper around the shared ModelManager, which keeps the GGUF model
resident in a persistent worker process, picks GPU offload adaptively from
free VRAM (falling back to CPU), and unloads after idle. See
app/ai/model_manager.py for the mechanics.

The public API (generate / generate_with_history / extract_entities) is
unchanged, so EntityExtractor and QueryEngine work as before.
"""

from app.ai.model_manager import get_model_manager


class LLMWrapper:
    def __init__(self, model_path: str = None):
        # model_path override is honored only if no manager exists yet;
        # the whole app shares one model slot by design.
        self.manager = get_model_manager()
        if model_path:
            self.manager.model_path = model_path

    def generate(self, prompt: str, system_prompt: str = "You are a helpful AI assistant.",
                 max_tokens: int = 1024) -> str:
        """Single-turn generation. Returns '' on failure."""
        return self.manager.chat(
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": prompt},
            ],
            max_tokens=max_tokens,
        )

    def generate_with_history(self, messages: list[dict], max_tokens: int = 1024) -> str:
        """Multi-turn generation with a full message history. '' on failure."""
        return self.manager.chat(messages=messages, max_tokens=max_tokens)

    def extract_entities(self, text: str) -> str:
        """Legacy method — kept for backward compatibility."""
        system_prompt = "You are a helpful industrial AI assistant. Return valid JSON only."
        prompt = f"Extract key industrial entities from the following text and format as JSON:\n\n{text}"
        return self.generate(prompt, system_prompt)

    def unload(self):
        """Free the model's VRAM/RAM immediately."""
        self.manager.unload()
