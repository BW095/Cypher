import gc
import whisper


class WhisperWrapper:
    def __init__(self, model_size="base"):
        self.model_size = model_size

    def transcribe(self, audio_path: str) -> str:
        """Dynamically loads Whisper, transcribes, and clears memory."""
        print(f"Loading Whisper ({self.model_size}) for {audio_path}...")

        # Load model into memory (CPU only on cloud deployment)
        model = whisper.load_model(self.model_size, device="cpu")

        try:
            result = model.transcribe(audio_path)
            return result["text"].strip()
        except Exception as e:
            print(f"Audio transcription failed for {audio_path}: {e}")
            return ""
        finally:
            del model
            gc.collect()