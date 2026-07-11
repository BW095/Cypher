import os
from app.processors.pdf_processor import PDFProcessor
from app.processors.image_processor import ImageProcessor
from app.processors.video_processor import VideoProcessor
from app.processors.audio_processor import AudioProcessor
from app.processors.excel_processor import ExcelProcessor
from app.processors.office_processor import OfficeProcessor

class Dispatcher:
    def __init__(self):
        self.pdf_processor = PDFProcessor()
        self.image_processor = ImageProcessor()
        self.video_processor = VideoProcessor()
        self.audio_processor = AudioProcessor()
        self.excel_processor = ExcelProcessor()
        self.office_processor = OfficeProcessor()
        self.processors = {
            # PDFs
            '.pdf': self.pdf_processor,

            # Images
            '.png': self.image_processor,
            '.jpg': self.image_processor,
            '.jpeg': self.image_processor,
            '.tiff': self.image_processor,
            '.bmp': self.image_processor,

            # Videos
            '.mp4': self.video_processor,
            '.mkv': self.video_processor,
            '.avi': self.video_processor,
            '.mov': self.video_processor,

            # Audio
            '.mp3': self.audio_processor,
            '.wav': self.audio_processor,
            '.m4a': self.audio_processor,
            '.flac': self.audio_processor,

            # Spreadsheets
            '.xlsx': self.excel_processor,
            '.xls': self.excel_processor,
            '.csv': self.excel_processor,

            # Office Documents
            '.docx': self.office_processor,
            '.doc': self.office_processor,
            '.pptx': self.office_processor,
            '.ppt': self.office_processor,
            '.odt': self.office_processor,
            '.html': self.office_processor,
            '.txt': self.office_processor
        }

    def get_processor(self, file_path: str):
        _, ext = os.path.splitext(file_path)
        processor = self.processors.get(ext.lower())

        if not processor:
            raise ValueError(f"No processor configured for file type: {ext}")

        return processor