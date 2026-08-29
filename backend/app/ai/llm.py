"""
Text LLM interface — Amazon Bedrock (Claude) backend.

Replaces the local GGUF/llama.cpp ModelManager with boto3 calls to
Amazon Bedrock. The public API (generate / generate_with_history /
generate_with_history_stream) is unchanged, so QueryEngine and
EntityExtractor work without modification.
"""

import json
import boto3

from app.config import BedrockConfig


class LLMWrapper:
    def __init__(self, model_id: str = None):
        self.model_id = model_id or BedrockConfig.CHAT_MODEL_ID
        self._client = None

    @property
    def client(self):
        if self._client is None:
            self._client = boto3.client(
                "bedrock-runtime",
                region_name=BedrockConfig.REGION,
            )
        return self._client

    def generate(self, prompt: str, system_prompt: str = "You are a helpful AI assistant.",
                 max_tokens: int = None) -> str:
        """Single-turn generation. Returns '' on failure."""
        return self._chat(
            messages=[{"role": "user", "content": prompt}],
            system_prompt=system_prompt,
            max_tokens=max_tokens or BedrockConfig.MAX_TOKENS,
        )

    def generate_with_history(self, messages: list[dict], max_tokens: int = None) -> str:
        """Multi-turn generation with a full message history. '' on failure."""
        system_prompt, chat_messages = self._split_system(messages)
        return self._chat(
            messages=chat_messages,
            system_prompt=system_prompt,
            max_tokens=max_tokens or BedrockConfig.MAX_TOKENS,
        )

    def generate_with_history_stream(self, messages: list[dict], max_tokens: int = None):
        """Streaming variant — yields text chunks."""
        system_prompt, chat_messages = self._split_system(messages)
        yield from self._chat_stream(
            messages=chat_messages,
            system_prompt=system_prompt,
            max_tokens=max_tokens or BedrockConfig.MAX_TOKENS,
        )

    def extract_entities(self, text: str) -> str:
        """Legacy method — kept for backward compatibility."""
        system_prompt = "You are a helpful industrial AI assistant. Return valid JSON only."
        prompt = f"Extract key industrial entities from the following text and format as JSON:\n\n{text}"
        return self.generate(prompt, system_prompt)

    def unload(self):
        """No-op for Bedrock — there's no local model to unload."""
        pass

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _split_system(messages: list[dict]) -> tuple[str, list[dict]]:
        """Separate the system message from the chat messages.

        Claude's Messages API takes system as a top-level param, not in
        the messages list.
        """
        system = ""
        chat = []
        for m in messages:
            if m.get("role") == "system":
                system = m.get("content", "")
            else:
                chat.append(m)
        # Claude requires messages to start with "user" and alternate.
        # Merge consecutive same-role messages if the history is malformed.
        chat = _merge_consecutive(chat)
        return system, chat

    def _chat(self, messages: list[dict], system_prompt: str = "",
              max_tokens: int = 1024) -> str:
        """Blocking chat completion via Bedrock invoke_model."""
        if not messages:
            return ""
        try:
            body = {
                "anthropic_version": "bedrock-2023-05-31",
                "max_tokens": max_tokens,
                "temperature": BedrockConfig.TEMPERATURE,
                "messages": _format_messages(messages),
            }
            if system_prompt:
                body["system"] = system_prompt

            response = self.client.invoke_model(
                modelId=self.model_id,
                contentType="application/json",
                accept="application/json",
                body=json.dumps(body),
            )
            result = json.loads(response["body"].read())
            return _extract_text(result)
        except Exception as e:
            print(f"[Bedrock LLM] Error: {e}")
            return ""

    def _chat_stream(self, messages: list[dict], system_prompt: str = "",
                     max_tokens: int = 1024):
        """Streaming chat completion via Bedrock invoke_model_with_response_stream."""
        if not messages:
            return
        try:
            body = {
                "anthropic_version": "bedrock-2023-05-31",
                "max_tokens": max_tokens,
                "temperature": BedrockConfig.TEMPERATURE,
                "messages": _format_messages(messages),
            }
            if system_prompt:
                body["system"] = system_prompt

            response = self.client.invoke_model_with_response_stream(
                modelId=self.model_id,
                contentType="application/json",
                accept="application/json",
                body=json.dumps(body),
            )
            for event in response["body"]:
                chunk = json.loads(event["chunk"]["bytes"])
                if chunk.get("type") == "content_block_delta":
                    delta = chunk.get("delta", {})
                    text = delta.get("text", "")
                    if text:
                        yield text
        except Exception as e:
            print(f"[Bedrock LLM] Stream error: {e}")


# ------------------------------------------------------------------
# Module-level helpers
# ------------------------------------------------------------------

def _format_messages(messages: list[dict]) -> list[dict]:
    """Convert messages to the Claude Messages API format.

    Each message content can be a string or a list of content blocks
    (for multimodal). This normalizes both.
    """
    formatted = []
    for m in messages:
        content = m.get("content", "")
        role = m.get("role", "user")
        if role not in ("user", "assistant"):
            role = "user"
        # If content is already a list (multimodal), keep it
        if isinstance(content, list):
            formatted.append({"role": role, "content": content})
        else:
            formatted.append({"role": role, "content": str(content)})
    return formatted


def _merge_consecutive(messages: list[dict]) -> list[dict]:
    """Merge consecutive messages with the same role.

    Claude requires strict user/assistant alternation. If the history
    has consecutive user or assistant messages, merge them.
    """
    if not messages:
        return []
    merged = [messages[0].copy()]
    for m in messages[1:]:
        if m["role"] == merged[-1]["role"]:
            # Merge content
            prev = merged[-1].get("content", "")
            curr = m.get("content", "")
            if isinstance(prev, str) and isinstance(curr, str):
                merged[-1]["content"] = prev + "\n\n" + curr
            else:
                merged[-1]["content"] = str(prev) + "\n\n" + str(curr)
        else:
            merged.append(m.copy())
    # Ensure starts with user
    if merged and merged[0].get("role") != "user":
        merged.insert(0, {"role": "user", "content": "(continuing conversation)"})
    return merged


def _extract_text(response: dict) -> str:
    """Extract text from a Claude Messages API response."""
    content = response.get("content", [])
    parts = []
    for block in content:
        if block.get("type") == "text":
            parts.append(block.get("text", ""))
    return "\n".join(parts).strip()
