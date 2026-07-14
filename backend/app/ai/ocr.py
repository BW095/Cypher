import gc
import torch
from paddleocr import PaddleOCR
import logging

# Suppress noisy PaddleOCR debug logs
logging.getLogger("ppocr").setLevel(logging.WARNING)


class OCRWrapper:
    def __init__(self, lang="en"):
        self.lang = lang

    def extract_text(self, image_path: str) -> str:
        """Extracts text from an image using PaddleOCR, then clears VRAM."""
        print(f"Loading PaddleOCR for {image_path}...")

        # 1. Load Model
        ocr_model = PaddleOCR(use_angle_cls=True, lang=self.lang)

        try:
            # 2. Process Image
            result = ocr_model.ocr(image_path, cls=True)

            extracted_text = []
            if result and result[0]:
                for line in result[0]:
                    text = line[1][0]
                    extracted_text.append(text)

            return "\n".join(extracted_text)
        except Exception as e:
            print(f"OCR failed for {image_path}: {e}")
            return ""
        finally:
            # 3. Flush Memory
            del ocr_model
            if torch.cuda.is_available():
                torch.cuda.empty_cache()
            gc.collect()

    def extract_from_pdf(self, pdf_path: str) -> str:
        """PaddleOCR can natively handle PDFs by parsing them page by page."""
        return self.extract_text(pdf_path)