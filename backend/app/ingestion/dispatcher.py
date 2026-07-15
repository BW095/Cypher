import os


class Dispatcher:
    """Routes files to the correct processor based on extension.

    Processors are created lazily — only when a file of that type is first
    encountered. Heavy models (Docling, OCR, Vision, Whisper) are created
    once and shared across processors that need them.
    """

    # Map extensions to processor group names
    _EXTENSION_MAP = {
        # PDFs
        '.pdf': 'pdf',
        # Images
        '.png': 'image', '.jpg': 'image', '.jpeg': 'image',
        '.tiff': 'image', '.bmp': 'image',
        # Videos
        '.mp4': 'video', '.mkv': 'video', '.avi': 'video', '.mov': 'video',
        # Audio
        '.mp3': 'audio', '.wav': 'audio', '.m4a': 'audio', '.flac': 'audio',
        # Spreadsheets
        '.xlsx': 'excel', '.xls': 'excel', '.csv': 'excel',
        # Office Documents
        '.docx': 'office', '.doc': 'office', '.pptx': 'office',
        '.ppt': 'office', '.odt': 'office', '.html': 'office', '.txt': 'office',
    }

    def __init__(self):
        self._processors = {}       # Cache of instantiated processors
        self._shared_resources = {}  # Shared model instances (Docling, OCR, etc.)

    @property
    def processors(self):
        """Expose the extension map for the watcher's file-type filtering."""
        return self._EXTENSION_MAP

    def _get_shared(self, name: str):
        """Lazily create and cache shared model instances."""
        if name not in self._shared_resources:
            if name == 'docling':
                from docling.document_converter import DocumentConverter
                print("  [Dispatcher] Loading Docling DocumentConverter (shared)...")
                self._shared_resources[name] = DocumentConverter()
            elif name == 'ocr':
                from app.ai.ocr import OCRWrapper
                print("  [Dispatcher] Loading OCR wrapper (shared)...")
                self._shared_resources[name] = OCRWrapper()
            elif name == 'vision':
                from app.ai.vision_model import QwenVLWrapper
                print("  [Dispatcher] Loading Vision model wrapper (shared)...")
                self._shared_resources[name] = QwenVLWrapper()
            elif name == 'whisper':
                from app.ai.audio_model import WhisperWrapper
                print("  [Dispatcher] Loading Whisper wrapper (shared)...")
                self._shared_resources[name] = WhisperWrapper()
        return self._shared_resources[name]

    def _create_processor(self, group: str):
        """Create a processor for the given group, injecting shared resources."""
        if group == 'pdf':
            from app.processors.pdf_processor import PDFProcessor
            proc = PDFProcessor.__new__(PDFProcessor)
            proc.converter = self._get_shared('docling')
            proc.fallback_ocr = self._get_shared('ocr')
            return proc

        elif group == 'image':
            from app.processors.image_processor import ImageProcessor
            proc = ImageProcessor.__new__(ImageProcessor)
            proc.ocr = self._get_shared('ocr')
            proc.vision = self._get_shared('vision')
            return proc

        elif group == 'video':
            from app.processors.video_processor import VideoProcessor
            proc = VideoProcessor.__new__(VideoProcessor)
            proc.whisper = self._get_shared('whisper')
            proc.vision = self._get_shared('vision')
            proc.temp_dir = "./data/temp"
            os.makedirs(proc.temp_dir, exist_ok=True)
            return proc

        elif group == 'audio':
            from app.processors.audio_processor import AudioProcessor
            proc = AudioProcessor.__new__(AudioProcessor)
            proc.whisper = self._get_shared('whisper')
            return proc

        elif group == 'excel':
            from app.processors.excel_processor import ExcelProcessor
            return ExcelProcessor()

        elif group == 'office':
            from app.processors.office_processor import OfficeProcessor
            proc = OfficeProcessor()
            # Docling is lazy inside OfficeProcessor — only loaded for .docx/.pptx,
            # not for .txt or .html. If a PDF already loaded Docling, share it.
            if 'docling' in self._shared_resources:
                proc.converter = self._shared_resources['docling']
            return proc

        raise ValueError(f"Unknown processor group: {group}")

    def get_processor(self, file_path: str):
        _, ext = os.path.splitext(file_path)
        ext_lower = ext.lower()

        group = self._EXTENSION_MAP.get(ext_lower)
        if not group:
            raise ValueError(f"No processor configured for file type: {ext}")

        # Lazy create — only on first use of this file type group
        if group not in self._processors:
            print(f"  [Dispatcher] First {group} file — creating {group} processor...")
            self._processors[group] = self._create_processor(group)

        return self._processors[group]