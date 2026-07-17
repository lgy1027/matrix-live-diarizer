# Usage

## Upload a recording

From Home, select a file and choose:

- **Quick transcript** for text only.
- **Meeting mode** for text plus optional offline speaker separation.

The upload is decoded before a durable job is accepted. Task progress appears under Tasks. A completed transcript can still report speaker separation as unavailable; this is not treated as an identity result.

## Correct a meeting

Open Meetings, search for transcript text, and select a result to jump to its exact segment. Double-click text to edit it. Anonymous speaker labels can be reassigned in batches. Confirm a person only after listening to the audio.

## Register a person

Create a person under People and upload a clear voice sample of at least two seconds. Expand **Manage samples** to preview recordings, inspect effective-speech and quality indicators, or remove a mistaken sample. Samples and embeddings remain on the local machine. A model-engine change can make existing embeddings incompatible; add a new sample for the active engine if matching is unavailable.

## Live captions

Live mode stores audio and final transcript segments as a meeting. Captions and speaker labels are approximate. Use an uploaded full recording when post-meeting quality matters. Browsers require microphone permission; non-loopback mobile access generally requires HTTPS.

## Notes and export

Summary, actions, and minutes have a local extractive fallback. Enabling an external LLM sends transcript text to the configured endpoint. Review generated notes before use. Export formats are Markdown, SRT, WebVTT, and JSON.
