import sys
import types
from pathlib import Path

import pytest

from app.services import model_resolver


@pytest.fixture()
def isolated_models(tmp_path, monkeypatch):
    monkeypatch.setattr(
        model_resolver._cfg().models, "models_dir", str(tmp_path / "models")
    )
    return tmp_path / "models"


def test_hf_download_is_published_atomically(isolated_models, monkeypatch):
    calls = {}

    def snapshot_download(repo_id, *, revision, local_dir):
        calls.update(repo_id=repo_id, revision=revision, local_dir=local_dir)
        Path(local_dir, "config.json").write_text("{}", encoding="utf-8")

    fake_hub = types.ModuleType("huggingface_hub")
    fake_hub.snapshot_download = snapshot_download
    monkeypatch.setitem(sys.modules, "huggingface_hub", fake_hub)

    result = Path(
        model_resolver.resolve_hf(
            "org/model", "asr", "model", revision="immutable-commit"
        )
    )

    assert result.is_dir()
    assert (result / "config.json").is_file()
    assert (result / model_resolver._COMPLETE_MARKER).is_file()
    assert calls["revision"] == "immutable-commit"
    assert not list(result.parent.glob(".model.partial-*"))


def test_failed_hf_download_never_exposes_partial_directory(
    isolated_models, monkeypatch
):
    def snapshot_download(repo_id, *, revision, local_dir):
        Path(local_dir, "partial.bin").write_bytes(b"partial")
        raise RuntimeError("network interrupted")

    fake_hub = types.ModuleType("huggingface_hub")
    fake_hub.snapshot_download = snapshot_download
    monkeypatch.setitem(sys.modules, "huggingface_hub", fake_hub)

    with pytest.raises(RuntimeError, match="network interrupted"):
        model_resolver.resolve_hf(
            "org/model", "asr", "model", revision="immutable-commit"
        )

    destination = isolated_models / "asr" / "model"
    assert not destination.exists()
    assert not list(destination.parent.glob(".model.partial-*"))


def test_legacy_nonempty_hf_directory_must_contain_model_metadata(
    isolated_models,
):
    destination = isolated_models / "asr" / "model"
    destination.mkdir(parents=True)
    (destination / "partial.bin").write_bytes(b"partial")

    with pytest.raises(RuntimeError, match="model download incomplete"):
        model_resolver.resolve_hf(
            "org/model", "asr", "model", revision="immutable-commit"
        )


def test_qwen_revisions_have_immutable_defaults():
    from engine.asr_engine import QWEN_ALIGNER_REVISION, QWEN_ASR_REVISION

    assert len(QWEN_ASR_REVISION) == 40
    assert len(QWEN_ALIGNER_REVISION) == 40
    int(QWEN_ASR_REVISION, 16)
    int(QWEN_ALIGNER_REVISION, 16)


def test_torch_hub_cache_selects_only_requested_revision(tmp_path, monkeypatch):
    monkeypatch.setenv("TORCH_HOME", str(tmp_path / "torch"))
    hub = tmp_path / "torch" / "hub"
    wrong = hub / "snakers4_silero-vad_main"
    exact = hub / "snakers4_silero-vad_deadbeef"
    wrong.mkdir(parents=True)
    exact.mkdir()
    (wrong / "hubconf.py").write_text("", encoding="utf-8")
    (exact / "hubconf.py").write_text("", encoding="utf-8")

    assert model_resolver._torch_hub_vad_cache("deadbeef") == str(exact)
    assert model_resolver._torch_hub_vad_cache("missing") is None


def test_managed_local_model_rejects_revision_mismatch(isolated_models):
    destination = isolated_models / "asr" / "model"
    destination.mkdir(parents=True)
    (destination / "config.json").write_text("{}", encoding="utf-8")
    (destination / model_resolver._COMPLETE_MARKER).write_text(
        "source=huggingface:org/model@old-revision\n", encoding="utf-8"
    )

    with pytest.raises(RuntimeError, match="revision does not match"):
        model_resolver.resolve_hf(
            "org/model", "asr", "model", revision="new-revision"
        )
