from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_native_selects_have_dark_popup_and_explicit_text_colors():
    base_css = (ROOT / "web/src/styles/base.css").read_text(encoding="utf-8")
    detail = (ROOT / "web/src/views/MeetingDetailView.vue").read_text(encoding="utf-8")

    assert "color-scheme: dark" in base_css
    assert "select option," in base_css
    assert "background-color: var(--ink-2)" in base_css
    assert ".speaker-confirm select,.batch select" in detail
    assert "background:var(--ink-3);color:var(--text)" in detail
