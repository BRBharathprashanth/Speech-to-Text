---
title: Speech to Text
emoji: 🎙️
colorFrom: blue
colorTo: indigo
sdk: docker
app_port: 8001
pinned: false
---

# Hugging Face Spaces Deployment Configuration

1. Create a free **Neon** PostgreSQL database (https://neon.tech) and copy its connection string (`postgresql://...?sslmode=require`).
2. Create a new **Hugging Face Space** with SDK **Docker** (CPU Basic — 2 vCPU, 16 GB RAM, Free).
3. In the Space **Settings -> Variables and secrets**:
   - **Secret**: `DATABASE_URL` = your Neon PostgreSQL connection string
   - **Variable**: `APP_ENV` = `production`
   - **Variable**: `WHISPER_MODEL` = `small`
   - **Variable**: `WHISPER_DEVICE` = `cpu`
   - **Variable**: `WHISPER_COMPUTE_TYPE` = `int8`
   - **Variable**: `HF_HOME` = `/models/hf`
   - **Variable**: `PORT` = `8001`
   - **Variable**: `ALLOWED_WS_ORIGINS` = `https://<your-hf-username>-<your-space-name>.hf.space`
4. Push this repository to the Space remote with the YAML frontmatter above at the top of `README.md`.
5. Wait for the Docker build & startup, then verify `/health`, `/health/db`, `/docs`, file upload, CRUD, and `wss://` WebSocket streaming.
