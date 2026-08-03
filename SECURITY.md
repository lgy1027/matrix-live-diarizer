# Security Policy

Matrix Live Diarizer is local-first software for a trusted local computer; public deployment is not supported.

See [docs/SECURITY.md](docs/SECURITY.md) for deployment defaults, sensitive-data handling, and the LAN checklist.

Do not publish recordings, transcripts, credentials, voice embeddings, or exploit details in an issue. Report vulnerabilities privately through [GitHub Security Advisories](https://github.com/lgy1027/matrix-live-diarizer/security/advisories/new).

## Temporary dependency exceptions

CI runs `pip-audit` and fails on every advisory except the entries below. These
exceptions are compatibility holds, not claims that the packages are generally
safe. They must be reviewed by **2026-10-01** or whenever the related model stack
adds support for the fixed versions, whichever comes first.

| Advisory | Dependency | Current mitigation |
|---|---|---|
| `PYSEC-2025-194` | PyTorch 2.11 | Audio/model inputs stay local; upgrade the Torch family together after real-model validation. |
| `PYSEC-2025-217`, `PYSEC-2026-2288`, `PYSEC-2026-2289`, `PYSEC-2026-2290` | Transformers 4.x | Remote model revisions are immutable by default; downloads publish atomically; the managed model directory must not be writable by untrusted users. |
| `PYSEC-2026-3447` | setuptools <81 | The affected sdist-build path is not used to publish this application; the upper bound remains for ModelScope compatibility. |

Removing an exception requires both the dependency audit and the real-model
release validation workflow to pass.
