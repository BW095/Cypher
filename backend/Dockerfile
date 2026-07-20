# Cypher backend — FastAPI + local GGUF LLM (llama.cpp, CUDA) + embeddings/OCR.
#
# The GPU is used ONLY by llama.cpp; torch, sentence-transformers and PaddleOCR
# run on CPU (as the app already does), so we install CPU torch and build the
# llama fork with CUDA. Requires nvidia-container-toolkit on the host at runtime.
#
# Build context is the repo root:  docker build -f backend/Dockerfile .
FROM nvidia/cuda:12.6.3-devel-ubuntu24.04

ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    HF_HUB_DISABLE_TELEMETRY=1

# System libraries: Python 3.12, a C/CUDA build toolchain (to compile the llama
# fork), and the shared libs Pillow / OpenCV / PaddleOCR / Docling / poppler
# (PDF) / ffmpeg (audio+video) need at runtime.
RUN apt-get update && apt-get install -y --no-install-recommends \
        python3.12 python3.12-venv python3.12-dev python3-pip \
        git build-essential cmake ninja-build \
        libgl1 libglib2.0-0 libgomp1 poppler-utils ffmpeg \
        curl ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Isolated venv (sidesteps Ubuntu 24.04's externally-managed-environment rule).
RUN python3.12 -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"
RUN pip install --upgrade pip setuptools wheel

WORKDIR /app

# 1) CPU-only torch — the app never runs torch on the GPU.
RUN pip install torch==2.13.0 torchvision==0.28.0 \
        --index-url https://download.pytorch.org/whl/cpu

# 2) Python dependencies (pinned from the working env).
COPY backend/requirements.txt ./requirements.txt
RUN pip install -r requirements.txt

# 3) llama-cpp-python — the JamePeng fork (Qwen3VL vision handler), built with
#    CUDA. CMAKE arch 89 = Ada (RTX 40-series); change for a different GPU
#    (e.g. 86 for Ampere/RTX 30, 75 for Turing/T4), or drop it to build for all.
ENV CMAKE_ARGS="-DGGML_CUDA=on -DCMAKE_CUDA_ARCHITECTURES=89"
RUN pip install "llama-cpp-python @ git+https://github.com/JamePeng/llama-cpp-python.git@1762647fe473a8cfc25447b53b32316f2ca3c391"

# 4) Application code (models & data are mounted at runtime, not baked in).
COPY backend/ ./backend/

WORKDIR /app/backend
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
