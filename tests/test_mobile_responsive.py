"""移动端规则必须存在于实际打包的 Vue/CSS 源码中。"""
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _source(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_mobile_navigation_is_bundled_with_component() -> None:
    source = _source("web/src/components/AppNav.vue")
    assert "@media (max-width: 700px)" in source
    assert "position: fixed" in source
    assert "flex-direction: row" in source
    assert "content: attr(aria-label)" in source
    assert ':aria-label="t(it.labelKey)"' in source


def test_mobile_content_reserves_bottom_navigation_space() -> None:
    source = _source("web/src/App.vue")
    assert "grid-template-columns: 1fr" in source
    assert "padding-bottom: 58px" in source
    assert "height: calc(100vh - 58px)" in source


def test_legacy_stylesheet_is_removed() -> None:
    assert not (ROOT / "web/src/styles/studio.css").exists()
