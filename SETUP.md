# Cypher — Complete Setup Guide

Everything you need after a fresh `git clone`.

---

## 1. Prerequisites (install once on the host)

| What | Why | How |
|---|---|---|
| **Docker Engine + Compose v2** | Runs Qdrant, Neo4j, backend, frontend | [docs.docker.com](https://docs.docker.com/engine/install/) |
| **NVIDIA driver** (470+) | GPU inference via llama.cpp | `nvidia-smi` to verify |
| **nvidia-container-toolkit** | Passes GPU into Docker container | [docs.nvidia.com/datacenter/cloud-native](https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/install-guide.html) |

> **No GPU?** The backend falls back to CPU. Set `n_gpu_layers=0` in config or just let it run — it will be slower but functional.

---

## 2. GGUF models — download before first run

Place all three files in `./models/` (they are **not** bundled in the image).

| File | Size | Purpose | Download |
|---|---|---|---|
| `Qwen3VL-8B-Instruct-Q4_K_M.gguf` | ~4.7 GB | Chat + vision (main LLM) | [Hugging Face](https://huggingface.co/Qwen/Qwen3-VL-8B-Instruct-GGUF) |
| `mmproj-Qwen3VL-8B-Instruct-Q8_0.gguf` | ~717 MB | Vision projector (required for image/PDF docs) | Same repo as above |
| `Qwen2.5-3B-Instruct-Q4_K_M.gguf` | ~1.8 GB | Fast entity extraction (smaller, cheaper) | [Hugging Face](https://huggingface.co/Qwen/Qwen2.5-3B-Instruct-GGUF) |

Quick download with `huggingface-cli`:
```bash
pip install huggingface_hub
huggingface-cli download Qwen/Qwen3-VL-8B-Instruct-GGUF \
    Qwen3VL-8B-Instruct-Q4_K_M.gguf \
    mmproj-Qwen3VL-8B-Instruct-Q8_0.gguf \
    --local-dir ./models

huggingface-cli download Qwen/Qwen2.5-3B-Instruct-GGUF \
    Qwen2.5-3B-Instruct-Q4_K_M.gguf \
    --local-dir ./models
```

---

## 3. HuggingFace models — auto-downloaded at first startup

These are **downloaded automatically** by the backend when it first runs and cached in the `hf_cache` Docker volume. You do **not** need to download them manually.

| Model | Size | Purpose |
|---|---|---|
| `BAAI/bge-m3` | ~570 MB | Dense embeddings (Qdrant) |
| `cross-encoder/ms-marco-MiniLM-L-6-v2` | ~80 MB | Reranker |
| Docling layout models | ~200 MB | PDF/Office layout parsing |

> If your server has no internet access, download these ahead of time and set `HF_HOME` to a local path in `docker-compose.yml`.

---

## 4. Environment file

```bash
cp .env.example .env
```

Edit `.env`:

```env
NEO4J_PASSWORD=change-me-to-a-strong-password   # ← change this
WEB_PORT=8080                                     # UI port
DOCUMENTS_DIR=./documents                         # host folder to ingest from
```

---

## 5. Build & start (Docker — recommended)

```bash
docker compose build      # first build compiles llama.cpp with CUDA (~5 min)
docker compose up -d
```

Open **http://localhost:8080**

---

## 6. Local dev (no Docker)

Only needed if you want to edit and hot-reload without rebuilding Docker images.

### Backend
```bash
cd backend
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# Start Qdrant and Neo4j separately (easiest via Docker):
docker run -d -p 6333:6333 qdrant/qdrant
docker run -d -p 7687:7687 -p 7474:7474 \
    -e NEO4J_AUTH=neo4j/password \
    -e NEO4J_PLUGINS='["apoc"]' \
    neo4j:5

# Set env vars (or create a .env in backend/):
export QDRANT_HOST=localhost
export NEO4J_URI=neo4j://localhost:7687
export NEO4J_USER=neo4j
export NEO4J_PASSWORD=password
export QWEN_MODEL_PATH=../models/Qwen3VL-8B-Instruct-Q4_K_M.gguf
export CLIP_PROJECTOR_PATH=../models/mmproj-Qwen3VL-8B-Instruct-Q8_0.gguf
export EXTRACTION_MODEL_PATH=../models/Qwen2.5-3B-Instruct-Q4_K_M.gguf

uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

### Frontend
```bash
cd ui
npm install
npm run dev        # Vite dev server at http://localhost:5173
```

The Vite proxy (`vite.config.js`) forwards `/api/*` → `http://localhost:8000` automatically.

---

## 7. GPU tuning

| GPU VRAM | Recommended setting |
|---|---|
| < 8 GB | Set `N_GPU_LAYERS=20` in compose env (partial offload) |
| 8–12 GB | Default (full 8B offload, 3B swaps in/out) |
| 16 GB+ | Both models resident; can use larger quantizations |

The backend image is compiled for **CUDA arch 89** (RTX 40-series / Ada).  
For other GPUs, edit `CMAKE_CUDA_ARCHITECTURES` in `backend/Dockerfile`:
- RTX 30-series (Ampere) → `86`
- T4 / RTX 20-series (Turing) → `75`
- A100 → `80`

---

## 8. What lives where

```
Cypher/
├── models/              ← GGUF models (you download these)
├── documents/           ← Your documents to ingest (mounted into container)
├── backend/
│   ├── requirements.txt ← pip dependencies
│   ├── app/             ← FastAPI source
│   └── data/            ← SQLite DB + uploads (inside container at /data)
├── ui/
│   ├── package.json     ← npm dependencies
│   └── src/             ← React source
├── docker-compose.yml
├── .env.example         ← Copy to .env and fill in
└── DEPLOY.md            ← Production deployment notes
```

---

## 9. Summary checklist for a fresh clone

- [ ] Install Docker + nvidia-container-toolkit
- [ ] Download 3 GGUF models into `./models/`
- [ ] `cp .env.example .env` and set `NEO4J_PASSWORD`
- [ ] `docker compose build && docker compose up -d`
- [ ] Open http://localhost:8080
- [ ] In the UI → Knowledge Base → add a folder to watch (e.g. `/documents`)
- [ ] Drop documents into `./documents/` on the host and watch them ingest
