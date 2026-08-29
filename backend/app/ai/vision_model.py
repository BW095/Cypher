"""
Vision model interface — Amazon Bedrock (Claude 3.5 Haiku with vision).

Replaces the local Qwen3VL + CLIP projector with Bedrock Claude's
multimodal API. Same analyze_image(path, prompt) interface.
"""

import base64
import json
import mimetypes

import boto3

from app.config import BedrockConfig


class QwenVLWrapper:
    """Bedrock vision wrapper.

    Named QwenVLWrapper for backward compatibility — the rest of the
    codebase imports this name.
    """

    def __init__(self, model_path=None, clip_path=None):
        # model_path / clip_path kept for API compat; ignored
        self.model_id = BedrockConfig.CHAT_MODEL_ID  # Claude Haiku supports vision
        self._client = None

    @property
    def client(self):
        if self._client is None:
            self._client = boto3.client(
                "bedrock-runtime",
                region_name=BedrockConfig.REGION,
            )
        return self._client

    def analyze_image(self, image_path: str, prompt: str,
                      max_tokens: int = 512) -> str:
        """Describe an image using Claude's vision capability. Returns '' on failure."""
        print(f"Analyzing image with Bedrock Vision: {image_path}")
        try:
            with open(image_path, "rb") as f:
                image_bytes = f.read()

            # Detect MIME type
            mime_type, _ = mimetypes.guess_type(image_path)
            if not mime_type or not mime_type.startswith("image/"):
                mime_type = "image/jpeg"
            # Claude accepts: image/jpeg, image/png, image/gif, image/webp
            media_type = mime_type if mime_type in (
                "image/jpeg", "image/png", "image/gif", "image/webp"
            ) else "image/jpeg"

            encoded = base64.b64encode(image_bytes).decode("utf-8")

            system_prompt = (
                "You are an industrial inspection assistant. You describe "
                "equipment, instruments, and plant environments precisely, "
                "transcribing visible tags, nameplates, and gauge readings "
                "exactly, and noting visible defects or safety hazards. "
                "You never invent details that are not visible."
            )

            body = {
                "anthropic_version": "bedrock-2023-05-31",
                "max_tokens": max_tokens,
                "temperature": 0.1,
                "system": system_prompt,
                "messages": [
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "image",
                                "source": {
                                    "type": "base64",
                                    "media_type": media_type,
                                    "data": encoded,
                                },
                            },
                            {
                                "type": "text",
                                "text": prompt,
                            },
                        ],
                    }
                ],
            }

            response = self.client.invoke_model(
                modelId=self.model_id,
                contentType="application/json",
                accept="application/json",
                body=json.dumps(body),
            )
            result = json.loads(response["body"].read())

            # Extract text from response
            content = result.get("content", [])
            parts = []
            for block in content:
                if block.get("type") == "text":
                    parts.append(block.get("text", ""))
            return "\n".join(parts).strip()

        except Exception as e:
            print(f"[Bedrock Vision] Error analyzing {image_path}: {e}")
            return ""
