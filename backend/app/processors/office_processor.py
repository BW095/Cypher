import traceback
from docling.document_converter import DocumentConverter
from app.ingestion.canonical_document import CanonicalDocument


# import pypandoc # For ODT fallback

class OfficeProcessor:
    def __init__(self):
        self.converter = DocumentConverter()

    def process(self, file_path: str) -> CanonicalDocument:
        print(f"Processing Office Document: {file_path}")

        # Determine file type
        file_ext = file_path.lower().split('.')[-1]

        if file_ext == "odt":
            return self._process_odt(file_path)

        try:
            # Run Docling for docx, pptx, html
            result = self.converter.convert(file_path)
            text_content = result.document.export_to_markdown()

            return CanonicalDocument(
                file_path=file_path,
                file_type="office_document",
                text=text_content,
                metadata={"processor": "docling"}
            )
        except Exception as e:
            print(f"Failed to process office doc {file_path}. Error:\n{traceback.format_exc()}")
            return CanonicalDocument(
                file_path=file_path,
                file_type="office_document",
                text=f"[Error Processing Document: {str(e)}]",
                metadata={"processor": "docling_failed"}
            )

    def _process_odt(self, file_path: str) -> CanonicalDocument:
        print("Handling ODT format...")
        try:
            # Use pypandoc to convert ODT to plain text or markdown
            # text_content = pypandoc.convert_file(file_path, 'markdown')
            text_content = "[Pypandoc Extracted ODT Text Placeholder]"

            return CanonicalDocument(
                file_path=file_path,
                file_type="office_document",
                text=text_content,
                metadata={"processor": "pypandoc"}
            )
        except Exception as e:
            return CanonicalDocument(
                file_path=file_path,
                file_type="office_document",
                text="",
                metadata={"processor": "pypandoc_failed", "error": str(e)}
            )