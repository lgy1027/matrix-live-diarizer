# Third-Party Notices

Matrix Live Diarizer source code is licensed under the MIT License. That license does not grant rights to third-party model weights, datasets, runtimes, or services downloaded or configured by users.

The default installation can retrieve Qwen3-ASR and speaker embedding models from ModelScope, Silero VAD from GitHub/Torch Hub, and optional pyannote Community-1 assets from Hugging Face. Optional FunASR engines and external OpenAI-compatible LLM services have their own terms. Model weights are not included in this repository or in the project license.

Before use or redistribution, review the upstream model card, license, acceptable-use terms, attribution requirements, and any gated-access agreement. In particular, pyannote Community-1 requires accepting its Hugging Face conditions and providing a token. See [docs/MODELS.md](docs/MODELS.md) for the model and network-access matrix.

Python and JavaScript packages installed from `requirements*.txt` and `web/package-lock.json` retain their respective licenses. A downstream distributor is responsible for producing a complete dependency license inventory for the exact build it ships.
