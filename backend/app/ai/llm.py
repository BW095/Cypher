"""
Text LLM interface — Amazon Bedrock backend.

Uses the Bedrock **Converse API** which works uniformly with all models:
  - Amazon Nova Pro / Nova Lite  (no Anthropic form needed)
  - Anthropic Claude 3.5 Haiku  (needs Anthropic FTU form once)
  - Any other Converse-compatible model

Switch models via BEDROCK_CHAT_MODEL_ID env var without code changes.
"""

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
        return self._converse(
            messages=[{"role": "user", "content": [{"text": prompt}]}],
            system_prompt=system_prompt,
            max_tokens=max_tokens or BedrockConfig.MAX_TOKENS,
        )

    def generate_with_history(self, messages: list[dict], max_tokens: int = None) -> str:
        """Multi-turn generation with a full message history. '' on failure."""
        system_prompt, converse_messages = self._split_system(messages)
        return self._converse(
            messages=converse_messages,
            system_prompt=system_prompt,
            max_tokens=max_tokens or BedrockConfig.MAX_TOKENS,
        )

    def generate_with_history_stream(self, messages: list[dict], max_tokens: int = None):
        """Streaming variant — yields text chunks."""
        system_prompt, converse_messages = self._split_system(messages)
        yield from self._converse_stream(
            messages=converse_messages,
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
        """Separate the system message from the chat messages and convert to
        Converse API format (content must be a list of blocks, not a string)."""
        system = ""
        chat = []
        for m in messages:
            if m.get("role") == "system":
                system = m.get("content", "")
            else:
                content = m.get("content", "")
                # Converse API requires content as a list of blocks
                if isinstance(content, str):
                    chat.append({"role": m["role"], "content": [{"text": content}]})
                elif isinstance(content, list):
                    # Already a list — ensure it's in Converse block format
                    blocks = []
                    for block in content:
                        if isinstance(block, str):
                            blocks.append({"text": block})
                        elif isinstance(block, dict):
                            if "text" in block:
                                blocks.append({"text": block["text"]})
                            elif block.get("type") == "image":
                                # Convert Claude-style image block to Converse format
                                src = block.get("source", {})
                                blocks.append({
                                    "image": {
                                        "format": src.get("media_type", "image/jpeg").split("/")[-1],
                                        "source": {
                                            "bytes": src.get("data", b""),
                                        },
                                    }
                                })
                    chat.append({"role": m["role"], "content": blocks})
                else:
                    chat.append({"role": m["role"], "content": [{"text": str(content)}]})

        # Converse requires strict user/assistant alternation, starting with user
        chat = _merge_consecutive(chat)
        return system, chat

    def _converse(self, messages: list[dict], system_prompt: str = "",
                  max_tokens: int = 1024) -> str:
        """Blocking chat completion via Bedrock Converse API."""
        if not messages:
            return ""
        try:
            kwargs = {
                "modelId": self.model_id,
                "messages": messages,
                "inferenceConfig": {
                    "maxTokens": max_tokens,
                    "temperature": BedrockConfig.TEMPERATURE,
                },
            }
            if system_prompt:
                kwargs["system"] = [{"text": system_prompt}]

            response = self.client.converse(**kwargs)
            return _extract_text_converse(response)
        except Exception as e:
            print(f"[Bedrock LLM] Error: {e}")
            return ""

    def _converse_stream(self, messages: list[dict], system_prompt: str = "",
                         max_tokens: int = 1024):
        """Streaming chat completion via Bedrock Converse Stream API."""
        if not messages:
            return
        try:
            kwargs = {
                "modelId": self.model_id,
                "messages": messages,
                "inferenceConfig": {
                    "maxTokens": max_tokens,
                    "temperature": BedrockConfig.TEMPERATURE,
                },
            }
            if system_prompt:
                kwargs["system"] = [{"text": system_prompt}]

            response = self.client.converse_stream(**kwargs)
            for event in response["stream"]:
                if "contentBlockDelta" in event:
                    delta = event["contentBlockDelta"].get("delta", {})
                    text = delta.get("text", "")
                    if text:
                        yield text
        except Exception as e:
            print(f"[Bedrock LLM] Stream error: {e}")


# ------------------------------------------------------------------
# Module-level helpers
# ------------------------------------------------------------------

def _merge_consecutive(messages: list[dict]) -> list[dict]:
    """Merge consecutive messages with the same role.

    Converse API requires strict user/assistant alternation.
    """
    if not messages:
        return []
    merged = [messages[0].copy()]
    for m in messages[1:]:
        if m["role"] == merged[-1]["role"]:
            # Merge content blocks
            prev_content = merged[-1].get("content", [])
            curr_content = m.get("content", [])
            merged[-1]["content"] = prev_content + curr_content
        else:
            merged.append(m.copy())
    # Ensure starts with user
    if merged and merged[0].get("role") != "user":
        merged.insert(0, {"role": "user", "content": [{"text": "(continuing conversation)"}]})
    return merged


def _extract_text_converse(response: dict) -> str:
    """Extract text from a Bedrock Converse API response."""
    try:
        output = response.get("output", {})
        message = output.get("message", {})
        content = message.get("content", [])
        parts = [block.get("text", "") for block in content if "text" in block]
        return "\n".join(parts).strip()
    except Exception:
        return ""
