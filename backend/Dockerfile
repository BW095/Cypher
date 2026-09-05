# Cypher backend — FastAPI + Amazon Bedrock (no GPU needed).
#
# Cloud deployment: all LLM/embedding inference is done via Bedrock API
# calls. No local models, no CUDA, no llama.cpp. The image is dramatically
# smaller (~2 GB vs ~10 GB for the GPU variant).
#
# Build context is the repo root:  docker build -f backend/Dockerfile .
FROM python:3.12-slim

ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

# System libraries needed at runtime:
#  - libgl1, libglib2.0-0: OpenCV / PaddleOCR
#  - poppler-utils: PDF processing (Docling)
#  - ffmpeg: audio/video processing (Whisper)
RUN apt-get update && apt-get install -y --no-install-recommends \
        libgl1 libglib2.0-0 libgomp1 poppler-utils ffmpeg \
        curl ca-certificates \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Python dependencies (no PyTorch — all inference is via Bedrock API)
RUN pip install --upgrade pip setuptools wheel
COPY backend/requirements.txt ./requirements.txt
RUN pip install -r requirements.txt

# 3) Application code (no models baked in — Bedrock is remote)
COPY backend/ ./backend/

WORKDIR /app/backend
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
