"""
Vision model interface — Amazon Bedrock (Converse API).

Uses the Converse API which works with both:
  - Amazon Nova Pro  (default, no Anthropic form needed)
  - Anthropic Claude 3.5 Haiku  (override with BEDROCK_CHAT_MODEL_ID)

Same analyze_image(path, prompt) interface as before.
"""

import base64
import mimetypes

import boto3

from app.config import BedrockConfig

# Converse-supported image formats
_SUPPORTED_FORMATS = {"jpeg", "png", "gif", "webp"}


class QwenVLWrapper:
    """Bedrock vision wrapper.

    Named QwenVLWrapper for backward compatibility — the rest of the
    codebase imports this name.
    """

    def __init__(self, model_path=None, clip_path=None):
        # model_path / clip_path kept for API compat; ignored
        self.model_id = BedrockConfig.CHAT_MODEL_ID
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
        """Describe an image using Bedrock Converse vision. Returns '' on failure."""
        print(f"Analyzing image with Bedrock Vision ({self.model_id}): {image_path}")
        try:
            with open(image_path, "rb") as f:
                image_bytes = f.read()

            # Detect image format
            mime_type, _ = mimetypes.guess_type(image_path)
            ext = (mime_type or "image/jpeg").split("/")[-1].lower()
            if ext not in _SUPPORTED_FORMATS:
                ext = "jpeg"

            system_prompt = (
                "You are an industrial inspection assistant. You describe "
                "equipment, instruments, and plant environments precisely, "
                "transcribing visible tags, nameplates, and gauge readings "
                "exactly, and noting visible defects or safety hazards. "
                "You never invent details that are not visible."
            )

            response = self.client.converse(
                modelId=self.model_id,
                system=[{"text": system_prompt}],
                messages=[
                    {
                        "role": "user",
                        "content": [
                            {
                                "image": {
                                    "format": ext,
                                    "source": {"bytes": image_bytes},
                                }
                            },
                            {"text": prompt},
                        ],
                    }
                ],
                inferenceConfig={
                    "maxTokens": max_tokens,
                    "temperature": 0.1,
                },
            )

            # Extract text from Converse response
            content = response.get("output", {}).get("message", {}).get("content", [])
            parts = [block.get("text", "") for block in content if "text" in block]
            return "\n".join(parts).strip()

        except Exception as e:
            print(f"[Bedrock Vision] Error analyzing {image_path}: {e}")
            return ""
