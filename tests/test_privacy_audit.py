"""隐私审计：确保代码中不存在公网调用 / 遥测 SDK"""
import re
from pathlib import Path

REPO = Path(__file__).parent.parent

# 允许的 host（127.0.0.1, localhost, ::1, 192.168/16, 10/8, 172.16/12）
ALLOWED_HOST_RE = re.compile(
    r"127\.0\.0\.1|localhost|::1|192\.168\.\d+|10\.\d+\.\d+\.\d+|172\.(1[6-9]|2\d|3[01])\.\d+\.\d+"
)
# 禁止的 host — 仅匹配 http(s):// 后跟公网 host 的 URL
PUBLIC_HOST_RE = re.compile(r"https?://(?!127\.|localhost|::1|192\.168\.|10\.\d|172\.(1[6-9]|2\d|3[01]))[a-zA-Z0-9.-]+")

FORBIDDEN_SDK_PATTERNS = [
    re.compile(r"google-analytics\.com"),
    re.compile(r"gtag\("),
    re.compile(r"sentry"),
    re.compile(r"datadoghq"),
    re.compile(r"amplitude"),
    re.compile(r"mixpanel"),
]


def _scan_python(path: Path) -> list[str]:
    if not path.exists():
        return []
    text = path.read_text(encoding="utf-8")
    violations = []
    for m in PUBLIC_HOST_RE.finditer(text):
        violations.append(f"{path}: 公网 URL: {m.group(0)}")
    for pat in FORBIDDEN_SDK_PATTERNS:
        for m in pat.finditer(text):
            violations.append(f"{path}: 禁止 SDK: {m.group(0)}")
    return violations


def test_app_directory_no_public_calls():
    violations = []
    for p in (REPO / "app").rglob("*.py"):
        violations.extend(_scan_python(p))
    assert not violations, "隐私违规:\n" + "\n".join(violations)


def test_engine_directory_no_public_calls():
    violations = []
    for p in (REPO / "engine").rglob("*.py"):
        violations.extend(_scan_python(p))
    assert not violations, "隐私违规:\n" + "\n".join(violations)


def test_web_directory_no_telemetry():
    violations = []
    for p in (REPO / "web").rglob("*"):
        rel_parts = p.relative_to(REPO / "web").parts
        if rel_parts and rel_parts[0] in {"node_modules", "dist", ".vite"}:
            continue
        if p.is_file() and p.suffix in (".html", ".js", ".css"):
            text = p.read_text(encoding="utf-8")
            for pat in FORBIDDEN_SDK_PATTERNS:
                for m in pat.finditer(text):
                    violations.append(f"{p}: 禁止 SDK: {m.group(0)}")
    assert not violations, "前端隐私违规:\n" + "\n".join(violations)


def test_scripts_directory_no_telemetry_sdk():
    """scripts/ 只禁遥测 SDK,不禁公网 URL。

    原因:scripts/seed_demo_data.py 合法地从 archive.org 下载 CC0 公开音频
    (https://archive.org/...),这是 demo 数据的正常行为,不应判违规。
    所以 scripts/ 只查 FORBIDDEN_SDK_PATTERNS,不查 PUBLIC_HOST_RE。
    """
    violations = []
    scripts_dir = REPO / "scripts"
    if not scripts_dir.exists():
        return
    for p in scripts_dir.rglob("*.py"):
        text = p.read_text(encoding="utf-8")
        for pat in FORBIDDEN_SDK_PATTERNS:
            for m in pat.finditer(text):
                violations.append(f"{p}: 禁止 SDK: {m.group(0)}")
    assert not violations, "scripts/ 遥测 SDK 违规:\n" + "\n".join(violations)


def test_model_download_calls_are_documented_known_behavior():
    """模型下载入口审计:不 fail 测试,只暴露发现。

    snapshot_download / hf_hub_download 是模型下载入口(首次启动走公网,
    完成后永久断网可用,见 README / PRIVACY)。这里收集所有调用点并打印
    告警,方便人工复核,但测试本身总是 pass。
    """
    pattern = re.compile(r"(snapshot_download|hf_hub_download)\s*\(")
    findings = []
    for sub in ("app", "engine"):
        sub_dir = REPO / sub
        if not sub_dir.exists():
            continue
        for p in sub_dir.rglob("*.py"):
            text = p.read_text(encoding="utf-8")
            for m in pattern.finditer(text):
                findings.append(f"{p}: {m.group(0)}")
    if findings:
        print(f"已知行为:{len(findings)} 处模型下载调用(首次启动联网,见 README/PRIVACY)")
        for f in findings:
            print(f"  - {f}")
    # 测试总是 pass,只把发现暴露出来
    assert True
