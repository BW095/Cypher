import os
import gc
import torch
import whisper


class WhisperWrapper:
    def __init__(self, model_size="base"):
        self.model_size = model_size

    def transcribe(self, audio_path: str) -> str:
        """Dynamically loads Whisper, transcribes, and clears VRAM."""
        print(f"Loading Whisper ({self.model_size}) for {audio_path}...")

        # 1. Load model into memory
        model = whisper.load_model(self.model_size)

        try:
            # 2. Process Audio
            result = model.transcribe(audio_path)
            return result["text"].strip()
        except Exception as e:
            print(f"Audio transcription failed for {audio_path}: {e}")
            return ""
        finally:
            # 3. Flush Memory
            del model
            if torch.cuda.is_available():
                torch.cuda.empty_cache()
            gc.collect()