"""Markdown rendering (mistune, escape=True): the spec subset + sanitization."""

from pyrepress.renderer import render_markdown


def test_headings_and_paragraphs():
    html = render_markdown("# Title\n\nSome paragraph.\n\n## Sub")
    assert "<h1>Title</h1>" in html
    assert "<h2>Sub</h2>" in html
    assert "<p>Some paragraph.</p>" in html


def test_emphasis_and_code_span():
    html = render_markdown("*it* **bold** `code`")
    assert "<em>it</em>" in html
    assert "<strong>bold</strong>" in html
    assert "<code>code</code>" in html


def test_fenced_code_block():
    html = render_markdown("```python\nprint('hi')\n```")
    assert "<pre><code" in html
    assert "print(&#x27;hi&#x27;)" in html or "print('hi')" in html


def test_links_and_images():
    html = render_markdown("[PYRE](https://example.com) ![alt](https://example.com/i.png)")
    assert '<a href="https://example.com">PYRE</a>' in html
    assert '<img src="https://example.com/i.png" alt="alt"' in html


def test_lists():
    html = render_markdown("- a\n- b\n\n1. x\n2. y")
    assert "<ul>" in html and html.count("<li>") == 4 and "<ol>" in html


def test_blockquote_and_hr():
    html = render_markdown("> quoted\n\n---")
    assert "<blockquote>" in html
    assert "<hr" in html


def test_raw_html_is_escaped_not_executed():
    html = render_markdown('hello <script>alert("xss")</script> world')
    assert "<script>" not in html
    assert "&lt;script&gt;" in html


def test_raw_block_html_is_escaped():
    html = render_markdown('<div onclick="evil()">click</div>')
    assert "<div" not in html
    assert "&lt;div" in html


def test_markdown_generated_tags_still_render():
    # escaping must hit RAW html only, not markdown-produced tags
    html = render_markdown("# H\n\n**b**")
    assert "&lt;" not in html


def test_empty_and_none_render():
    assert render_markdown("") == ""
    assert render_markdown(None) == ""
