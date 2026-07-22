# Security

## Supported deployment

The supported beta deployment is one user on a trusted computer. The default server binds to `127.0.0.1`. Local browser requests may bypass login only when the network peer and browser Origin are trusted loopback values.

LAN mode is an advanced deployment, not a multi-user security boundary. All authenticated users would access the same meetings and people.

## Safe defaults

- No wildcard CORS in the default configuration
- HTTP and WebSocket Origin validation for local bypass
- JWT authentication outside trusted local bypass
- First-login password change for the default account
- Rate limits and basic browser security headers
- Public LLM endpoints require explicit opt-in

## LAN checklist

```dotenv
HOST=0.0.0.0
DEPLOYMENT_MODE=lan
LOCAL_AUTH_DISABLED=false
JWT_SECRET=<at-least-32-random-bytes>
ALLOWED_ORIGINS=https://matrix.example.internal
```

Put the service behind an HTTPS reverse proxy and firewall. Do not expose port 8000 directly to the internet. Keep `WORKERS=1`; inference engines and the in-process job runner are designed for one process.

## Sensitive material

Audio, transcripts, embeddings, SQLite files, `.env`, JWT secrets, and LLM keys must never be committed. API keys saved in Settings are stored in SQLite without application-level encryption. Prefer a local LLM or an environment variable when stronger secret isolation is required.

Model loaders download third-party artifacts and some ModelScope packages may execute trusted upstream model code. Review model sources and licenses, use isolated environments, and avoid running unreviewed cache contents with elevated privileges.

## Reporting

Do not open a public issue containing recordings, transcripts, credentials, or exploit details. Report vulnerabilities privately through [GitHub Security Advisories](https://github.com/lgy1027/matrix-live-diarizer/security/advisories/new). Repository maintainers must enable private vulnerability reporting before release.
