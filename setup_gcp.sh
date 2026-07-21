#!/bin/bash
# =============================================================================
# Cypher — GCP VM Setup Script
# Run this ONCE on a fresh Ubuntu 22.04 VM with an NVIDIA T4 GPU
# Usage: bash setup_gcp.sh
# =============================================================================
set -e

echo "============================================="
echo "  Cypher GCP Deployment Script"
echo "============================================="

# 1. Install NVIDIA drivers + Docker + nvidia-container-toolkit
echo ""
echo "[1/6] Installing NVIDIA drivers..."
sudo apt-get update -qq
sudo apt-get install -y linux-headers-$(uname -r)
distribution=$(. /etc/os-release; echo $ID$VERSION_ID)

# Docker
echo "[2/6] Installing Docker..."
curl -fsSL https://get.docker.com | sudo sh
sudo usermod -aG docker $USER

# NVIDIA Container Toolkit
echo "[3/6] Installing NVIDIA Container Toolkit..."
curl -fsSL https://nvidia.github.io/libnvidia-container/gpgkey | sudo gpg --dearmor -o /usr/share/keyrings/nvidia-container-toolkit-keyring.gpg
curl -s -L "https://nvidia.github.io/libnvidia-container/stable/deb/nvidia-container-toolkit.list" | \
  sed 's#deb https://#deb [signed-by=/usr/share/keyrings/nvidia-container-toolkit-keyring.gpg] https://#g' | \
  sudo tee /etc/apt/sources.list.d/nvidia-container-toolkit.list
sudo apt-get update -qq
sudo apt-get install -y nvidia-container-toolkit
sudo nvidia-ctk runtime configure --runtime=docker
sudo systemctl restart docker

# Install NVIDIA drivers if not present
if ! command -v nvidia-smi &> /dev/null; then
  sudo apt-get install -y ubuntu-drivers-common
  sudo ubuntu-drivers install
fi

# 4. Clone the project
echo "[4/6] Cloning Cypher..."
if [ ! -d "Cypher" ]; then
  git clone https://github.com/BW095/Cypher.git
fi
cd Cypher

# 5. Create .env file
echo "[5/6] Creating .env file..."
cat > .env << 'EOF'
NEO4J_PASSWORD=Cypher@2024
WEB_PORT=8080
DOCUMENTS_DIR=./documents
EOF

mkdir -p documents models

# 6. Download models from HuggingFace
echo "[6/6] Downloading GGUF models (this takes 10-20 min)..."
pip3 install -q huggingface_hub

python3 - << 'PYEOF'
from huggingface_hub import hf_hub_download
import os

models = [
    {
        "repo": "Qwen/Qwen3-VL-8B-Instruct-GGUF",
        "file": "Qwen3-VL-8B-Instruct-Q4_K_M.gguf",
        "dest": "Qwen3VL-8B-Instruct-Q4_K_M.gguf"
    },
    {
        "repo": "Qwen/Qwen3-VL-8B-Instruct-GGUF",
        "file": "mmproj-Qwen3-VL-8B-Instruct-Q8_0.gguf",
        "dest": "mmproj-Qwen3VL-8B-Instruct-Q8_0.gguf"
    },
    {
        "repo": "Qwen/Qwen2.5-3B-Instruct-GGUF",
        "file": "qwen2.5-3b-instruct-q4_k_m.gguf",
        "dest": "Qwen2.5-3B-Instruct-Q4_K_M.gguf"
    },
]

for m in models:
    dest = f"./models/{m['dest']}"
    if os.path.exists(dest):
        print(f"  Already exists: {m['dest']}")
        continue
    print(f"  Downloading {m['file']}...")
    path = hf_hub_download(
        repo_id=m["repo"],
        filename=m["file"],
        local_dir="./models",
        local_dir_use_symlinks=False
    )
    if path != dest:
        os.rename(path, dest)
    print(f"  ✅ {m['dest']}")

print("All models downloaded!")
PYEOF

# 7. Build and start everything
echo ""
echo "Building and starting Cypher (first build takes ~15 min)..."
sudo docker compose up -d --build

echo ""
echo "============================================="
echo "  ✅ Cypher is deploying!"
echo "============================================="
echo ""
echo "  Monitor progress:  sudo docker compose logs -f"
echo "  Check status:      sudo docker compose ps"
echo ""

# Get public IP
PUBLIC_IP=$(curl -s ifconfig.me 2>/dev/null || echo "YOUR_VM_IP")
echo "  Once all services are UP, your app will be at:"
echo ""
echo "  👉  http://${PUBLIC_IP}:8080"
echo ""
echo "  To get a clean HTTPS URL, run:"
echo "  curl -L https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64 -o cloudflared"
echo "  chmod +x cloudflared && ./cloudflared tunnel --url http://localhost:8080"
echo ""
