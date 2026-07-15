import os
import subprocess
import tempfile
import logging

logger = logging.getLogger(__name__)


class OCRWrapper:
    """OCR wrapper using Tesseract (available at /usr/bin/tesseract).

    PaddleOCR v3.7.0 has incompatible API changes that break in this environment.
    Tesseract is lightweight, reliable, and already installed system-wide.
    """

    def __init__(self, lang="eng"):
        self.lang = lang
        self._tesseract_path = self._find_tesseract()

    def _find_tesseract(self) -> str:
        """Find the tesseract binary."""
        import shutil
        path = shutil.which("tesseract")
        if path:
            return path
        # Common locations
        for p in ["/usr/bin/tesseract", "/usr/local/bin/tesseract"]:
            if os.path.isfile(p):
                return p
        return "tesseract"  # Hope it's on PATH

    def extract_text(self, image_path: str) -> str:
        """Extracts text from an image using Tesseract OCR."""
        print(f"Running Tesseract OCR on {image_path}...")

        try:
            result = subprocess.run(
                [self._tesseract_path, image_path, "stdout", "-l", self.lang],
                capture_output=True,
                text=True,
                timeout=60,
            )

            if result.returncode != 0:
                print(f"  Tesseract failed: {result.stderr[:200]}")
                return ""

            text = result.stdout.strip()
            print(f"  Tesseract extracted {len(text)} chars.")
            return text

        except FileNotFoundError:
            print("  Tesseract not found! Install with: sudo apt install tesseract-ocr")
            return ""
        except subprocess.TimeoutExpired:
            print("  Tesseract timed out after 60s.")
            return ""
        except Exception as e:
            print(f"  OCR failed for {image_path}: {e}")
            return ""

    def extract_from_pdf(self, pdf_path: str) -> str:
        """Extract text from a scanned PDF using Tesseract.

        Converts each PDF page to an image, then runs OCR on each.
        Requires pdf2image (poppler) or falls back to a simpler approach.
        """
        print(f"Running Tesseract OCR on PDF {pdf_path}...")

        try:
            from pdf2image import convert_from_path
            images = convert_from_path(pdf_path, dpi=300)
            all_text = []

            for i, img in enumerate(images):
                # Save temp image
                with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp:
                    img.save(tmp.name, "PNG")
                    page_text = self.extract_text(tmp.name)
                    all_text.append(f"--- Page {i+1} ---\n{page_text}")
                    os.unlink(tmp.name)

            return "\n\n".join(all_text)

        except ImportError:
            print("  pdf2image not installed. Trying direct tesseract on PDF...")
            # Tesseract can handle some PDFs directly via stdin
            try:
                result = subprocess.run(
                    [self._tesseract_path, pdf_path, "stdout", "-l", self.lang],
                    capture_output=True, text=True, timeout=120,
                )
                return result.stdout.strip()
            except Exception as e:
                print(f"  PDF OCR failed: {e}")
                return ""
        except Exception as e:
            print(f"  PDF OCR failed: {e}")
            return ""