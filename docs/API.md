# API

The beta API serves one local user. Contracts may still change before a stable release. Except for health, model catalog, login, and limited status endpoints, `/v1/*` requires authentication when local bypass is disabled.

## Meetings

| Method | Path | Purpose |
|---|---|---|
| `POST` | `/v1/meetings/upload?mode=quick|meeting` | Validate and queue an audio recording |
| `GET` | `/v1/meetings` | List meetings |
| `GET` | `/v1/meetings/search?q=...` | Search transcript text |
| `GET/PATCH/DELETE` | `/v1/meetings/{id}` | Read, rename, or delete a meeting |
| `GET` | `/v1/meetings/{id}/audio` | Stream managed audio |
| `PATCH` | `/v1/meetings/{id}/segments/{segment_id}` | Correct text |
| `PATCH` | `/v1/meetings/{id}/segments/speaker` | Assign selected segments |
| `PATCH` | `/v1/meetings/{id}/speakers/{speaker_id}/person` | Confirm or clear a person |
| `POST/PUT` | `/v1/meetings/{id}/notes/{summary|minutes|actions}` | Generate or edit a note |
| `GET` | `/v1/meetings/{id}/export?format=markdown|srt|vtt|json` | Export |

`status=ready` means the transcript is usable. `transcript_state=draft|refined`
distinguishes a provisional live transcript from a completed refinement. Check
`diarization_status` separately: `completed`, `unavailable`, `pending`, or
`not_requested`. A usable draft is retained if refinement fails.
While `status=processing`, draft text, speaker/person assignments, and meeting
outputs are read-only so the atomic refinement cannot overwrite user changes.
Meeting detail includes the most recent `processing_job` for stage/progress UI.

Meeting detail may include a `processing_manifest` describing the immutable
provenance of that processing run. Clients must treat its nested fields as
optional for records created before manifests were introduced:

```json
{
  "version": 1,
  "strategy": "external-diarization",
  "asr": {"engine": "qwen3", "model": "Qwen/Qwen3-ASR-0.6B", "timestamp_granularity": "word"},
  "diarization": {"provider": "pyannote", "status": "completed", "alignment": "word-timestamps"},
  "speaker_identity": {"engine": "campplus", "model_id": "modelscope:..."},
  "generated_at": "2026-07-16T10:00:00Z"
}
```

`SPEAKER_00`, `SPEAKER_01`, and similar labels are anonymous identifiers scoped
to one meeting. They are not person IDs. `identity_status` is one of
`anonymous`, `suggested`, `auto_matched`, or `confirmed`. Strict matches may be
displayed and exported automatically with provenance; suggestions remain
anonymous in the transcript until confirmed through the speaker/person `PATCH`.

## Jobs and people

- `GET /v1/jobs`, `GET /v1/jobs/{id}`
- `POST /v1/jobs/{id}/cancel`, `POST /v1/jobs/{id}/retry`
- `GET/POST /v1/people`
- `GET/PATCH/DELETE /v1/people/{id}`
- `POST /v1/people/{id}/samples`
- `GET /v1/people/{id}/samples/{sample_id}/audio`
- `DELETE /v1/people/{id}/samples/{sample_id}`

People are locally enrolled identities. Automatic display requires compatible
embedding models, enough meeting speech, at least two strong enrollment samples,
and stricter confidence/ambiguity thresholds than ordinary suggestions.

## Runtime configuration

- `GET /v1/models`, `GET /v1/engines`, `PUT /v1/engine`
- `GET /v1/asr/engines`, `PUT /v1/asr/engine`
- `GET/PUT /v1/llm/settings`, `GET /v1/llm/status`, `POST /v1/llm/test`
- `POST /v1/auth/login`, `GET /v1/auth/me`, `POST /v1/auth/change-password`
- `GET /health`, `GET /ready`
- `WS /ws/v1/stream/{client_id}`

OpenAPI is available at `/docs` while the server is running.

`GET /v1/llm/status` is passive and returns only configuration plus the most
recent explicit test result. Only `POST /v1/llm/test` sends a minimal `ping`
request to the configured OpenAI-compatible `/chat/completions` endpoint.
Saving LLM settings clears the previous test result but does not contact the
LLM service.

LLM API keys are read from the `LLM_API_KEY` process environment. They are not
accepted by the settings API, returned to the browser, or stored in SQLite.
