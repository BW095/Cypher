from app.ingestion.canonical_document import CanonicalDocument
from app.ai.ocr import OCRWrapper
from app.ai.vision_model import QwenVLWrapper

class ImageProcessor:
    def __init__(self):
        self.ocr = OCRWrapper()
        self.vision = QwenVLWrapper()

    def process(self, file_path: str) -> CanonicalDocument:
        print(f"Processing Image: {file_path}")

        # 1. Run PaddleOCR to extract hard text from the image
        ocr_text = self.ocr.extract_text(file_path)

        # 2. Run Qwen-VL to get a visual description
        prompt = "Describe this industrial image in detail. Focus on equipment, conditions, and potential faults."
        vision_desc = self.vision.analyze_image(file_path, prompt)

        # 3. Combine text for the LLM
        combined_text = f"--- OCR Text ---\n{ocr_text}\n\n--- Visual Description ---\n{vision_desc}"

        return CanonicalDocument(
            file_path=file_path,
            file_type="image",
            text=combined_text,
            metadata={"processor": "paddleocr_and_qwenvl"}
        )