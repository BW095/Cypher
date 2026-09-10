"""
Text LLM interface — Bedrock Mantle (OpenAI-compatible API).

Uses the OpenAI SDK pointing at the Bedrock Mantle endpoint
(https://bedrock-mantle.us-east-1.api.aws/v1).

This works on free-tier AWS accounts where direct Bedrock InvokeModel /
Converse APIs return "Operation not allowed".

Switch models via BEDROCK_CHAT_MODEL_ID env var without code changes.
"""

from openai import OpenAI

from app.config import BedrockConfig


class LLMWrapper:
    def __init__(self, model_id: str = None):
        self.model_id = model_id or BedrockConfig.CHAT_MODEL_ID
        self._client = None

    @property
    def client(self) -> OpenAI:
        if self._client is None:
            self._client = OpenAI(
                base_url=BedrockConfig.MANTLE_BASE_URL,
                api_key=BedrockConfig.MANTLE_API_KEY,
                default_headers={"OpenAI-Project": "default"},
            )
        return self._client

    def generate(self, prompt: str, system_prompt: str = "You are a helpful AI assistant.",
                 max_tokens: int = None) -> str:
        """Single-turn generation. Returns '' on failure."""
        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})
        return self._chat(messages, max_tokens=max_tokens or BedrockConfig.MAX_TOKENS)

    def generate_with_history(self, messages: list[dict], max_tokens: int = None) -> str:
        """Multi-turn generation with a full message history. '' on failure."""
        openai_messages = self._to_openai_messages(messages)
        return self._chat(openai_messages, max_tokens=max_tokens or BedrockConfig.MAX_TOKENS)

    def generate_with_history_stream(self, messages: list[dict], max_tokens: int = None):
        """Streaming variant — yields text chunks."""
        openai_messages = self._to_openai_messages(messages)
        yield from self._chat_stream(
            openai_messages,
            max_tokens=max_tokens or BedrockConfig.MAX_TOKENS,
        )

    def extract_entities(self, text: str) -> str:
        """Legacy method — kept for backward compatibility."""
        system_prompt = "You are a helpful industrial AI assistant. Return valid JSON only."
        prompt = f"Extract key industrial entities from the following text and format as JSON:\n\n{text}"
        return self.generate(prompt, system_prompt)

    def unload(self):
        """No-op — there's no local model to unload."""
        pass

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _to_openai_messages(messages: list[dict]) -> list[dict]:
        """Convert internal message format to OpenAI format.

        Internal format may have content as:
          - a string
          - a list of blocks like [{"text": "..."}, {"type": "image", ...}]
        OpenAI expects content as a string (for text-only).
        """
        result = []
        for m in messages:
            role = m.get("role", "user")
            content = m.get("content", "")

            if isinstance(content, str):
                result.append({"role": role, "content": content})
            elif isinstance(content, list):
                # Flatten text blocks; skip image blocks (Mantle is text-only)
                text_parts = []
                for block in content:
                    if isinstance(block, str):
                        text_parts.append(block)
                    elif isinstance(block, dict):
                        if "text" in block:
                            text_parts.append(block["text"])
                combined = "\n".join(text_parts)
                if combined.strip():
                    result.append({"role": role, "content": combined})
            else:
                result.append({"role": role, "content": str(content)})

        # OpenAI requires messages to start with user or system
        if result and result[0].get("role") == "assistant":
            result.insert(0, {"role": "user", "content": "(continuing conversation)"})

        return result

    def _chat(self, messages: list[dict], max_tokens: int = 1024) -> str:
        """Blocking chat completion via OpenAI SDK."""
        if not messages:
            return ""
        try:
            response = self.client.chat.completions.create(
                model=self.model_id,
                messages=messages,
                max_tokens=max_tokens,
                temperature=BedrockConfig.TEMPERATURE,
            )
            return response.choices[0].message.content or ""
        except Exception as e:
            print(f"[Mantle LLM] Error: {e}")
            return ""

    def _chat_stream(self, messages: list[dict], max_tokens: int = 1024):
        """Streaming chat completion via OpenAI SDK."""
        if not messages:
            return
        try:
            stream = self.client.chat.completions.create(
                model=self.model_id,
                messages=messages,
                max_tokens=max_tokens,
                temperature=BedrockConfig.TEMPERATURE,
                stream=True,
            )
            for chunk in stream:
                if chunk.choices and chunk.choices[0].delta.content:
                    yield chunk.choices[0].delta.content
        except Exception as e:
            print(f"[Mantle LLM] Stream error: {e}")
