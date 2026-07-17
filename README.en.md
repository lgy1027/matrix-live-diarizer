# Matrix Live Diarizer

A local-first, single-user meeting transcription tool. Uploaded recordings and live captions become one meeting record that can be corrected, linked to confirmed people, summarized, and exported as Markdown, SRT, VTT, or JSON.

> This is alpha software for personal use on a trusted computer. It is not a public, multi-tenant, compliance-archive, or automatic identity-verification service.

[中文](README.md) · [Usage](docs/USAGE.md) · [Privacy](docs/PRIVACY.md) · [Security](docs/SECURITY.md) · [API](docs/API.md)

## Product boundary

- Uploaded recordings are the quality path; live mode provides low-latency reference captions.
- Diarization creates anonymous speaker labels. Strict voice matches may display an enrolled person automatically, but this is not identity authentication and is always correctable.
- Without pyannote, transcription can finish but remains anonymous and reports diarization as unavailable.
- Data stays local by default and LLM features are off. Initial model downloads require network access.
- Public hosting and regulated medical or legal workflows are outside the supported scope.

## Quick start

Python 3.10–3.12, Node.js 20+, and FFmpeg are required.

```bash
python -m venv .venv
# Windows: .venv\Scripts\activate
# macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
cd web && npm ci && npm run build && cd ..
python main.py
```

Open `http://127.0.0.1:8000`. The default server binds only to loopback. Docker CPU builds are available with `docker compose up --build`, but CPU inference may be slow.

Data structures may change during the alpha period, so do not use this project as the only copy or as a long-term archive.

Maintainers publishing their own multi-architecture image can use `docker buildx build --platform linux/amd64,linux/arm64 ...`; each target must be tested separately and the project does not currently promise prebuilt images.

For LAN use, explicitly configure `HOST=0.0.0.0`, `DEPLOYMENT_MODE=lan`, a strong `JWT_SECRET`, trusted `ALLOWED_ORIGINS`, and an HTTPS reverse proxy. Mobile microphone capture normally requires HTTPS.

## Data and verification

Managed audio is stored under `data/media/`. Transcripts, people, embeddings, settings, and an optional LLM API key are stored in `data/matrix.db` without application-level encryption.

```bash
pytest -q --ignore=tests/test_smoke_boot.py
cd web && npm run check:i18n && npm run build
npm audit --omit=dev
```

Project code is under the [MIT License](LICENSE). Model weights keep their upstream licenses and terms; MIT does not relicense them. See [docs/MODELS.md](docs/MODELS.md).
