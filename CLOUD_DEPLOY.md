# Cypher — Cloud Deployment Guide (AWS)

Step-by-step instructions to deploy Cypher on an AWS EC2 instance using Amazon Bedrock for LLM inference.

---

## Prerequisites

- An AWS account with billing enabled
- At least ~$15 in credits for a 5-6 demo run (budget-safe — see cost table below)
- SSH key pair for EC2 access

---

## 1. Enable Bedrock Models

1. Go to **Amazon Bedrock** → **Model access** in the AWS console
2. Region: **us-east-1** (N. Virginia) — best model availability
3. Request access to:
   - **Anthropic Claude 3.5 Haiku** (`us.anthropic.claude-3-5-haiku-20241022-v1:0`)
   - **Amazon Titan Text Embeddings V2** (`amazon.titan-embed-text-v2:0`)
4. Access is usually granted instantly

---

## 2. Launch EC2 Instance

| Setting | Value |
|---|---|
| AMI | Ubuntu 24.04 LTS (x86_64) |
| Instance type | **t3.medium** (2 vCPU, 4 GB RAM) |
| Storage | 30 GB gp3 EBS |
| Security group | Ports 22 (SSH), 80 (HTTP) |

### Attach IAM Role

1. Create an IAM role with the policy **AmazonBedrockFullAccess**
2. Attach it to the EC2 instance (Actions → Security → Modify IAM role)
3. This is more secure than using access keys — no secrets in `.env`

---

## 3. Install Docker

SSH into your instance and run:

```bash
# Update system
sudo apt update && sudo apt upgrade -y

# Install Docker
curl -fsSL https://get.docker.com | sudo sh
sudo usermod -aG docker $USER

# Install Docker Compose plugin
sudo apt install -y docker-compose-plugin

# Re-login for group changes
exit
# SSH back in
```

---

## 4. Deploy Cypher

```bash
# Clone the repo
git clone https://github.com/YOUR_REPO/Cypher.git
cd Cypher
git checkout cloud

# Configure
cp .env.cloud.example .env
nano .env  # Set NEO4J_PASSWORD and WEB_PORT (80)

# Build and start (first build takes ~10-15 min)
docker compose up -d --build

# Watch logs
docker compose logs -f backend
```

---

## 5. Access the UI

Open `http://<your-ec2-public-ip>` in **Chrome or Edge**.

1. Click **"Connect Local Folder"** in the sidebar
2. Pick a local folder with your industrial documents
3. The browser reads your files and uploads them to the server
4. Watch the ingestion progress in the logs
5. Start chatting — Cypher answers with citations

> **Note:** The File System Access API requires **Chrome** or **Edge**. Firefox is not supported.

---

## 6. Cost Management

### Estimated costs for 5-6 demo runs

| Item | Unit cost | Usage | Total |
|---|---|---|---|
| EC2 t3.medium | $0.048/hr | 5 days | ~$5.80 |
| Claude 3.5 Haiku (input) | $0.80/MTok | 6 × 200K tok | ~$0.96 |
| Claude 3.5 Haiku (output) | $4/MTok | 6 × 50K tok | ~$1.20 |
| Titan Embed v2 | $0.02/1K tok | 100K tok | ~$2.00 |
| EBS 30 GB gp3 | $0.08/GB/mo | 1 month | ~$2.40 |
| **Total** | | | **~$12.36** |

### Cost-saving tips

- **Stop the instance when not demoing** — EC2 stops billing when stopped
- Use an **Elastic IP** ($0) so the public IP doesn't change between stops
- Don't leave `docker compose up` running overnight
- Delete the instance + EBS when done with all demos

### How to stop/start

```bash
# From your local machine
aws ec2 stop-instances --instance-ids i-xxxxxxxxx
# When you need it again:
aws ec2 start-instances --instance-ids i-xxxxxxxxx
```

---

## 7. Troubleshooting

### "Bedrock model not accessible"
- Verify model access in the Bedrock console (us-east-1)
- Check the IAM role is attached: `curl http://169.254.169.254/latest/meta-data/iam/security-credentials/`

### "Backend offline" in the UI
- Check backend logs: `docker compose logs backend`
- Verify Qdrant and Neo4j are healthy: `docker compose ps`

### "File System Access API not supported"
- Use Chrome or Edge — Firefox doesn't support this API

### Re-ingest after model changes
If you switch embedding models, the Qdrant collection dimensions won't match. Delete the volume and re-ingest:
```bash
docker compose down
docker volume rm cypher_qdrant_data
docker compose up -d
```
