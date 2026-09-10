"""
Vision model interface — Bedrock Mantle (OpenAI-compatible API).

Uses the OpenAI SDK's vision capabilities with base64-encoded images.
Falls back gracefully if the model doesn't support images.

Same analyze_image(path, prompt) interface as before.
"""

import base64
import mimetypes

from openai import OpenAI

from app.config import BedrockConfig


class QwenVLWrapper:
    """Mantle vision wrapper.

    Named QwenVLWrapper for backward compatibility — the rest of the
    codebase imports this name.
    """

    def __init__(self, model_path=None, clip_path=None):
        # model_path / clip_path kept for API compat; ignored
        self.model_id = BedrockConfig.CHAT_MODEL_ID
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

    def analyze_image(self, image_path: str, prompt: str,
                      max_tokens: int = 512) -> str:
        """Describe an image using Mantle vision. Returns '' on failure."""
        print(f"Analyzing image with Mantle Vision ({self.model_id}): {image_path}")
        try:
            with open(image_path, "rb") as f:
                image_bytes = f.read()

            # Detect MIME type
            mime_type, _ = mimetypes.guess_type(image_path)
            if not mime_type or not mime_type.startswith("image/"):
                mime_type = "image/jpeg"

            b64_image = base64.b64encode(image_bytes).decode("utf-8")
            data_url = f"data:{mime_type};base64,{b64_image}"

            system_prompt = (
                "You are an industrial inspection assistant. You describe "
                "equipment, instruments, and plant environments precisely, "
                "transcribing visible tags, nameplates, and gauge readings "
                "exactly, and noting visible defects or safety hazards. "
                "You never invent details that are not visible."
            )

            response = self.client.chat.completions.create(
                model=self.model_id,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "image_url",
                                "image_url": {"url": data_url},
                            },
                            {"type": "text", "text": prompt},
                        ],
                    },
                ],
                max_tokens=max_tokens,
                temperature=0.1,
            )

            return response.choices[0].message.content or ""

        except Exception as e:
            print(f"[Mantle Vision] Error analyzing {image_path}: {e}")
            return ""
