<div align="center">

# Matrix Live Diarizer

**Local-first meeting speech AI · zero external transfer by default**

For small meetings and personal live captions. Transcription, speaker identification, and meeting summaries run on your own machine.
Audio and transcripts stay local by default, and ASR / speaker / LLM engines can be switched from the Settings page.

[![Python](https://img.shields.io/badge/Python-3.12+-blue.svg)](https://www.python.org/downloads/)
[![License](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)
[![ModelScope](https://img.shields.io/badge/ModelScope-Qwen3--ASR-orange.svg)](https://modelscope.cn/models/Qwen/Qwen3-ASR-0.6B)

[中文](README.md) | **English**

</div>

---

## Value In 30 Seconds

> Your meeting audio -> local transcription + speaker identification + summaries.
> **Zero external transfer by default.** Optional LLM integrations include Ollama, LM Studio, LAN vLLM, and OpenAI-compatible endpoints.

## Why Matrix Instead Of Cloud Meeting Transcription?

| | Cloud transcription | Matrix |
|---|---|---|
| Audio uploaded to cloud | Required | Never by default |
| Transcription speed | Network-dependent | Hardware-dependent |
| LAN LLM | Not supported | Supported |
| Offline mode | No | Yes, after models are cached |
| Cost | Subscription | Self-hosted |
| Speaker identification | Generic | Local enrollment supported |
| Data ownership | Vendor | You |

## Target Users

- Small teams: weekly meetings, reviews, customer calls, automatic minutes.
- Developers and creators: live captions for courses, livestreams, podcasts.
- Privacy-sensitive work: legal, medical, journalism, internal interviews.
- LAN AI users: already running Ollama, LM Studio, LocalAI, or vLLM.

## Docker Quick Start

No host-side PyTorch installation is required. The Docker image uses CPU PyTorch by default; models and data are persisted in Docker volumes.

```bash
# 1. Clone
git clone https://github.com/lgy1027/matrix-live-diarizer.git
cd matrix-live-diarizer

# 2. Optional: copy runtime config
cp .env.example .env

# If the container should call Ollama on the host, do not use 127.0.0.1:
# LLM_ENABLED=true
# LLM_ENDPOINT=http://host.docker.internal:11434/v1

# 3. Build and start
docker compose up -d

# 4. Watch logs. First run downloads ASR / VAD / speaker models.
docker compose logs -f

# 5. Open the web UI
# Default: http://127.0.0.1:8000/
# If .env sets PORT=8888, open http://127.0.0.1:8888/
```

Common commands:

```bash
# Rebuild
docker compose build --pull

# Stop but keep data and model volumes
docker compose down

# Remove service and volumes. This deletes model cache and local history.
docker compose down -v
```

Notes:

- `docker-compose.yml` optionally reads `.env`.
- `PORT` controls both the container listening port and the host mapping.
- ModelScope, HuggingFace, Torch caches, SQLite data, uploads, and speaker DB are persisted in volumes.
- Multi-arch image publishing should use buildx, for example:
  `docker buildx build --platform linux/amd64,linux/arm64 -t your-name/matrix-live-diarizer:latest --push .`
- The default Docker image is CPU-only. For NVIDIA GPU, build a CUDA PyTorch based image and add `gpus: all` to compose.

## Run From Source

```bash
# 1. Install backend dependencies
git clone https://github.com/lgy1027/matrix-live-diarizer.git
cd matrix-live-diarizer
pip install -r requirements.txt

# 2. Build frontend
cd web
npm ci
npm run build
cd ..

# 3. Start backend
ASR_DEVICE=cpu python main.py

# 4. Open
# http://127.0.0.1:8000/
```

Development mode:

```bash
# Terminal 1: backend
python main.py

# Terminal 2: frontend
cd web
npm ci
npm run dev
# http://127.0.0.1:5173/
```

If the backend is not on port 8000, configure `web/.env.local`:

```bash
VITE_BACKEND_URL=http://127.0.0.1:8888
# Optional. Usually inferred from VITE_BACKEND_URL.
# VITE_BACKEND_WS=ws://127.0.0.1:8888
```

## Features

- Real-time transcription: browser microphone -> WebSocket -> live text.
- Offline file processing: upload audio, transcribe, identify speakers, export SRT / VTT / Markdown / JSON.
- Multiple ASR engines: Qwen3-ASR, SenseVoice, Paraformer, Paraformer Streaming.
- Speaker identification: enroll local voiceprints and label speakers.
- Switchable speaker engines: CamPlus, ERes2NetV2, Wespeaker.
- Optional local LLM: summaries, action items, minutes via Ollama / LM Studio / LocalAI / vLLM / OpenAI-compatible endpoints.
- Offline fallback: TextRank summaries when LLM is disabled or unavailable.
- Local history: transcripts are stored in local SQLite.
- JWT authentication: default `admin/admin`, forced password change on first login.
- Safety defaults: DNS rebinding protection, localhost-only runtime LLM settings, prompt isolation.
- Responsive UI for desktop, tablet, and mobile.

## Settings Page

The Settings page supports runtime configuration:

| Setting | UI Capability | Behavior |
|---|---|---|
| ASR engine | Dynamic switch | The old ASR remains active until the new model is loaded |
| Speaker engine | Confirmed switch | Switch CamPlus / ERes2NetV2 / Wespeaker |
| Local LLM | Provider / endpoint / model / API key | Saved to local SQLite settings, no restart required |
| History storage | Status display | Controlled by `STORAGE_HISTORY_ENABLED` |

`.env` remains the default configuration source. Once LLM settings are saved in the UI, those settings override `.env` LLM defaults.

## Authentication

- First startup creates `admin/admin`.
- The UI forces a password change before normal use.
- `/v1/*` endpoints require `Authorization: Bearer <token>`.
- JWT tokens are valid for 24 hours by default and stored in `localStorage`.

Production checklist:

- Set `JWT_SECRET`.
- Use HTTPS when exposing beyond localhost.
- Set `ALLOWED_ORIGINS` to trusted origins instead of `*`.

## Speaker Identification Limits

Speaker identification accuracy depends strongly on meeting conditions:

| Scenario | Accuracy | Recommended Mode | Notes |
|---|---:|---|---|
| Single-speaker lecture / podcast | 95%+ | Real-time | Best fit for the realtime pipeline |
| 2-3 speakers, quiet room | 60-80% | Real-time | Manual enrollment improves results |
| 3-10 speakers, single mic, overlap | 40-60% | Real-time as reference | Physical single-mic limitation |
| Multi-mic with enrollment | 85%+ | Real-time + enrollment | Best realtime multi-speaker setup |
| Offline high-accuracy diarization | 80%+ DER target | Upload + `?diarization=pyannote` | Requires pyannote setup |

Key constraints:

- A single microphone cannot separate overlapping speakers.
- Realtime mode uses short segments, so clustering context is limited.
- ASR generally assumes one dominant speaker per segment.

## ASR Engines

| Engine | Model | Dependency | Recommended Use |
|---|---|---|---|
| Qwen3-ASR | `Qwen/Qwen3-ASR-0.6B` | `qwen-asr` | Default high-quality Chinese / multilingual ASR |
| SenseVoice-Small | `iic/SenseVoiceSmall` | `funasr` | Faster multilingual upload transcription |
| Paraformer | `paraformer-zh` | `funasr` | Stable Chinese meeting / interview transcription |
| Paraformer Streaming | `paraformer-zh-streaming` | `funasr` | Low-latency live captions |

If a target model or dependency is unavailable, the backend returns a clear error and keeps the current ASR active.

On Windows + Python 3.13, `funasr` may fail to install because `editdistance` may not have a prebuilt wheel. Use Python 3.10-3.12 or Docker for FunASR engines.

## Speaker Engines

| Engine | EER VoxCeleb | EER CNCeleb | Params | Speed | Use Case |
|---|---:|---:|---:|---|---|
| CamPlus | 0.65% | 6.78% | 7.2M | Fast | Default realtime engine |
| ERes2NetV2 | 0.61% | 6.14% | 17.8M | Medium | Higher precision |
| Wespeaker | 1.05% | 6.92% | 6.34M | Fast | Classic stable baseline |

## Project Structure

```text
matrix-live-diarizer/
├── main.py                # Entry point
├── app/                   # FastAPI application layer
│   ├── api/               # websocket / upload / speakers / health / settings
│   ├── repositories/      # SQLite persistence
│   ├── services/          # LLM / exporter / statistics / pyannote
│   ├── middleware/        # auth / rate limit
│   └── config.py          # dataclass configuration
├── engine/                # Inference engines
│   ├── asr_engine.py      # Qwen3-ASR compatibility layer + Silero VAD
│   ├── asr/               # ASR factory + FunASR engine + dynamic switch manager
│   └── speaker/           # Speaker engines + dynamic switch manager
├── tests/                 # Unit / API / smoke tests
├── docs/                  # Detailed documentation
└── web/                   # Vue / Vite frontend
```

## Model Sources

| Module | Models | Source |
|---|---|---|
| ASR | Qwen3-ASR / SenseVoice / Paraformer | ModelScope |
| Speaker | CamPlus / ERes2NetV2 / Wespeaker | ModelScope |
| VAD | Silero VAD | torch.hub |

Models are downloaded on first use and cached locally or in Docker volumes.

## FAQ

**Q: `python main.py` hangs for several minutes on macOS?**  
A: MPS can stall while loading Qwen3-ASR. Use `ASR_DEVICE=cpu python main.py`.

**Q: How do I use a high-quality remote LLM while preserving privacy?**  
A: Run a local OpenAI-compatible proxy such as LiteLLM, then set the Settings page provider to `Custom` and endpoint to `http://127.0.0.1:4000/v1`.

**Q: Does data go to the cloud?**  
A: Not by default. Public LLM endpoints require `LLM_ALLOW_PUBLIC=true`; only transcript text is sent, never audio or speaker vectors.

**Q: How does the frontend connect to a non-8000 backend?**  
A: Set `VITE_BACKEND_URL=http://127.0.0.1:8888` in `web/.env.local`.

**Q: Why cannot Docker reach host Ollama through `127.0.0.1`?**  
A: Inside the container, `127.0.0.1` means the container itself. Use `http://host.docker.internal:11434/v1`.

## License

[MIT](LICENSE)
