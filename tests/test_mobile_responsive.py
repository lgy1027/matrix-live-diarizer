"""移动端响应式 CSS 测试。

当前前端是 Vue/Vite，响应式规则位于 web/src/styles/studio.css。
"""
from pathlib import Path

import tinycss2


REPO_ROOT = Path(__file__).resolve().parents[1]
STUDIO_CSS = REPO_ROOT / "web" / "src" / "styles" / "studio.css"
APP_NAV = REPO_ROOT / "web" / "src" / "components" / "AppNav.vue"


def _load_css() -> str:
    return STUDIO_CSS.read_text(encoding="utf-8")


def _find_media_blocks(css_text: str) -> list[dict]:
    """解析 @media 块，返回 [{condition, rules}] 列表。"""
    rules = tinycss2.parse_stylesheet(css_text, skip_comments=True, skip_whitespace=True)
    media_blocks = []
    for rule in rules:
        if rule.type != "at-rule" or rule.lower_at_keyword != "media":
            continue
        condition = tinycss2.serialize(rule.prelude).strip()
        inner_rules = []
        for inner in tinycss2.parse_rule_list(rule.content, skip_comments=True, skip_whitespace=True):
            if inner.type == "qualified-rule":
                selector = tinycss2.serialize(inner.prelude).strip()
                body = tinycss2.serialize(inner.content).strip()
                inner_rules.append((selector, body))
        media_blocks.append({"condition": condition, "rules": inner_rules})
    return media_blocks


def _media_block(width: int) -> dict:
    blocks = _find_media_blocks(_load_css())
    target = next(
        (b for b in blocks if "max-width" in b["condition"] and str(width) in b["condition"]),
        None,
    )
    assert target is not None, f"未找到 @media (max-width:{width}px) 断点"
    return target


def test_768_breakpoint_exists():
    _media_block(768)


def test_480_breakpoint_exists():
    _media_block(480)


def test_768_nav_becomes_bottom_tab_bar():
    target = _media_block(768)
    nav_rules = [r for s, r in target["rules"] if "aside.nav" in s]
    assert nav_rules, "768 断点里没有 aside.nav 规则"

    nav_body = " ".join(nav_rules)
    assert "position" in nav_body and "fixed" in nav_body
    assert "bottom" in nav_body and "0" in nav_body
    assert "row" in nav_body


def test_768_nav_item_shows_label():
    target = _media_block(768)
    label_rules = [r for s, r in target["rules"] if ".nav-item" in s and "::after" in s]
    assert label_rules, "768 断点里没找到 .nav-item::after 规则"
    assert "attr(title)" in " ".join(label_rules)

    nav_component = APP_NAV.read_text(encoding="utf-8")
    assert ':title="it.label"' in nav_component


def test_768_main_has_bottom_padding():
    target = _media_block(768)
    main_rules = [r for s, r in target["rules"] if s == "main"]
    assert main_rules, "768 断点里没 main 规则"
    assert "padding-bottom" in " ".join(main_rules)


def test_768_hides_nav_brand():
    target = _media_block(768)
    brand_rules = [r for s, r in target["rules"] if "brand" in s]
    assert brand_rules, "768 断点里没处理 brand"
    assert "display:none" in " ".join(brand_rules).replace(" ", "")


def test_768_active_indicator_changed():
    target = _media_block(768)
    indicator_rules = [r for s, r in target["rules"] if "active::before" in s]
    assert indicator_rules, "768 断点里没重写 active::before"
    body = " ".join(indicator_rules)
    assert "top" in body
    assert "left:-1" not in body


def test_existing_980_breakpoint_preserved():
    target = _media_block(980)
    rules = dict(target["rules"])
    assert ".live-grid" in rules
    assert "grid-template-columns" in rules[".live-grid"]
    assert "1fr" in rules[".live-grid"]


def test_no_duplicate_breakpoint_conditions():
    blocks = _find_media_blocks(_load_css())
    seen = set()
    for block in blocks:
        normalized = block["condition"].replace(" ", "")
        assert normalized not in seen, f"重复的 @media 条件: {block['condition']}"
        seen.add(normalized)


def test_studio_css_does_not_contain_legacy_html():
    css = _load_css()
    assert "</style>" not in css
    assert "<body" not in css
