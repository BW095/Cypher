"""
Text LLM interface — provider-aware factory.

Set LLM_PROVIDER in your environment (or backend/.env) to choose:

  LLM_PROVIDER=local    (default) — local GGUF model via llama-cpp-python
  LLM_PROVIDER=bedrock  — AWS Bedrock Nova Pro via boto3 Converse API

The public API (generate / generate_with_history /
generate_with_history_stream / extract_entities / analyze_image / unload)
is identical for both providers, so QueryEngine, EntityExtractor, and
every other caller is unaffected by the switch.
"""

import os

# Load backend/.env (if it exists) before reading any config values.
# This must happen before importing app.config so the env vars are visible.
try:
    from dotenv import load_dotenv
    _env_path = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__)))), ".env")
    load_dotenv(_env_path, override=False)   # don't override values already in env
except ImportError:
    pass  # python-dotenv not installed; rely on the shell environment


class LLMWrapper:
    """Thin shim that delegates to the active provider backend.

    Instantiate this exactly as before — the provider selection is
    transparent to all callers.
    """

    def __new__(cls, model_path: str = None):
        """Return the right backend instance based on LLM_PROVIDER."""
        provider = os.getenv("LLM_PROVIDER", "local").strip().lower()

        if provider == "bedrock":
            from app.ai.bedrock_llm import BedrockLLMWrapper
            instance = object.__new__(BedrockLLMWrapper)
            BedrockLLMWrapper.__init__(instance)
            return instance

        # Default: local GGUF model via ModelManager.
        from app.ai.model_manager import get_model_manager
        instance = object.__new__(_LocalLLMWrapper)
        _LocalLLMWrapper.__init__(instance, model_path)
        return instance


class _LocalLLMWrapper:
    """Original local GGUF implementation (unchanged from before)."""

    def __init__(self, model_path: str = None):
        from app.ai.model_manager import get_model_manager
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
