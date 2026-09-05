"""
Audio model stub — cloud deployment.

Whisper requires PyTorch which is not installed. Audio files return
an empty transcript and a note. For audio ingestion in production,
use Amazon Transcribe via boto3.
"""


class WhisperWrapper:
    def __init__(self, *args, **kwargs):
        print("[AudioModel] Whisper not available in cloud build — audio files skipped.")

    def transcribe(self, file_path: str) -> str:
        return (
            "[Audio transcription not available in cloud deployment. "
            "Integrate Amazon Transcribe for production audio support.]"
        )

    def unload(self):
        pass