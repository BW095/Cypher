# Deploying Cypher with Docker

Cypher runs as four containers — **Qdrant** (vectors), **Neo4j** (graph), the
**backend** (FastAPI + local GPU LLM), and the **frontend** (nginx-served React
that also reverse-proxies `/api` to the backend).

## Prerequisites

1. **NVIDIA GPU + driver** on the host, and the **NVIDIA Container Toolkit** so
   Docker can pass the GPU to the backend:
   ```bash
   # verify the toolkit works:
   docker run --rm --gpus all nvidia/cuda:12.6.3-base-ubuntu24.04 nvidia-smi
   ```
   The backend also runs CPU-only (llama.cpp falls back), just slowly — a GPU is
   strongly recommended.
2. **Docker Engine + Compose v2.**
3. **GGUF models** in `./models/` (not baked into the image):
   - `Qwen3VL-8B-Instruct-Q4_K_M.gguf` (chat/vision)
   - `mmproj-Qwen3VL-8B-Instruct-Q8_0.gguf` (vision projector)
   - `Qwen2.5-3B-Instruct-Q4_K_M.gguf` (fast entity extraction)

## Setup

```bash
cp .env.example .env
# edit .env: set a strong NEO4J_PASSWORD, pick WEB_PORT, and set DOCUMENTS_DIR
# to the host folder holding the documents you want ingested.

docker compose build      # first build is slow: it compiles llama.cpp with CUDA
docker compose up -d
```

Open **http://localhost:8080** (or your `WEB_PORT`).

## Ingesting documents

`DOCUMENTS_DIR` from `.env` is mounted into the backend at **`/documents`**. In
the UI's *Knowledge Base* tab, track folders using the **in-container path**,
e.g. `/documents/reports`, `/documents/logs`. (The UI runs on the server, so it
sees the container filesystem, not your laptop's.)

## What uses the GPU

Only **llama.cpp** (the chat 8B and the 3B extractor) uses the GPU. Embeddings
(BGE), reranking (cross-encoder) and OCR run on CPU by design, to keep VRAM free
for the LLM. On a 6 GB GPU the 8B and 3B swap in/out as needed; 16 GB+ can hold
both resident and run larger models.

## Notes & tuning

- **GPU architecture:** the backend image builds llama.cpp for CUDA arch **89**
  (Ada / RTX 40-series). For another GPU, edit `CMAKE_CUDA_ARCHITECTURES` in
  `backend/Dockerfile` (86 = Ampere/RTX 30, 75 = Turing/T4).
- **Config** is all env-driven (see `docker-compose.yml`): model paths, DB
  hosts, `EXTRACTION_MODEL_PATH`, `EXTRACTION_MAX_TOKENS`, `RERANK_MODEL`,
  `SPREADSHEET_SUMMARY_ROWS`, `MAX_CHUNKS_PER_DOC`, `LLM_*`, etc.
- **Persistence:** Qdrant, Neo4j, the SQLite DB and the HuggingFace model cache
  live in named volumes and survive restarts.
- **Streaming:** nginx is configured with `proxy_buffering off` so chat answers
  stream token-by-token through the proxy.

## ⚠️ Before exposing to a network

The API currently has **no authentication**. For anything beyond localhost, put
it behind your VPN or a reverse proxy with auth (and add app-level auth). Do not
publish the Neo4j/Qdrant ports; leave them internal to the compose network.
