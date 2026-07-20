<div align="center">

<img src="https://readme-typing-svg.demolab.com?font=Fira+Code&weight=700&size=40&pause=1000&color=E8A33D&center=true&vCenter=true&repeat=false&width=700&lines=⬡+CYPHER" alt="CYPHER" />

<h3>Industrial AI Knowledge Brain</h3>

<p><em>Transform fragmented industrial documents into a living, queryable knowledge graph — fully local, fully private.</em></p>

<p>
  <img src="https://img.shields.io/badge/Python-3.11+-3776AB?style=for-the-badge&logo=python&logoColor=white" />
  <img src="https://img.shields.io/badge/FastAPI-0.111-009688?style=for-the-badge&logo=fastapi&logoColor=white" />
  <img src="https://img.shields.io/badge/React-18-61DAFB?style=for-the-badge&logo=react&logoColor=black" />
  <img src="https://img.shields.io/badge/Neo4j-Graph_DB-008CC1?style=for-the-badge&logo=neo4j&logoColor=white" />
  <img src="https://img.shields.io/badge/Qdrant-Vector_DB-FF4081?style=for-the-badge" />
  <img src="https://img.shields.io/badge/LLM-100%25_Local-E8A33D?style=for-the-badge&logo=llama&logoColor=black" />
</p>

<p>
  <a href="#-features">Features</a> •
  <a href="#-architecture">Architecture</a> •
  <a href="#-tech-stack">Tech Stack</a> •
  <a href="#-quick-start">Quick Start</a> •
  <a href="#%EF%B8%8F-configuration">Configuration</a> •
  <a href="#-screenshots">Screenshots</a>
</p>

---

</div>

## 🚨 The Problem

Industrial companies sit on **mountains of institutional knowledge** locked inside:

| Format | Problem |
|---|---|
| PDF Manuals & P&IDs | Searched by keyword only — no semantic understanding |
| Maintenance Work Orders | Siloed by equipment, not linked across systems |
| Compliance Documents | Manually checked against procedures — error-prone |
| Inspection Records | No automated root-cause correlation |
| Expert Knowledge | Lives in people's heads; **lost when they retire** |

> *A field engineer needing to diagnose a pump failure might spend hours searching 50 documents — or ask a colleague who might not be available.*

**Cypher solves this.** It ingests every document type, extracts entities and relationships into a knowledge graph, and lets your team ask questions in plain English — getting precise, cited answers in seconds.

---

## ✨ Features

### 🔄 Universal Document Ingestion
Drop **any** file type into a watched folder. Cypher handles it automatically:

| File Type | Processor | What It Extracts |
|---|---|---|
| `.pdf` | PyMuPDF | Full text, embedded images |
| `.docx` / `.xlsx` | python-docx / openpyxl | Text, tables, sheet data |
| `.png` / `.jpg` / P&ID diagrams | **Qwen3-VL-8B Vision Model** | Diagram descriptions, labels |
| `.eml` | Custom email parser | Sender, body, attachments |
| `.mp3` / `.wav` | Whisper transcription | Full speech-to-text |
| `.mp4` / video | Frame extraction + VLM | Visual scene descriptions |

Content-hash change detection ensures files are never re-embedded unnecessarily.

---

### 🧠 Knowledge Graph Construction

Every ingested document is analyzed by a local **Qwen3-8B-Instruct** model using an overlapping window strategy to extract structured knowledge:

**10 Entity Types:**
`EQUIPMENT` · `COMPONENT` · `PROCESS_PARAMETER` · `FAILURE` · `PROCEDURE` · `REGULATION` · `PERSONNEL` · `MATERIAL` · `LOCATION` · `DATE`

**9 Relationship Types:**
`PART_OF` · `HAS_FAILURE` · `REQUIRES` · `MEASURES` · `GOVERNED_BY` · `RESPONSIBLE_FOR` · `LOCATED_IN` · `OCCURRED_ON` · `RELATES_TO`

**Cross-document entity resolution** — `"Pump P-101"`, `"pump p101"`, `"PUMP P 101"` all canonicalize to the same graph node, building a unified knowledge mesh across all your documents.

```
(Document: Maintenance_Report.pdf)
        │
        └─[:MENTIONS]──► (Equipment: Pump P-101)
                                 │
                    ┌────────────┼────────────────┐
                    │            │                │
           [:HAS_FAILURE]  [:HAS_PARAMETER]  [:GOVERNED_BY]
                    │            │                │
             (Failure:     (ProcessParam:   (Regulation:
            Bearing Wear)   3000 RPM)        OISD-116)
```

---

### 💬 Expert Knowledge Copilot (RAG)

Ask any question in natural language. Cypher runs a **parallel dual-retrieval** pipeline:

```
User Query
    │
    ├──► Vector Retriever (Qdrant)          ← semantic similarity
    │        BGE-base-en-v1.5, 768-dim
    │        Fetches top-15 chunks
    │
    └──► Graph Retriever (Neo4j)            ← structural relationships
             Entity name matching
             2-hop neighborhood traversal
             │
             └──► Cross-Encoder Reranker   ← ranks ALL candidates
                      Drops low-confidence
                      Keeps top-5
                          │
                          └──► Context Builder (6000-char budget)
                                    │
                                    └──► Qwen3-8B-Instruct (local)
                                             Mandatory inline citations
                                             Sources: section
                                             Confidence: High/Medium/Low
```

Every answer includes:
- **Inline citations** — `The pump showed vibration [pump_maintenance_log.pdf]`
- **Sources panel** — visually distinguishes *cited* vs *retrieved* documents
- **Confidence score** — computed from retrieval strength + citation presence + graph corroboration

---

### 🛡️ Compliance Gap Detection

Automatically audit your regulatory coverage — no manual checking required.

```python
for regulation in graph.all_regulations():
    neighbors = graph.traverse(regulation, depth=1)
    
    if not neighbors.procedures and not neighbors.documents:
        status = "GAP"      # 🚨 Nothing references this regulation
    elif not neighbors.procedures or not neighbors.documents:
        status = "PARTIAL"  # ⚠️ Incomplete coverage
    else:
        status = "COVERED"  # ✅ Fully evidenced
```

An optional **LLM audit pass** generates a written narrative identifying operational/safety risks and concrete remediation steps.

---

### 🕸️ Interactive Graph Explorer

Browse the knowledge graph visually:
- **Force-directed graph** with entity-type color coding
- **Semantic search** — type any term to fly to that subgraph
- **Depth control** — expand from 1 to 4 hops
- **Source document tracing** — see which files mention each entity

---

## 🏗️ Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                          REACT UI (Vite)                        │
│  ChatView │ KnowledgeView │ GraphView │ ComplianceView          │
└─────────────────────────┬───────────────────────────────────────┘
                           │  REST + Streaming
┌─────────────────────────▼───────────────────────────────────────┐
│                     FastAPI Backend                             │
│  /api/chat  │  /api/ingest  │  /api/graph  │  /api/compliance   │
│                                                                  │
│  ┌─────────────────────┐    ┌──────────────────────────────┐    │
│  │  Ingestion Pipeline │    │      Query Engine            │    │
│  │  ┌───────────────┐  │    │  ┌────────────┐              │    │
│  │  │ File Watcher  │  │    │  │   Vector   │              │    │
│  │  │  (SQLite)     │  │    │  │ Retriever  │◄─── Qdrant  │    │
│  │  └──────┬────────┘  │    │  └────────────┘              │    │
│  │         │           │    │  ┌────────────┐              │    │
│  │  ┌──────▼────────┐  │    │  │   Graph    │◄─── Neo4j   │    │
│  │  │  Dispatcher   │  │    │  │ Retriever  │              │    │
│  │  │  (8 parsers)  │  │    │  └────────────┘              │    │
│  │  └──────┬────────┘  │    │  ┌────────────┐              │    │
│  │         │           │    │  │ Reranker   │              │    │
│  │  ┌──────▼────────┐  │    │  └────────────┘              │    │
│  │  │Entity Extract │  │    │  ┌────────────┐              │    │
│  │  │  (Qwen3-8B)   │  │    │  │    LLM     │◄── Qwen3-8B │    │
│  │  └──────┬────────┘  │    │  └────────────┘              │    │
│  │         │           │    └──────────────────────────────┘    │
│  │  ┌──────▼────────┐  │                                        │
│  │  │  Qdrant Store │  │    ┌──────────────────────────────┐    │
│  │  │  Neo4j Store  │  │    │   Compliance Analyzer        │    │
│  │  │  SQLite Track │  │    │   (Graph-driven, + LLM audit)│    │
│  │  └───────────────┘  │    └──────────────────────────────┘    │
│  └─────────────────────┘                                        │
└─────────────────────────────────────────────────────────────────┘
```

---

## 🔒 Privacy First — 100% Local

Cypher runs **entirely on your infrastructure**. No data ever leaves your network.

| Component | Technology | Why Local? |
|---|---|---|
| LLM (text + vision) | Qwen3-8B-Instruct GGUF via **llama.cpp** | VRAM-aware GPU offload |
| Embeddings | BAAI/bge-base-en-v1.5 (768-dim) | Runs on CPU or GPU |
| Vector DB | **Qdrant** (self-hosted) | Your vectors stay yours |
| Graph DB | **Neo4j** (self-hosted) | Your entity graph stays yours |
| Metadata | **SQLite** (local file) | Zero external dependency |

---

## 🛠️ Tech Stack

<table>
<tr>
<td><strong>Backend</strong></td>
<td>

| Layer | Technology |
|---|---|
| API Framework | FastAPI (async, streaming) |
| LLM Runtime | llama-cpp-python |
| Model | Qwen3-VL-8B-Instruct (Q4_K_M GGUF) |
| Embeddings | BAAI/bge-base-en-v1.5 |
| Vector Store | Qdrant |
| Graph Store | Neo4j |
| Metadata | SQLite |
| File Watching | watchdog |
| PDF Parsing | PyMuPDF |
| Office Parsing | python-docx, openpyxl |

</td>
<td><strong>Frontend</strong></td>
<td>

| Layer | Technology |
|---|---|
| Framework | React 18 + Vite |
| Graph Viz | react-force-graph-2d |
| Markdown | react-markdown |
| Styling | Vanilla CSS (dark theme) |
| API Client | Fetch (streaming SSE) |

</td>
</tr>
</table>

---

## ⚡ Quick Start

### Prerequisites

- Python 3.11+
- Node.js 18+
- [Qdrant](https://qdrant.tech/documentation/quick-start/) running on `localhost:6333`
- [Neo4j](https://neo4j.com/download/) running on `localhost:7687`
- A GGUF model file (see [Models](#models) below)

---

### 1. Clone the Repository

```bash
git clone https://github.com/your-username/cypher.git
cd cypher
```

---

### 2. Backend Setup

```bash
cd backend

# Create and activate a virtual environment
python -m venv .venv
.venv\Scripts\activate          # Windows
# source .venv/bin/activate     # Linux/macOS

# Install dependencies
pip install -r requirements.txt
```

> **GPU Acceleration:** Install the CUDA-enabled llama-cpp-python wheel for your CUDA version:
> ```bash
> pip install llama-cpp-python --extra-index-url https://abetlen.github.io/llama-cpp-python/whl/cu121
> ```

---

### 3. Download Models

Place GGUF model files in the `models/` directory at the project root:

```
cypher/
└── models/
    ├── Qwen3VL-8B-Instruct-Q4_K_M.gguf      ← main LLM
    └── mmproj-Qwen3VL-8B-Instruct-Q8_0.gguf ← vision projector (for image/P&ID)
```

Download from Hugging Face:
- [Qwen/Qwen3-VL-8B-Instruct-GGUF](https://huggingface.co/Qwen/Qwen3-VL-8B-Instruct-GGUF)

---

### 4. Configure Environment

Create a `.env` file in `backend/`:

```env
# Database connections
NEO4J_URI=neo4j://localhost:7687
NEO4J_USER=neo4j
NEO4J_PASSWORD=your_password

QDRANT_HOST=localhost
QDRANT_PORT=6333

# Model paths (override defaults)
QWEN_MODEL_PATH=../models/Qwen3VL-8B-Instruct-Q4_K_M.gguf
CLIP_PROJECTOR_PATH=../models/mmproj-Qwen3VL-8B-Instruct-Q8_0.gguf

# LLM tuning
LLM_N_GPU_LAYERS=auto   # auto = maximize VRAM usage
LLM_N_CTX=4096
LLM_MAX_TOKENS=1024
```

---

### 5. Start the Backend

```bash
cd backend
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

You'll see:
```
🚀 Starting Cypher AI Brain...
  ✅ SQLite initialized
  ✅ Qdrant connected
  ✅ Neo4j connected
  ✅ AI models configured (lazy-loaded on first use)
  ✅ Query engine initialized
  ✅ Ingestion pipeline initialized
🧠 Cypher AI Brain is ready!
```

---

### 6. Start the Frontend

```bash
cd ui
npm install
npm run dev
```

Open **http://localhost:5173** 🎉

---

### 7. Ingest Your Documents

In the **Knowledge Base** tab → Add Folder → browse to a directory containing your PDFs, Word docs, P&IDs, or any other supported file.

Cypher will automatically watch the folder and ingest every file, showing real-time status for each document.

---

## ⚙️ Configuration

All configuration lives in [`backend/app/config.py`](backend/app/config.py) with environment variable overrides.

| Config Class | Key Setting | Default | Description |
|---|---|---|---|
| `LLMConfig` | `N_GPU_LAYERS` | `auto` | `auto` = plan from free VRAM; `0` = CPU-only |
| `LLMConfig` | `N_CTX` | `4096` | Context window size |
| `LLMConfig` | `IDLE_UNLOAD_SECONDS` | `600` | Unload model after 10 min idle |
| `RetrievalConfig` | `VECTOR_TOP_K` | `5` | Top chunks kept after reranking |
| `RetrievalConfig` | `VECTOR_FETCH_K` | `15` | Over-fetch before reranking |
| `RetrievalConfig` | `GRAPH_SEARCH_DEPTH` | `2` | Neo4j traversal hops |
| `ExtractionConfig` | `WINDOW_CHARS` | `2000` | Entity extraction window size |
| `ExtractionConfig` | `MAX_WINDOWS` | `8` | Max windows per document |

---

## 📁 Project Structure

```
cypher/
├── backend/
│   └── app/
│       ├── ai/
│       │   ├── embeddings.py          # BGE wrapper
│       │   ├── entity_extractor.py    # LLM-based KG extraction
│       │   ├── hardware.py            # VRAM detection & GPU planning
│       │   ├── llm.py                 # LLM wrapper
│       │   └── model_manager.py       # Persistent GGUF worker process
│       ├── api/
│       │   ├── chat.py                # /api/chat (streaming)
│       │   ├── compliance.py          # /api/compliance/gaps
│       │   ├── documents.py           # /api/documents
│       │   ├── graph.py               # /api/graph
│       │   ├── ingestion.py           # /api/ingest
│       │   └── models.py              # Pydantic schemas
│       ├── ingestion/
│       │   ├── pipeline.py            # Main ingestion orchestrator
│       │   ├── dispatcher.py          # Routes files to correct processor
│       │   ├── chunking.py            # Text chunking strategy
│       │   ├── watcher.py             # watchdog folder monitor
│       │   └── queue.py               # Async ingestion queue
│       ├── processors/
│       │   ├── pdf_processor.py
│       │   ├── office_processor.py    # DOCX + XLSX
│       │   ├── image_processor.py     # PNG/JPG via VLM
│       │   ├── email_processor.py     # .eml files
│       │   ├── audio_processor.py     # MP3/WAV
│       │   └── video_processor.py     # MP4
│       ├── retrieval/
│       │   ├── query_engine.py        # Main RAG orchestrator
│       │   ├── vector_retriever.py    # Qdrant semantic search
│       │   ├── graph_retriever.py     # Neo4j entity search
│       │   ├── reranker.py            # Cross-encoder reranking
│       │   ├── context_builder.py     # Assembles LLM context
│       │   └── compliance.py          # Compliance gap analyzer
│       └── storage/
│           ├── neo4j.py               # Graph DB operations
│           ├── qdrant.py              # Vector DB operations
│           └── sqlite.py             # Document tracking
└── ui/
    └── src/
        ├── components/
        │   ├── ChatView.jsx           # Chat interface with citations
        │   ├── ComplianceView.jsx     # Compliance gap intelligence
        │   ├── ForceGraph.jsx         # Force-directed graph renderer
        │   ├── GraphView.jsx          # Graph explorer with search
        │   ├── KnowledgeView.jsx      # Document management
        │   └── Sidebar.jsx            # Navigation & system status
        ├── api.js                     # API client + color palette
        ├── App.jsx                    # Root component + routing
        ├── icons.jsx                  # SVG icon library
        └── index.css                  # Design system (dark theme)
```

---

## 🔌 API Reference

| Endpoint | Method | Description |
|---|---|---|
| `GET /api/health` | GET | System status — all services |
| `POST /api/chat` | POST | Ask a question (streaming response) |
| `GET /api/chat/sessions` | GET | List all chat sessions |
| `GET /api/chat/sessions/{id}` | GET | Full session with message history |
| `POST /api/ingest/start` | POST | Add a folder to watch |
| `POST /api/ingest/stop` | POST | Remove a folder |
| `GET /api/ingest/status` | GET | Ingestion statistics |
| `GET /api/documents` | GET | All ingested documents |
| `GET /api/documents/open` | GET | Open/download a source file |
| `POST /api/graph/query` | POST | Traverse the knowledge graph |
| `GET /api/graph/full` | GET | Full graph for visualization |
| `GET /api/graph/stats` | GET | Entity/relationship counts |
| `GET /api/compliance/gaps` | GET | Compliance coverage report |

---

## 🧪 Evaluation Metrics

| Metric | What We Measure |
|---|---|
| **Entity Extraction Accuracy** | Precision & Recall of EQUIPMENT, REGULATION, FAILURE entities vs. expert-annotated ground truth |
| **Query Answer Quality** | ROUGE-L & BERTScore on 50 industrial Q&A pairs; Human eval for Relevance (1–5) and Factual Accuracy (1–5) |
| **Compliance Gap Accuracy** | F1-score on detecting real regulatory gaps vs. reference coverage map |
| **Retrieval Latency (P95)** | Target: <8 s on GPU, <30 s CPU-only. Dual-retrieval runs in parallel |
| **Cross-Functional Discovery** | Whether graph surfaces non-obvious multi-document connections that keyword search would miss |

---

## 💡 Usage Examples

### Querying the Knowledge Copilot

> **Q:** *What caused the last failure of Pump P-101 and what procedure was used to fix it?*

Cypher will:
1. Semantically retrieve maintenance reports mentioning Pump P-101
2. Traverse the graph: `Pump P-101 → HAS_FAILURE → Bearing Wear → REQUIRES → Procedure WO-2024-015`
3. Return a cited answer:
   > *"The last recorded failure of Pump P-101 was bearing wear detected on 2024-03-12 [maintenance_log_Q1_2024.pdf]. The corrective procedure was WO-2024-015 which involved replacing the impeller bearing set with type 6205-ZZ [work_order_015.docx].*
   > 
   > **Sources:** maintenance_log_Q1_2024.pdf · work_order_015.docx"

---

### Compliance Check

Navigate to the **Compliance** tab → the system automatically:
- Enumerates all `REGULATION` entities from the graph
- Checks if each has linked `PROCEDURE` and evidence documents
- Surfaces GAPs in red for immediate attention

---

## 📊 System Requirements

| Tier | RAM | GPU VRAM | Performance |
|---|---|---|---|
| **Optimal** | 32 GB | ≥ 12 GB NVIDIA | All layers GPU-offloaded, <5 s queries |
| **Good** | 16 GB | 6–12 GB NVIDIA | Partial GPU offload, ~8–15 s queries |
| **Minimum (CPU)** | 16 GB | None | Full CPU inference, ~30–60 s queries |

> Cypher's `hardware.py` automatically detects free VRAM and computes the optimal `n_gpu_layers` value — no manual tuning needed.

---

## 🤝 Contributing

1. Fork the repository
2. Create your feature branch: `git checkout -b feature/amazing-feature`
3. Commit your changes: `git commit -m 'Add amazing feature'`
4. Push to the branch: `git push origin feature/amazing-feature`
5. Open a Pull Request

---

## 📜 License

This project is licensed under the MIT License — see the [LICENSE](LICENSE) file for details.

---

<div align="center">

Built with ⚡ for the industrial world.

**Cypher** — *Know everything your company knows.*

</div>
