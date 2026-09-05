"""
PDF Processor — cloud deployment (no Docling/PaddleOCR).

Uses pypdfium2 for text extraction. For scanned/image-only PDFs,
falls back to Bedrock Vision via OCRWrapper.
"""

import traceback
import pypdfium2 as pdfium

from app.ingestion.canonical_document import CanonicalDocument
from app.ai.ocr import OCRWrapper


class PDFProcessor:
    def __init__(self):
        self.fallback_ocr = OCRWrapper()

    def process(self, file_path: str) -> CanonicalDocument:
        print(f"Processing PDF with pypdfium2: {file_path}")
        try:
            text_pages = []
            pdf = pdfium.PdfDocument(file_path)
            for page in pdf:
                textpage = page.get_textpage()
                text_pages.append(textpage.get_text_range())
                textpage.close()
                page.close()
            pdf.close()

            text_content = "\n\n".join(text_pages).strip()

            # If barely any text, it's a scanned PDF — use vision OCR
            if len(text_content) < 50:
                print(f"  pypdfium2 extracted {len(text_content)} chars — trying vision OCR...")
                return self._fallback_process(file_path)

            return CanonicalDocument(
                file_path=file_path,
                file_type="pdf",
                text=text_content,
                tables=[],
                images=[],
                metadata={"processor": "pypdfium2", "pages": len(text_pages)},
            )

        except Exception:
            print(f"pypdfium2 failed for {file_path}:\n{traceback.format_exc()}")
            return self._fallback_process(file_path)

    def _fallback_process(self, file_path: str) -> CanonicalDocument:
        """Use Bedrock vision to OCR each page."""
        ocr_text = ""
        try:
            ocr_text = self.fallback_ocr.extract_from_pdf(file_path)
        except Exception as e:
            print(f"  Vision OCR also failed: {e}")

        return CanonicalDocument(
            file_path=file_path,
            file_type="pdf",
            text=ocr_text or "[PDF could not be read]",
            metadata={"processor": "vision_ocr_fallback"},
        )