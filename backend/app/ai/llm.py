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
        # Each distinct model_path gets its own shared manager/worker. None
        # (the common case) resolves to the main chat model.
        self.manager = get_model_manager(model_path or None)

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

    def generate_with_history_stream(self, messages: list[dict], max_tokens: int = 1024):
        """Streaming variant of generate_with_history — yields text chunks."""
        yield from self.manager.chat_stream(messages=messages, max_tokens=max_tokens)

    def extract_entities(self, text: str) -> str:
        """Legacy method — kept for backward compatibility."""
        system_prompt = "You are a helpful industrial AI assistant. Return valid JSON only."
        prompt = f"Extract key industrial entities from the following text and format as JSON:\n\n{text}"
        return self.generate(prompt, system_prompt)

    def unload(self):
        """Free the model's VRAM/RAM immediately."""
        self.manager.unload()
