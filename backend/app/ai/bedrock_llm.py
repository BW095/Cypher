"""
AWS Bedrock LLM wrapper.

Uses the Bedrock Converse / ConversStream API with the new bearer-token
API key (AWS_BEARER_TOKEN_BEDROCK environment variable).  boto3 >= 1.35
picks up that variable automatically for bedrock-runtime calls.

Exposes the identical public interface as LLMWrapper so that QueryEngine,
EntityExtractor, and every other caller needs zero changes when
LLM_PROVIDER=bedrock is set.

Supported operations
--------------------
  generate(prompt, system_prompt, max_tokens)          -> str
  generate_with_history(messages, max_tokens)          -> str
  generate_with_history_stream(messages, max_tokens)   -> Iterator[str]
  extract_entities(text)                               -> str
  analyze_image(image_path, prompt, max_tokens)        -> str
  unload()                                             -> None  (no-op)
"""

import base64
import os

from app.config import BedrockConfig, LLMConfig


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_client():
    """Return a boto3 bedrock-runtime client.

    boto3 >= 1.35 automatically uses AWS_BEARER_TOKEN_BEDROCK when present,
    so no explicit credential wiring is required.
    """
    import boto3
    return boto3.client("bedrock-runtime", region_name=BedrockConfig.REGION)


def _split_messages(messages: list[dict]) -> tuple[list[dict], list[dict]]:
    """Partition a flat message list into (system_blocks, turn_messages).

    The Bedrock Converse API keeps system instructions in a separate top-level
    key; user/assistant turns go in the 'messages' list.
    """
    system_blocks: list[dict] = []
    turns: list[dict] = []

    for m in messages:
        role = m["role"]
        content = m["content"]

        if role == "system":
            system_blocks.append({"text": content if isinstance(content, str) else str(content)})
        else:
            if isinstance(content, str):
                turns.append({"role": role, "content": [{"text": content}]})
            else:
                # Multi-modal content list (vision requests)
                parts = []
                for part in content:
                    ptype = part.get("type", "")
                    if ptype == "text":
                        parts.append({"text": part["text"]})
                    elif ptype == "image_url":
                        url = part["image_url"]["url"]
                        if url.startswith("data:"):
                            header, b64 = url.split(",", 1)
                            fmt = header.split(";")[0].split("/")[1]
                            parts.append({
                                "image": {
                                    "format": fmt,
                                    "source": {"bytes": base64.b64decode(b64)},
                                }
                            })
                if parts:
                    turns.append({"role": role, "content": parts})

    return system_blocks, turns


def _inference_config(max_tokens: int = None, temperature: float = None) -> dict:
    return {
        "maxTokens": max_tokens or LLMConfig.MAX_TOKENS,
        "temperature": LLMConfig.TEMPERATURE if temperature is None else temperature,
    }


# ---------------------------------------------------------------------------
# Main wrapper class
# ---------------------------------------------------------------------------

class BedrockLLMWrapper:
    """Drop-in replacement for LLMWrapper backed by AWS Bedrock (Nova Pro)."""

    def __init__(self):
        self.model_id = BedrockConfig.MODEL_ID
        self.region   = BedrockConfig.REGION
        if not BedrockConfig.BEARER_TOKEN:
            print(
                "[BedrockLLM] WARNING: AWS_BEARER_TOKEN_BEDROCK is not set. "
                "Set it in backend/.env before making any LLM calls."
            )

    # ------------------------------------------------------------------
    # Core non-streaming call
    # ------------------------------------------------------------------

    def _converse(
        self,
        messages: list[dict],
        max_tokens: int = None,
        temperature: float = None,
    ) -> str:
        """Call the Bedrock Converse API and return the assistant text."""
        system_blocks, turns = _split_messages(messages)
        if not turns:
            return ""

        kwargs = {
            "modelId": self.model_id,
            "messages": turns,
            "inferenceConfig": _inference_config(max_tokens, temperature),
        }
        if system_blocks:
            kwargs["system"] = system_blocks

        try:
            client = _make_client()
            response = client.converse(**kwargs)
            content = response["output"]["message"]["content"]
            for block in content:
                if "text" in block:
                    return block["text"]
            return ""
        except Exception as e:
            print(f"[BedrockLLM] converse error: {e}")
            return ""

    # ------------------------------------------------------------------
    # Public API  (mirrors LLMWrapper exactly)
    # ------------------------------------------------------------------

    def generate(
        self,
        prompt: str,
        system_prompt: str = "You are a helpful AI assistant.",
        max_tokens: int = 1024,
    ) -> str:
        """Single-turn generation."""
        return self._converse(
            [
                {"role": "system", "content": system_prompt},
                {"role": "user",   "content": prompt},
            ],
            max_tokens=max_tokens,
        )

    def generate_with_history(
        self, messages: list[dict], max_tokens: int = 1024
    ) -> str:
        """Multi-turn generation from a full message history."""
        return self._converse(messages, max_tokens=max_tokens)

    def generate_with_history_stream(
        self, messages: list[dict], max_tokens: int = 1024
    ):
        """Stream tokens via the Bedrock converse_stream API.

        Yields text chunks as they arrive.  Falls back to emitting the full
        non-streaming response in one chunk if streaming fails.
        """
        system_blocks, turns = _split_messages(messages)
        if not turns:
            return

        kwargs = {
            "modelId": self.model_id,
            "messages": turns,
            "inferenceConfig": _inference_config(max_tokens),
        }
        if system_blocks:
            kwargs["system"] = system_blocks

        try:
            client = _make_client()
            response = client.converse_stream(**kwargs)
            for event in response["stream"]:
                if "contentBlockDelta" in event:
                    delta = event["contentBlockDelta"].get("delta", {})
                    text = delta.get("text")
                    if text:
                        yield text
                elif "messageStop" in event:
                    break
        except Exception as e:
            print(f"[BedrockLLM] converse_stream error ({e}); falling back to non-streaming.")
            result = self._converse(messages, max_tokens=max_tokens)
            if result:
                yield result

    def extract_entities(self, text: str) -> str:
        """Entity extraction — returns JSON string (or '' on failure)."""
        system_prompt = (
            "You are a helpful industrial AI assistant. Return valid JSON only."
        )
        prompt = (
            "Extract key industrial entities from the following text and "
            "format as JSON:\n\n" + text
        )
        return self.generate(prompt, system_prompt)

    def analyze_image(
        self, image_path: str, prompt: str, max_tokens: int = 256
    ) -> str:
        """Describe an image using Nova Pro's vision capability."""
        ext = os.path.splitext(image_path)[-1].lstrip(".").lower()
        fmt_map = {"jpg": "jpeg", "jpeg": "jpeg", "png": "png",
                   "gif": "gif", "webp": "webp"}
        fmt = fmt_map.get(ext, "jpeg")

        with open(image_path, "rb") as f:
            img_bytes = f.read()

        system_prompt = (
            "You are an industrial inspection assistant. You describe equipment, "
            "instruments, and plant environments precisely, transcribing visible "
            "tags, nameplates, and gauge readings exactly, and noting visible "
            "defects or safety hazards. You never invent details that are not visible."
        )
        try:
            client = _make_client()
            response = client.converse(
                modelId=self.model_id,
                system=[{"text": system_prompt}],
                messages=[{
                    "role": "user",
                    "content": [
                        {
                            "image": {
                                "format": fmt,
                                "source": {"bytes": img_bytes},
                            }
                        },
                        {"text": prompt},
                    ],
                }],
                inferenceConfig=_inference_config(max_tokens),
            )
            content = response["output"]["message"]["content"]
            for block in content:
                if "text" in block:
                    return block["text"]
            return ""
        except Exception as e:
            print(f"[BedrockLLM] vision error: {e}")
            return ""

    def unload(self):
        """No-op — no local resources are held."""
        pass
