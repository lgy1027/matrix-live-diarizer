"""Smoke test — 验证服务能完整启动并响应核心端点

用真实 uvicorn + httpx,避免 mock 掩盖了真实的初始化失败。
给 CI 一个"服务能不能跑起来"的快速信心。

CI 跑法: pytest tests/test_smoke_boot.py -v
预期耗时: 30-90s (首次 ASR 模型加载)
"""
import os
import sys
import threading
import time
import socket
import tempfile

import pytest
import httpx


if os.environ.get("MATRIX_TEST_REAL_DEPENDENCIES") != "1":
    pytest.skip(
        "set MATRIX_TEST_REAL_DEPENDENCIES=1 to load real model dependencies",
        allow_module_level=True,
    )


def _find_free_port() -> int:
    """找一个空闲端口,避免与其他测试冲突"""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture(scope="module")
def server_url():
    """启动真实 uvicorn server,模块级 fixture 复用"""
    # 用临时 DB 避免污染真实数据
    tmp = tempfile.mkdtemp()
    os.environ["STORAGE_DB_PATH"] = os.path.join(tmp, "smoke.db")

    # 准备 sys.path 以便从仓库根目录 import
    repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    if repo_root not in sys.path:
        sys.path.insert(0, repo_root)

    # 重置可能已被污染的 sys.modules
    for mod_name in list(sys.modules.keys()):
        if mod_name.startswith("engine.") or mod_name.startswith("app."):
            if "matrix-live-diarizer" not in (
                getattr(sys.modules[mod_name], "__file__", "") or ""
            ):
                del sys.modules[mod_name]

    import uvicorn
    from app import create_app

    app = create_app()
    port = _find_free_port()
    config = uvicorn.Config(
        app=app, host="127.0.0.1", port=port, log_level="warning"
    )
    server = uvicorn.Server(config)

    # 启动 server 在后台线程
    server_thread = threading.Thread(target=server.run, daemon=True)
    server_thread.start()

    # 等服务 ready,最长 90s (ASR 加载)
    base_url = f"http://127.0.0.1:{port}"
    deadline = time.time() + 90
    last_error = None
    while time.time() < deadline:
        try:
            r = httpx.get(f"{base_url}/ready", timeout=2)
            if r.status_code == 200:
                yield base_url
                # 关闭 server
                server.should_exit = True
                server_thread.join(timeout=5)
                return
        except Exception as e:
            last_error = e
        time.sleep(1)

    # 超时
    server.should_exit = True
    server_thread.join(timeout=5)
    pytest.fail(f"服务启动超时 (90s): {last_error}")


@pytest.mark.timeout(120)
def test_health_endpoint(server_url):
    """/health 应返回 200"""
    r = httpx.get(f"{server_url}/health", timeout=5)
    assert r.status_code == 200
    data = r.json()
    assert "status" in data


@pytest.mark.timeout(120)
def test_ready_endpoint(server_url):
    """/ready 应返回 200 (ASR + Speaker 都 loaded)"""
    r = httpx.get(f"{server_url}/ready", timeout=5)
    assert r.status_code == 200
    data = r.json()
    assert data["asr"] is True, f"ASR 未就绪: {data}"
    assert data["speaker"] is True, f"Speaker 引擎未就绪: {data}"


@pytest.mark.timeout(120)
def test_engines_endpoint(server_url):
    """/v1/engines 应返回所有引擎信息"""
    r = httpx.get(f"{server_url}/v1/engines", timeout=5)
    assert r.status_code == 200
    data = r.json()
    assert "current" in data
    assert "engines" in data
    # 至少有一个引擎
    assert len(data["engines"]) >= 1


@pytest.mark.timeout(120)
def test_people_endpoint(server_url):
    """The product identity API is /v1/people, not the legacy speaker library."""
    r = httpx.get(f"{server_url}/v1/people", timeout=5)
    assert r.status_code == 200
    data = r.json()
    assert "items" in data
    assert "total" in data
    assert isinstance(data["items"], list)


@pytest.mark.timeout(120)
def test_llm_status_endpoint(server_url):
    """/v1/llm/status 应返回 LLM 启用状态"""
    r = httpx.get(f"{server_url}/v1/llm/status", timeout=5)
    assert r.status_code == 200
    data = r.json()
    # 必填字段
    for k in ("enabled", "available", "mock"):
        assert k in data, f"缺少字段 {k}"


@pytest.mark.timeout(120)
def test_spa_homepage_mounted(server_url):
    """/ 应返回 Vue SPA 首页"""
    r = httpx.get(f"{server_url}/", timeout=5)
    assert r.status_code == 200
    assert "html" in r.text.lower(), "返回的不是 HTML"


@pytest.mark.timeout(120)
def test_unknown_route_returns_404(server_url):
    """未知路径应返回 404 而非 500"""
    r = httpx.get(f"{server_url}/v1/nonexistent", timeout=5)
    assert r.status_code == 404
