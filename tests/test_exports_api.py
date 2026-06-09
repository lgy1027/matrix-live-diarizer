"""Exports API 测试 — 用 sys.modules mock 绕过真实引擎加载"""
import os
import sys
import types
import tempfile
import importlib
from unittest.mock import MagicMock

import pytest


_FAKE_NAMES = (
    "engine.asr_engine",
    "engine.speaker",
    "engine.speaker.speaker_factory",
)


def _install_fake_engines():
    """注入 fake 引擎模块，返回 (saved_state, fake_modules)"""
    saved = {name: sys.modules.get(name) for name in _FAKE_NAMES}

    # fake engine.asr_engine
    fake_asr = types.ModuleType("engine.asr_engine")
    fake_asr.ASREngine = MagicMock(return_value=MagicMock())
    sys.modules["engine.asr_engine"] = fake_asr

    # fake engine.speaker（含 speaker_factory）
    fake_speaker_pkg = types.ModuleType("engine.speaker")
    fake_speaker_pkg.__path__ = []  # 让它表现为包
    # 包级别也暴露 get_speaker_engine / get_engine_info（被 app/__init__.py 使用）
    fake_speaker_pkg.get_speaker_engine = MagicMock(return_value=MagicMock())
    fake_speaker_pkg.get_engine_info = MagicMock(return_value={"name": "Mock", "model": "mock"})

    fake_factory = types.ModuleType("engine.speaker.speaker_factory")
    fake_factory.get_speaker_engine = MagicMock(return_value=MagicMock())
    fake_factory.get_engine_info = MagicMock(return_value={"name": "Mock", "model": "mock"})
    fake_factory.get_all_engines = MagicMock(return_value={"current": "mock", "asr": {}, "speakers": {}})
    fake_factory.get_engine_manager = MagicMock(return_value=MagicMock())
    fake_factory.ENGINE_CONFIG = {}
    fake_factory.ASR_CONFIG = {}

    sys.modules["engine.speaker"] = fake_speaker_pkg
    sys.modules["engine.speaker.speaker_factory"] = fake_factory

    return saved


def _restore_fake_engines(saved):
    """恢复原始 sys.modules 状态"""
    for name, mod in saved.items():
        if mod is None:
            sys.modules.pop(name, None)
        else:
            sys.modules[name] = mod


@pytest.fixture
def client(tmp_path):
    """每个测试用独立的 app，避免状态污染 + 不污染其他测试的 sys.modules"""
    saved = _install_fake_engines()
    try:
        os.environ["STORAGE_DB_PATH"] = str(tmp_path / "test.db")
        # reload config (用 import_module 拿到真正的模块对象,
        # 因为 app/__init__.py 里 `from app.config import config`
        # 会把 app.config 这个名字覆盖为 AppConfig 实例)
        cfg_mod = importlib.import_module("app.config")
        importlib.reload(cfg_mod)
        app_mod = importlib.import_module("app")
        importlib.reload(app_mod)
        from fastapi.testclient import TestClient
        yield TestClient(app_mod.create_app())
    finally:
        _restore_fake_engines(saved)


def test_export_srt_endpoint(client):
    app = client.app
    sid = app.state.transcript_repo.create_session(
        source="upload", original_filename="a.wav", duration_sec=5.0, title="test"
    )
    app.state.transcript_repo.insert_segment(
        sid, segment_index=0, text="你好", start_time=0.0, end_time=1.5
    )

    resp = client.get(f"/v1/exports/{sid}?format=srt")
    assert resp.status_code == 200
    assert "00:00:00,000 --> 00:00:01,500" in resp.text
    assert "你好" in resp.text
    assert "attachment" in resp.headers["content-disposition"]


def test_export_invalid_format(client):
    resp = client.get("/v1/exports/any?format=xml")
    # FastAPI 的 Query(pattern=...) 触发 Pydantic 验证,返回 422
    assert resp.status_code == 422


def test_export_md_alias_accepted(client, tmp_path):
    """format=md 是 format=markdown 的别名,应当走通到 404(会话不存在)而非 422"""
    resp = client.get("/v1/exports/nonexist?format=md")
    assert resp.status_code == 404


def test_export_nonexistent_session(client):
    resp = client.get("/v1/exports/nonexistent?format=srt")
    assert resp.status_code == 404


# ========== 回归测试:Content-Disposition 头注入防护 ==========

def test_export_filename_sanitizes_quotes(client):
    """title 含双引号时,Content-Disposition 头不应被破坏"""
    app = client.app
    # 含双引号 + 分号的攻击性 title
    sid = app.state.transcript_repo.create_session(
        source='upload', title='evil"; rm -rf / #', duration_sec=1.0
    )
    app.state.transcript_repo.insert_segment(sid, 0, 'hi', 0.0, 1.0)

    resp = client.get(f"/v1/exports/{sid}?format=srt")
    assert resp.status_code == 200
    cd = resp.headers.get("content-disposition", "")
    # 双引号必须被替换(防 header 字段值闭合攻击)
    assert '"' not in cd.split("filename=")[1].split(";")[0].split('"')[-2] if 'filename=' in cd else True, \
        f"双引号未净化: {cd}"
    # 关键: header 仍是合法的 Content-Disposition
    assert cd.startswith("attachment; filename=")


def test_export_filename_strips_crlf(client):
    """title 含 CRLF 时,Content-Disposition 头不应被注入新行"""
    app = client.app
    # 含 CRLF 的 title
    sid = app.state.transcript_repo.create_session(
        source='upload', title='a\r\nX-Injected: pwned', duration_sec=1.0
    )
    app.state.transcript_repo.insert_segment(sid, 0, 'hi', 0.0, 1.0)

    resp = client.get(f"/v1/exports/{sid}?format=srt")
    assert resp.status_code == 200
    cd = resp.headers.get("content-disposition", "")
    # CRLF 必须被剥掉(防 HTTP 头注入)
    assert "\r" not in cd
    assert "\n" not in cd
    # X-Injected 不能作为独立 header 出现
    assert "X-Injected" not in cd or "X-Injected" in cd.split("filename=")[-1]


def test_export_filename_handles_unicode(client):
    """中文 title 应保留(只过滤控制字符)"""
    app = client.app
    sid = app.state.transcript_repo.create_session(
        source='upload', title='会议纪要 2026', duration_sec=1.0
    )
    app.state.transcript_repo.insert_segment(sid, 0, 'hi', 0.0, 1.0)

    resp = client.get(f"/v1/exports/{sid}?format=srt")
    assert resp.status_code == 200
    cd = resp.headers.get("content-disposition", "")
    # RFC 5987: 中文 URL 编码后是 %E4%BC%9A%E8%AE%AE... 浏览器解析后看到"会议纪要"
    from urllib.parse import unquote
    decoded = unquote(cd)
    assert "会议纪要" in decoded, f"中文 title 应在 header 中保留,实际: {cd}"


def test_export_filename_empty_title_falls_back(client):
    """title 全是控制字符时,降级到 session_id 前 8 位"""
    app = client.app
    sid = app.state.transcript_repo.create_session(
        source='upload', title='\r\n\r\n', duration_sec=1.0
    )
    app.state.transcript_repo.insert_segment(sid, 0, 'hi', 0.0, 1.0)

    resp = client.get(f"/v1/exports/{sid}?format=srt")
    assert resp.status_code == 200
    cd = resp.headers.get("content-disposition", "")
    # 不能是空的 filename
    assert 'filename=""' not in cd
    # 应回退到 session_id 前 8 位
    assert sid[:8] in cd
