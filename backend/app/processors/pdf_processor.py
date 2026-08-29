import traceback
from docling.document_converter import DocumentConverter
from app.ingestion.canonical_document import CanonicalDocument


from app.ai.ocr import OCRWrapper # We will build this wrapper later

class PDFProcessor:
    def __init__(self):
        # Initialize the IBM Docling converter
        self.converter = DocumentConverter()
        self.fallback_ocr = OCRWrapper()

    def process(self, file_path: str) -> CanonicalDocument:
        print(f"Processing PDF with Docling: {file_path}")

        try:
            # 1. Run Docling conversion
            result = self.converter.convert(file_path)

            # 2. Extract standard elements
            text_content = result.document.export_to_markdown()
            doc_data = result.document.export_to_dict()

            tables = self._extract_tables(doc_data)
            images = self._extract_images(doc_data)

            # 3. Check if Docling extracted meaningful text.
            #    Scanned PDFs may "succeed" but return empty/minimal text.
            stripped = text_content.strip() if text_content else ""
            if len(stripped) < 50:
                print(f"  Docling extracted only {len(stripped)} chars — likely a scanned PDF.")
                print("  Falling back to PaddleOCR...")
                return self._fallback_process(file_path)

            return CanonicalDocument(
                file_path=file_path,
                file_type="pdf",
                text=text_content,
                tables=tables,
                images=images,
                metadata={"processor": "docling"}
            )

        except Exception as e:
            print(f"Docling failed for {file_path}. Error:\n{traceback.format_exc()}")
            print("Falling back to PaddleOCR...")
            return self._fallback_process(file_path)

    def _extract_tables(self, doc_data: dict) -> list:
        # Placeholder: Parse Docling's dictionary structure for tables
        return []

    def _extract_images(self, doc_data: dict) -> list:
        # Placeholder: Parse Docling's dictionary structure for images
        return []

    def _fallback_process(self, file_path: str) -> CanonicalDocument:
        # 1. Use PaddleOCR wrapper to brute-force read the PDF pages
        ocr_text = self.fallback_ocr.extract_from_pdf(file_path)

        return CanonicalDocument(
            file_path=file_path,
            file_type="pdf",
            text=ocr_text,
            metadata={"processor": "paddleocr_fallback"}
        )