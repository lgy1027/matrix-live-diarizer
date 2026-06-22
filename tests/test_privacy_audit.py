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
