"""声纹实时聚类存储策略回归测试。"""

from pathlib import Path

from engine.speaker.speaker_factory import (
    ENGINE_CONFIG,
    embedding_model_id,
    resolve_embedding_model_id,
)
from app.repositories.database import Database
from app.repositories.people import PeopleRepository
from app.config import SpeakerConfig


ROOT = Path(__file__).resolve().parents[1]
ENGINE_FILES = (
    ROOT / "engine" / "speaker" / "campplus_engine.py",
    ROOT / "engine" / "speaker" / "eres2net_engine.py",
    ROOT / "engine" / "speaker" / "wespeaker_engine.py",
)


def test_live_speaker_engines_use_process_local_chroma() -> None:
    """匿名实时聚类不得写入跨进程、跨版本的 Chroma 数据库。"""
    for engine_file in ENGINE_FILES:
        source = engine_file.read_text(encoding="utf-8")
        assert "EphemeralClient" in source, engine_file.name
        assert "PersistentClient" not in source, engine_file.name


def test_chroma_telemetry_dependency_is_compatible() -> None:
    requirements = (ROOT / "requirements.txt").read_text(encoding="utf-8")
    assert "chromadb>=0.6.3,<0.7.0" in requirements
    assert "posthog>=2.4.0,<3.0.0" in requirements


def test_embedding_model_id_captures_full_compatibility_contract() -> None:
    model_id = embedding_model_id("campplus")
    assert "speech_campplus_sv_zh-cn_16k-common" in model_id
    assert f"revision={ENGINE_CONFIG['campplus']['model_revision']}" in model_id
    assert "revision=master" not in model_id
    assert "dim=192" in model_id
    assert "normalization=l2" in model_id


def test_legacy_model_name_is_resolved_only_at_compatible_dimension() -> None:
    assert resolve_embedding_model_id("CamPlus", 192) == embedding_model_id("campplus")
    assert resolve_embedding_model_id("CamPlus", 256) is None
    assert resolve_embedding_model_id(embedding_model_id("campplus"), 256) is None


def test_repository_never_returns_same_dimension_from_another_model(tmp_path) -> None:
    db = Database(str(tmp_path / "speaker.db"))
    db.init_schema()
    people = PeopleRepository(db)
    alice = people.create("Alice")
    bob = people.create("Bob")
    vector = bytes(192 * 4)
    people.add_sample(
        alice,
        audio_path=str(tmp_path / "alice.wav"),
        duration_sec=3.0,
        embedding=vector,
        embedding_dim=192,
        model_name="CamPlus",
    )
    people.add_sample(
        bob,
        audio_path=str(tmp_path / "bob.wav"),
        duration_sec=3.0,
        embedding=vector,
        embedding_dim=192,
        model_name="ERes2NetV2",
    )

    matches = people.matching_samples("CamPlus", 192)

    assert [item["person_id"] for item in matches] == [alice]
    assert matches[0]["model_id"] == embedding_model_id("campplus")


def test_each_engine_has_an_independent_identity_match_policy(monkeypatch) -> None:
    monkeypatch.setenv("PERSON_MATCH_THRESHOLD_CAMPPLUS", "0.81")
    monkeypatch.setenv("PERSON_MATCH_MARGIN_CAMPPLUS", "0.05")
    monkeypatch.setenv("PERSON_MATCH_THRESHOLD_ERES2NET", "0.75")
    monkeypatch.setenv("PERSON_MATCH_MARGIN_ERES2NET", "0.02")
    monkeypatch.setenv("PERSON_AUTO_MATCH_THRESHOLD_CAMPPLUS", "0.90")
    monkeypatch.setenv("PERSON_AUTO_MATCH_MARGIN_CAMPPLUS", "0.09")
    monkeypatch.setenv("PERSON_AUTO_MATCH_THRESHOLD_ERES2NET", "0.70")
    monkeypatch.setenv("PERSON_AUTO_MATCH_MARGIN_ERES2NET", "0.01")
    settings = SpeakerConfig.from_env()

    assert settings.person_match_policy("CamPlus") == (0.81, 0.05)
    assert settings.person_match_policy("ERes2NetV2") == (0.75, 0.02)
    assert settings.person_auto_match_policy("CamPlus") == (0.90, 0.09)
    assert settings.person_auto_match_policy("ERes2NetV2") == (0.75, 0.02)
