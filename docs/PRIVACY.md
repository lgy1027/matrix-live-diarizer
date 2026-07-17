# Privacy

Matrix is local-first, not zero-storage. The application intentionally persists data so meetings remain available after restart.

## Stored locally

| Data | Default location | Encrypted by app |
|---|---|---|
| Meeting audio, including live recordings | `data/media/` | No |
| Transcripts, notes, people, voice embeddings | `data/matrix.db` | No |
| Non-secret settings (LLM endpoint/model/enabled state) | `data/matrix.db` | No |
| Optional LLM API key | `LLM_API_KEY` process environment / `.env` | No |
| Model files | User ModelScope/Hugging Face/Torch caches | No |

Use operating-system full-disk encryption and a protected user account. Voice recordings and embeddings are biometric-sensitive information; register samples only with appropriate consent.

## Network behavior

Network access occurs when models or Python/npm dependencies are downloaded.
Model hosts include ModelScope, Hugging Face, and Torch Hub according to the
selected capability; pyannote additionally requires the user to accept its
gated model terms and provide `HF_TOKEN`.

LLM features are disabled by default. Reading `/v1/llm/status` and saving LLM
settings do not contact the configured endpoint. Clicking **Test connection**
sends one minimal request without meeting text and may incur provider usage.
Generating a summary, action list, or minutes with an enabled external
OpenAI-compatible endpoint sends transcript text and prompts to that endpoint;
audio and voice embeddings are not included by the application.

The LLM API key is read from `LLM_API_KEY`; it is not written to SQLite or
returned to the browser. Protect `.env`, process environments, backups, and
diagnostic bundles as secrets.

The repository contains no product analytics or telemetry SDK. Server logs may contain operational metadata and errors, but should not log audio or API keys.

## Deletion

Deleting a meeting removes its database records and application-managed audio. Deleting a person removes registered voice-sample files and detaches that person from meetings without deleting the meetings. Stop the service before deleting `data/` to erase all managed product data. Model caches and `.env` are separate and must be removed independently when required.

No automatic backup or retention purge is currently provided. Users are responsible for backups, retention, consent, and compliance obligations.
