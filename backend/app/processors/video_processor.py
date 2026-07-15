import os
import ffmpeg
from app.ingestion.canonical_document import CanonicalDocument
from app.ai.audio_model import WhisperWrapper
from app.ai.vision_model import QwenVLWrapper
class VideoProcessor:
    def __init__(self):
        self.whisper = WhisperWrapper()
        self.vision = QwenVLWrapper()
        self.temp_dir = "./data/temp"
        os.makedirs(self.temp_dir, exist_ok=True)

    def process(self, file_path: str) -> CanonicalDocument:
        print(f"Processing Video: {file_path}")

        base_name = os.path.basename(file_path)
        audio_path = os.path.join(self.temp_dir, f"{base_name}.wav")
        frame_path = os.path.join(self.temp_dir, f"{base_name}_frame.jpg")

        # 1. Extract audio and key frames using FFmpeg
        self._extract_audio(file_path, audio_path)
        self._extract_key_frames(file_path, frame_path)

        # 2. Transcribe Audio
        transcript = ""
        if os.path.exists(audio_path):
            transcript = self.whisper.transcribe(audio_path)

        # 3. Analyze Frames
        frame_desc = ""
        if os.path.exists(frame_path):
            prompt = "Describe this keyframe from an industrial video. Identify equipment and actions."
            frame_desc = self.vision.analyze_image(frame_path, prompt)

        # 4. Cleanup temp files
        if os.path.exists(audio_path): os.remove(audio_path)
        if os.path.exists(frame_path): os.remove(frame_path)

        combined_text = f"--- Video Transcript ---\n{transcript}\n\n--- Visual Content ---\n{frame_desc}"

        return CanonicalDocument(
            file_path=file_path,
            file_type="video",
            text=combined_text,
            metadata={"processor": "ffmpeg_whisper_qwenvl"}
        )

    def _extract_audio(self, video_path: str, output_path: str):
        try:
            (
                ffmpeg
                .input(video_path)
                .output(output_path, acodec='pcm_s16le', ac=1, ar='16k')
                .overwrite_output()
                .run(quiet=True)
            )
        except Exception as e:
            print(f"Failed to extract audio from video: {e}")

    def _extract_key_frames(self, video_path: str, output_path: str):
        try:
            # Extracts a representative frame at the 5-second mark
            (
                ffmpeg
                .input(video_path, ss='00:00:05')
                .output(output_path, vframes=1)
                .overwrite_output()
                .run(quiet=True)
            )
        except Exception as e:
            print(f"Failed to extract keyframe from video: {e}")