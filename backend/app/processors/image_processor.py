from app.ingestion.canonical_document import CanonicalDocument
from app.ai.ocr import OCRWrapper
from app.ai.vision_model import QwenVLWrapper


# Minimum OCR text length to consider the image as "text-based" (e.g., form, manual scan)
_OCR_SUFFICIENT_THRESHOLD = 30


class ImageProcessor:
    def __init__(self):
        self.ocr = OCRWrapper()
        self.vision = QwenVLWrapper()

    def process(self, file_path: str) -> CanonicalDocument:
        print(f"Processing Image: {file_path}")

        # 1. Try OCR first — cheapest option, no GPU model loading needed
        ocr_text = self.ocr.extract_text(file_path)

        # 2. If OCR found substantial text, it's a document/form/screenshot
        #    → skip the expensive Vision model (~30s GPU time saved)
        if len(ocr_text.strip()) >= _OCR_SUFFICIENT_THRESHOLD:
            print(f"  OCR extracted {len(ocr_text.strip())} chars — sufficient, skipping Vision model.")
            return CanonicalDocument(
                file_path=file_path,
                file_type="image",
                text=f"--- OCR Text ---\n{ocr_text}",
                metadata={"processor": "paddleocr"}
            )

        # 3. OCR found little/nothing — it's a photo (equipment, site, etc.)
        #    → use Vision model for visual understanding
        print(f"  OCR extracted only {len(ocr_text.strip())} chars — invoking Vision model...")
        prompt = "Describe this industrial image in detail. Focus on equipment, conditions, and potential faults."
        vision_desc = self.vision.analyze_image(file_path, prompt)

        # Combine whatever OCR found (if any) with the vision description
        parts = []
        if ocr_text.strip():
            parts.append(f"--- OCR Text ---\n{ocr_text}")
        if vision_desc.strip():
            parts.append(f"--- Visual Description ---\n{vision_desc}")

        combined = "\n\n".join(parts) if parts else "[No text or visual content extracted]"

        return CanonicalDocument(
            file_path=file_path,
            file_type="image",
            text=combined,
            metadata={"processor": "paddleocr_and_qwenvl" if vision_desc else "paddleocr"}
        )