"""移动端响应式 CSS 测试(Roadmap #1.5)

用 tinycss2 解析 web/index.html 的 <style> 块,验证:
- 768px 断点存在
- 关键 CSS 规则在 768px 断点内生效(底部 tab bar)
- 480px 极窄屏断点存在
- nav 不会被改坏(不删/不重命名)

不依赖浏览器/JS 引擎,纯静态解析。
"""
import sys
import re
import tinycss2

sys.path.insert(0, "/Users/lgy/python/github.com/lgy1027/matrix-live-diarizer")

INDEX_HTML = "/Users/lgy/python/github.com/lgy1027/matrix-live-diarizer/web/index.html"


def _extract_styles(html: str) -> str:
    """提取所有 <style> 块,合并成一段 CSS"""
    blocks = re.findall(r"<style[^>]*>(.*?)</style>", html, re.DOTALL)
    return "\n".join(blocks)


def _find_media_blocks(css_text: str) -> list[dict]:
    """解析 @media 块,返回 [{condition, rules}] 列表"""
    rules = tinycss2.parse_stylesheet(css_text, skip_comments=True, skip_whitespace=True)
    media_blocks = []
    for r in rules:
        if r.type == "at-rule" and r.lower_at_keyword == "media":
            # r.prelude 是 media query 列表
            condition = tinycss2.serialize(r.prelude).strip()
            inner_rules = []
            for inner in tinycss2.parse_rule_list(r.content, skip_comments=True, skip_whitespace=True):
                if inner.type == "qualified-rule":
                    selector = tinycss2.serialize(inner.prelude).strip()
                    body = tinycss2.serialize(inner.content).strip()
                    inner_rules.append((selector, body))
            media_blocks.append({"condition": condition, "rules": inner_rules})
    return media_blocks


def test_768_breakpoint_exists():
    """< 768px 断点必须存在"""
    html = open(INDEX_HTML).read()
    css = _extract_styles(html)
    blocks = _find_media_blocks(css)
    conditions = [b["condition"] for b in blocks]
    assert any("max-width" in c and "768" in c for c in conditions), (
        f"未找到 @media (max-width:768px) 断点,实际: {conditions}"
    )


def test_480_breakpoint_exists():
    """< 480px 极窄屏断点存在(老款手机适配)"""
    html = open(INDEX_HTML).read()
    css = _extract_styles(html)
    blocks = _find_media_blocks(css)
    conditions = [b["condition"] for b in blocks]
    assert any("max-width" in c and "480" in c for c in conditions), (
        f"未找到 @media (max-width:480px) 极窄屏断点,实际: {conditions}"
    )


def test_768_nav_becomes_bottom_tab_bar():
    """< 768px: aside.nav 改底部 tab bar(position fixed bottom)"""
    html = open(INDEX_HTML).read()
    css = _extract_styles(html)
    blocks = _find_media_blocks(css)
    target = next((b for b in blocks if "max-width" in b["condition"] and "768" in b["condition"]), None)
    assert target is not None, "768 断点缺失"

    # 找到 aside.nav 的规则
    nav_rules = [r for s, r in target["rules"] if "aside.nav" in s]
    assert nav_rules, f"768 断点里没有 aside.nav 规则"

    # 验证 position: fixed
    nav_body = " ".join(nav_rules)
    assert "position" in nav_body and "fixed" in nav_body, (
        f"aside.nav 在 768 应 position:fixed,实际: {nav_body[:200]}"
    )
    # 验证 bottom: 0
    assert "bottom" in nav_body and "0" in nav_body, (
        f"aside.nav 应 bottom:0 贴底,实际: {nav_body[:200]}"
    )
    # 验证 flex-direction: row(横向 tab bar)
    assert "row" in nav_body, f"aside.nav 应 flex-direction:row 横向排列,实际: {nav_body[:200]}"


def test_768_nav_item_shows_label():
    """< 768px: nav-item 用 ::after 显示 title 属性(让 tab bar 有文字)"""
    html = open(INDEX_HTML).read()
    css = _extract_styles(html)
    blocks = _find_media_blocks(css)
    target = next((b for b in blocks if "max-width" in b["condition"] and "768" in b["condition"]), None)

    # 找 .nav-item::after 规则
    label_rules = [r for s, r in target["rules"] if ".nav-item" in s and "::after" in s]
    assert label_rules, f"768 断点里没找到 .nav-item::after 规则"

    label_body = " ".join(label_rules)
    assert "attr(title)" in label_body, f"::after 没用 attr(title),实际: {label_body[:200]}"


def test_768_main_has_bottom_padding():
    """< 768px: main 内容应 padding-bottom 让出底部 nav 空间"""
    html = open(INDEX_HTML).read()
    css = _extract_styles(html)
    blocks = _find_media_blocks(css)
    target = next((b for b in blocks if "max-width" in b["condition"] and "768" in b["condition"]), None)

    main_rules = [r for s, r in target["rules"] if s == "main"]
    assert main_rules, f"768 断点里没 main 规则"
    main_body = " ".join(main_rules)
    assert "padding-bottom" in main_body, f"main 缺 padding-bottom,实际: {main_body[:200]}"


def test_768_hides_nav_brand():
    """< 768px: 隐藏 aside.nav 的 brand(logo 已在顶 header)"""
    html = open(INDEX_HTML).read()
    css = _extract_styles(html)
    blocks = _find_media_blocks(css)
    target = next((b for b in blocks if "max-width" in b["condition"] and "768" in b["condition"]), None)

    brand_rules = [r for s, r in target["rules"] if "brand" in s]
    assert brand_rules, f"768 断点里没处理 brand"
    assert "display:none" in " ".join(brand_rules) or "display: none" in " ".join(brand_rules), (
        f"brand 应 display:none,实际: {brand_rules}"
    )


def test_768_active_indicator_changed():
    """< 768px: active 指示器从左竖条改为顶横条"""
    html = open(INDEX_HTML).read()
    css = _extract_styles(html)
    blocks = _find_media_blocks(css)
    target = next((b for b in blocks if "max-width" in b["condition"] and "768" in b["condition"]), None)

    indicator_rules = [r for s, r in target["rules"] if "active::before" in s]
    assert indicator_rules, f"768 断点里没重写 active::before"
    body = " ".join(indicator_rules)
    # 顶横条:top: 0
    assert "top" in body, f"active 指示器应改到 top,实际: {body[:200]}"
    # 不应再有 left
    assert "left:-1" not in body or "left:50" in body, f"active 指示器没改 left,实际: {body[:200]}"


def test_existing_980_breakpoint_preserved():
    """原有 980px 断点没被破坏(已做 grid 1fr 等)"""
    html = open(INDEX_HTML).read()
    css = _extract_styles(html)
    blocks = _find_media_blocks(css)
    target = next((b for b in blocks if "max-width" in b["condition"] and "980" in b["condition"]), None)
    assert target is not None, "原有 980px 断点丢失"
    # 验证关键规则
    rules = dict(target["rules"])
    assert ".live-grid" in rules, "980 断点里 .live-grid 规则丢失"
    assert "grid-template-columns" in rules[".live-grid"], ".live-grid 应保持 grid 调整"
    assert "1fr" in rules[".live-grid"], ".live-grid 应保持 1fr 单列"


def test_no_duplicate_breakpoint_conditions():
    """不应有重复的断点条件(避免覆盖)"""
    html = open(INDEX_HTML).read()
    css = _extract_styles(html)
    blocks = _find_media_blocks(css)
    conditions = [b["condition"] for b in blocks]
    # 同条件只允许出现一次
    seen = set()
    for c in conditions:
        normalized = c.replace(" ", "")
        assert normalized not in seen, f"重复的 @media 条件: {c}"
        seen.add(normalized)
