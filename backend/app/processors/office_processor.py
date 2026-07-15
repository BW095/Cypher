import os
import traceback
from app.ingestion.canonical_document import CanonicalDocument


class OfficeProcessor:
    def __init__(self):
        self._converter = None  # Lazy-loaded only for complex formats

    @property
    def converter(self):
        """Docling is only loaded when a complex format (.docx, .pptx) needs it."""
        if self._converter is None:
            from docling.document_converter import DocumentConverter
            print("  [OfficeProcessor] Loading Docling (first complex doc)...")
            self._converter = DocumentConverter()
        return self._converter

    @converter.setter
    def converter(self, value):
        """Allow Dispatcher to inject a shared Docling instance."""
        self._converter = value

    def process(self, file_path: str) -> CanonicalDocument:
        print(f"Processing Office Document: {file_path}")

        file_ext = os.path.splitext(file_path)[1].lower()

        # Fast path: plain text files — no need for Docling's ML pipeline
        if file_ext == ".txt":
            return self._process_plaintext(file_path)

        # Fast path: HTML — simple read (Docling adds overhead for no benefit)
        if file_ext == ".html":
            return self._process_html(file_path)

        # ODT: use pypandoc
        if file_ext == ".odt":
            return self._process_odt(file_path)

        # Complex formats (.docx, .pptx, .doc, .ppt): use Docling
        try:
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

    def _process_plaintext(self, file_path: str) -> CanonicalDocument:
        """Direct file read — instant, no ML overhead."""
        print(f"  Reading plain text file directly (bypassing Docling)...")
        try:
            with open(file_path, 'r', encoding='utf-8', errors='replace') as f:
                text_content = f.read()
            return CanonicalDocument(
                file_path=file_path,
                file_type="office_document",
                text=text_content,
                metadata={"processor": "direct_read"}
            )
        except Exception as e:
            return CanonicalDocument(
                file_path=file_path,
                file_type="office_document",
                text=f"[Error reading file: {str(e)}]",
                metadata={"processor": "direct_read_failed"}
            )

    def _process_html(self, file_path: str) -> CanonicalDocument:
        """Read HTML and strip tags for text extraction."""
        print(f"  Reading HTML file directly...")
        try:
            with open(file_path, 'r', encoding='utf-8', errors='replace') as f:
                html_content = f.read()

            # Basic HTML tag stripping — good enough for industrial docs
            import re
            text_content = re.sub(r'<[^>]+>', ' ', html_content)
            text_content = re.sub(r'\s+', ' ', text_content).strip()

            return CanonicalDocument(
                file_path=file_path,
                file_type="office_document",
                text=text_content,
                metadata={"processor": "html_direct"}
            )
        except Exception as e:
            return CanonicalDocument(
                file_path=file_path,
                file_type="office_document",
                text=f"[Error reading HTML: {str(e)}]",
                metadata={"processor": "html_failed"}
            )

    def _process_odt(self, file_path: str) -> CanonicalDocument:
        """Convert ODT via pypandoc."""
        print("  Handling ODT format with pypandoc...")
        try:
            import pypandoc
            text_content = pypandoc.convert_file(file_path, 'markdown')

            return CanonicalDocument(
                file_path=file_path,
                file_type="office_document",
                text=text_content,
                metadata={"processor": "pypandoc"}
            )
        except ImportError:
            print("  pypandoc not installed — falling back to Docling for ODT.")
            try:
                result = self.converter.convert(file_path)
                return CanonicalDocument(
                    file_path=file_path,
                    file_type="office_document",
                    text=result.document.export_to_markdown(),
                    metadata={"processor": "docling_odt_fallback"}
                )
            except Exception as e2:
                return CanonicalDocument(
                    file_path=file_path,
                    file_type="office_document",
                    text=f"[ODT processing failed: {str(e2)}]",
                    metadata={"processor": "odt_failed"}
                )
        except Exception as e:
            return CanonicalDocument(
                file_path=file_path,
                file_type="office_document",
                text="",
                metadata={"processor": "pypandoc_failed", "error": str(e)}
            )