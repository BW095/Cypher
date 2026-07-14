from app.ingestion.canonical_document import CanonicalDocument
from app.ai.audio_model import WhisperWrapper

class AudioProcessor:
    def __init__(self):
        self.whisper = WhisperWrapper()

    def process(self, file_path: str) -> CanonicalDocument:
        print(f"Processing Audio: {file_path}")

        # 1. Run Whisper to transcribe the audio file
        transcript = self.whisper.transcribe(file_path)

        return CanonicalDocument(
            file_path=file_path,
            file_type="audio",
            text=transcript,
            metadata={"processor": "whisper"}
        )