# Changelog

All notable changes to this project are documented in this file. The format is
based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the
project follows semantic versioning after its first stable release.

## [0.2.0-beta] - 2026-08-03

### Added

- Add durable background processing jobs with cancellation, recovery, retry, and progress states.
- Persist live meetings and audio, then queue full-quality refinement when a recording ends.
- Add LAN/public deployment guards, authentication hardening, readiness checks, and browser security headers.
- Add frontend unit tests, CodeQL, dependency review, dependency auditing, and Dependabot.

### Changed

- Move blocking persistence work out of the WebSocket event loop.
- Keep speaker creation and transcript writes in the same database transaction.
- Make model downloads atomic and validate pinned revisions before reuse.
- Enforce the supported single-process runtime instead of accepting unsafe worker counts.

### Security

- Pin default Qwen model downloads to immutable upstream revisions.
- Publish downloaded model directories atomically to prevent partial-cache use.
- Pin GitHub Actions to immutable commits.
- Bound concurrent login attempts and protect trusted-proxy address handling.
- Reject unsafe LLM endpoints and keep public providers behind explicit opt-in.

### Fixed

- Prevent active live meetings from being deleted during recording or refinement.
- Avoid releasing or closing inference resources while provider worker threads are still running.
- Classify permanent processing failures by exception type instead of parsing error text.
- Persist finalized live transcript segments before they are sent to the browser.
- Validate diarization waveform shape, range, sample rate, and integer PCM normalization.
- Send only the requested PCM view when a browser audio frame is a typed-array slice.
- Build native Docker wheels for the target architecture.
- Make the Docker health check work in HTTP and HTTPS modes.
- Exclude local model caches and development artifacts from Docker contexts.
- Restrict pytest discovery to the project test suite.

[0.2.0-beta]: https://github.com/lgy1027/matrix-live-diarizer/compare/v0.1.0-beta...v0.2.0-beta
