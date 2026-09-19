"""Formatter regression tests: inline markdown edge cases and block styling."""

from rich.table import Table

from hazzel.formatter import (
    parse_blocks,
    render_block,
    render_inline,
    render_table,
)


# ---------------------------------------------------------------------------
# render_inline: identifiers must never be mangled by emphasis rules
# ---------------------------------------------------------------------------

def test_dunder_and_snake_case_not_italicized():
    text = render_inline("patched __init__ and my_var_name helpers")
    assert "__init__" in text.plain
    assert "my_var_name" in text.plain
    assert "init" != text.plain.split()[1]


def test_math_asterisks_not_italicized():
    text = render_inline("cost is 1*2*3 = 6 dollars")
    assert text.plain == "cost is 1*2*3 = 6 dollars"


def test_word_internal_underscores_not_italicized():
    text = render_inline("snake_case stays_snake")
    assert text.plain == "snake_case stays_snake"


def test_real_bold_and_italic_still_render():
    text = render_inline("**bold** and *ital* work")
    assert text.plain == "bold and ital work"
    styles = {span.style for span in text.spans}
    assert any("bold" in str(style) for style in styles)
    assert any("italic" in str(style) for style in styles)


def test_dunder_marked_word_not_bold():
    text = render_inline("the __init__ method")
    assert text.plain == "the __init__ method"
    assert text.spans == []


def test_backtick_code_protects_identifiers():
    text = render_inline("call `my_var_name` here")
    assert text.plain == "call my_var_name here"
    assert text.spans  # styled as inline code


# ---------------------------------------------------------------------------
# Color roles: one fixed role per color, unified palette
# ---------------------------------------------------------------------------

def test_bold_prose_uses_stress_color():
    text = render_inline("**main words** stand out")
    span = text.spans[0]
    assert text.plain[span.start : span.end] == "main words"
    assert str(span.style) == "bold #ffb454"  # STRESS — light orange


def test_links_and_mentions_share_the_cool_color():
    link = render_inline("[docs](https://example.com)")
    mention = render_inline("@src/hazzel/ui.py")
    styles = {str(s.style) for s in link.spans} | {str(s.style) for s in mention.spans}
    assert "underline #8ab4f8" in styles  # link text
    assert "bold #8ab4f8" in styles  # mention
    # The cool color appears in both — pointers, and only pointers


def test_neutrals_get_no_color():
    plain = render_inline("*soft* ~~gone~~ text")
    styles = {str(s.style) for s in plain.spans}
    assert "italic" in styles and "strike" in styles
    assert not any("#" in style for style in styles if style not in ("italic", "strike"))


def test_accent_is_reserved_for_structure():
    blocks = parse_blocks("# Section\n\n- bullet item\n")
    h1 = render_block(blocks[0])
    bullet = render_block(blocks[1])
    h1_styles = {str(s.style) for s in h1.spans}
    bullet_styles = {str(s.style) for s in bullet.spans}
    assert "bold #ec8500" in h1_styles  # heading marker + text: structure
    assert "bold #ec8500" in bullet_styles  # bullet marker: structure
    # The stress tint must not leak into structure elements
    assert "bold #ffb454" not in h1_styles
    assert "bold #ffb454" not in bullet_styles


def test_palette_is_small():
    import re

    from hazzel import formatter

    source_colors = {
        formatter.ACCENT,
        formatter.STRESS,
        formatter.COOL,
    }
    # Three text colors outside syntax highlighting: brand orange, its
    # lighter stress tint, and one cool contrast. Inline code and task
    # checks keep their existing dedicated tints.
    assert len(source_colors) == 3
    for color in source_colors:
        assert re.fullmatch(r"#[0-9a-f]{6}", color)


# ---------------------------------------------------------------------------
# Tables: tight columns, padded edges
# ---------------------------------------------------------------------------

def test_table_columns_hug_content():
    from rich.console import Console
    from rich.measure import Measurement

    headers = ["Provider", "Context"]
    rows = [["Groq", "128k"]]
    table = render_table(headers, rows)
    assert isinstance(table, Table)
    for col in table.columns:
        # No forced 20-char floor: columns size to content at render time
        assert col.min_width is None or col.min_width <= 1
        assert col.width is None  # not pinned; Rich measures on render
        assert col.max_width is None or col.max_width >= len("Provider")

    # Natural render width stays close to content: "128k" must not be
    # stretched to a 20-char column.
    console = Console(width=100, no_color=True, force_terminal=False)
    measured = Measurement.get(console, console.options, table).maximum
    assert measured <= 32  # hug: ~22 vs the old ~35 with min_width=20


def test_table_pad_edge_is_on():
    headers, rows = ["A", "B"], [["1", "2"]]
    table = render_table(headers, rows)
    assert table.pad_edge is True


# ---------------------------------------------------------------------------
# Blocks: parsing and structure
# ---------------------------------------------------------------------------

def test_parse_blocks_kinds():
    blocks = parse_blocks(
        "# Title\n\nParagraph.\n\n- item\n\n```python\nx = 1\n```\n\n> quoted\n"
    )
    kinds = [block.kind for block in blocks]
    assert kinds == ["heading", "paragraph", "list", "code", "blockquote"]


def test_code_block_text_language_still_parses():
    blocks = parse_blocks("```\nplain code\n```\n")
    code_block = blocks[0].content
    assert code_block.language == ""
    assert code_block.code == "plain code"
