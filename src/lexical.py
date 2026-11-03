"""Convert Payload Lexical JSON (and embedded raw HTML) into markdown."""

from __future__ import annotations

import html as html_lib
import re
from collections import Counter
from collections.abc import Iterable
from html.parser import HTMLParser
from typing import Any

# Lexical text.format bitmask (Payload / Lexical convention).
# Real BenBot cache only had format=0; bits kept as documented in BENBOT-2.
FORMAT_BOLD = 1
FORMAT_ITALIC = 2
FORMAT_STRIKETHROUGH = 4
FORMAT_UNDERLINE = 8
FORMAT_CODE = 16

KNOWN_NODE_TYPES = frozenset(
    {
        "root",
        "paragraph",
        "quote",
        "text",
        "link",
        "upload",
        "heading",
        "list",
        "listitem",
        "code",
        "linebreak",
        "horizontalrule",
        "table",
        "tablerow",
        "tablecell",
        "tableheader",
        "raw-html",
    }
)


def lexical_to_markdown(
    root: dict[str, Any],
    *,
    stats: Counter[str] | None = None,
) -> str:
    """Render a Lexical root node as markdown.

    Pure: no file or network access. Optional ``stats`` accumulates node type counts.
    """
    if not isinstance(root, dict):
        return ""
    _record(stats, root.get("type") if isinstance(root.get("type"), str) else "root")
    blocks = _render_block_children(root.get("children") or [], stats)
    return _join_blocks(blocks).strip()


def is_known_node_type(node_type: str) -> bool:
    """Return True when the converter has a dedicated handler for node_type."""
    return node_type in KNOWN_NODE_TYPES


def _record(stats: Counter[str] | None, node_type: str | None) -> None:
    if stats is not None and node_type:
        stats[node_type] += 1


def _join_blocks(blocks: Iterable[str]) -> str:
    parts = [b.strip("\n") for b in blocks if b and b.strip()]
    return "\n\n".join(parts)


def _render_block_children(
    children: list[Any],
    stats: Counter[str] | None,
) -> list[str]:
    blocks: list[str] = []
    for child in children:
        if isinstance(child, dict):
            blocks.extend(_render_block(child, stats))
    return blocks


def _render_block(node: dict[str, Any], stats: Counter[str] | None) -> list[str]:
    node_type = node.get("type")
    _record(stats, node_type if isinstance(node_type, str) else None)

    if node_type == "paragraph":
        text = _render_inline_children(node.get("children") or [], stats).strip()
        return [text] if text else []

    if node_type == "quote":
        inner = _render_inline_children(node.get("children") or [], stats).strip()
        if not inner:
            return []
        lines = inner.splitlines() or [inner]
        return ["\n".join(f"> {line}" if line else ">" for line in lines)]

    if node_type == "heading":
        level = _heading_level(node)
        text = _render_inline_children(node.get("children") or [], stats).strip()
        if not text:
            return []
        return [f"{'#' * level} {text}"]

    if node_type == "list":
        return [_render_list(node, stats)]

    if node_type == "listitem":
        # Orphan listitem treated as a paragraph-like block.
        text = _render_inline_children(node.get("children") or [], stats).strip()
        return [text] if text else []

    if node_type == "code":
        return [_render_code_block(node, stats)]

    if node_type == "horizontalrule":
        return ["---"]

    if node_type == "linebreak":
        return []

    if node_type == "upload":
        caption = _upload_caption(node)
        return [f"*{caption}*"] if caption else []

    if node_type == "raw-html":
        html = node.get("html")
        if not isinstance(html, str) or not html.strip():
            return []
        return [html_to_markdown(html)]

    if node_type in {"table", "tablerow", "tablecell", "tableheader"}:
        # Minimal table support: flatten cell text into lines.
        text = _render_inline_children(node.get("children") or [], stats).strip()
        if node_type == "table":
            rows = _render_block_children(node.get("children") or [], stats)
            return [_join_blocks(rows)] if rows else ([] if not text else [text])
        return (
            [text]
            if text
            else _render_block_children(node.get("children") or [], stats)
        )

    if node_type == "root":
        return _render_block_children(node.get("children") or [], stats)

    # Unknown: never crash; recurse into children when present.
    return _render_block_children(node.get("children") or [], stats)


def _heading_level(node: dict[str, Any]) -> int:
    tag = node.get("tag") or node.get("tagName") or ""
    if isinstance(tag, str):
        match = re.fullmatch(r"h([1-6])", tag, flags=re.IGNORECASE)
        if match:
            return int(match.group(1))
    level = node.get("level")
    if isinstance(level, int) and 1 <= level <= 6:
        return level
    return 2


def _render_list(node: dict[str, Any], stats: Counter[str] | None) -> str:
    ordered = _list_is_ordered(node)
    lines: list[str] = []
    index = 1
    for child in node.get("children") or []:
        if not isinstance(child, dict):
            continue
        if child.get("type") != "listitem":
            lines.extend(_render_block(child, stats))
            continue
        _record(stats, "listitem")
        text = _render_listitem_text(child, stats).strip()
        if not text:
            continue
        value = child.get("value")
        if ordered:
            number = value if isinstance(value, int) else index
            prefix = f"{number}."
            index = number + 1
        else:
            prefix = "-"
        first, *rest = text.splitlines() or [text]
        lines.append(f"{prefix} {first}")
        indent = " " * (len(prefix) + 1)
        for line in rest:
            lines.append(f"{indent}{line}" if line else "")
    return "\n".join(lines)


def _list_is_ordered(node: dict[str, Any]) -> bool:
    list_type = node.get("listType") or node.get("tag") or ""
    if isinstance(list_type, str):
        lowered = list_type.lower()
        return lowered in {"number", "numbered", "ol", "ordered"}
    return False


def _render_listitem_text(node: dict[str, Any], stats: Counter[str] | None) -> str:
    """Render a list item, allowing nested lists as additional lines."""
    parts: list[str] = []
    inline_buf: list[str] = []

    def flush_inline() -> None:
        if inline_buf:
            parts.append("".join(inline_buf).strip())
            inline_buf.clear()

    for child in node.get("children") or []:
        if not isinstance(child, dict):
            continue
        if child.get("type") == "list":
            flush_inline()
            _record(stats, "list")
            nested = _render_list(child, stats)
            if nested:
                # Indent nested list under the parent item.
                indented = "\n".join(
                    f"  {line}" if line else "" for line in nested.splitlines()
                )
                parts.append(indented)
        elif child.get("type") in {
            "paragraph",
            "quote",
            "heading",
            "code",
            "upload",
            "raw-html",
        }:
            flush_inline()
            parts.extend(_render_block(child, stats))
        else:
            inline_buf.append(_render_inline(child, stats))
    flush_inline()
    return "\n".join(p for p in parts if p)


def _render_code_block(node: dict[str, Any], stats: Counter[str] | None) -> str:
    language = node.get("language") or node.get("lang") or ""
    if not isinstance(language, str):
        language = ""
    body = _render_code_children(node.get("children") or [], stats)
    fence = f"```{language}".rstrip()
    return f"{fence}\n{body}\n```"


def _render_code_children(children: list[Any], stats: Counter[str] | None) -> str:
    parts: list[str] = []
    for child in children:
        if not isinstance(child, dict):
            continue
        node_type = child.get("type")
        _record(stats, node_type if isinstance(node_type, str) else None)
        if node_type == "linebreak":
            parts.append("\n")
        elif node_type == "text":
            parts.append(str(child.get("text") or ""))
        else:
            parts.append(_render_inline(child, stats))
    return "".join(parts).strip("\n")


def _upload_caption(node: dict[str, Any]) -> str | None:
    value = node.get("value")
    if not isinstance(value, dict):
        return None
    caption = value.get("caption")
    if isinstance(caption, str):
        caption = caption.strip()
        return caption or None
    return None


def _render_inline_children(children: list[Any], stats: Counter[str] | None) -> str:
    return "".join(
        _render_inline(child, stats) for child in children if isinstance(child, dict)
    )


def _render_inline(node: dict[str, Any], stats: Counter[str] | None) -> str:
    node_type = node.get("type")
    # Avoid double-counting when called from block handlers that already recorded.
    # Callers for unknown nests should record before calling; for inline children
    # from paragraph/etc we record here once.
    if node_type == "text":
        _record(stats, "text")
        return _format_text(str(node.get("text") or ""), node.get("format", 0))

    if node_type == "link":
        _record(stats, "link")
        label = _render_inline_children(node.get("children") or [], stats).strip()
        fields = node.get("fields") if isinstance(node.get("fields"), dict) else {}
        url = fields.get("url") if isinstance(fields, dict) else None
        return _markdown_link(label, url if isinstance(url, str) else None)

    if node_type == "linebreak":
        _record(stats, "linebreak")
        return "\n"

    if node_type in {
        "paragraph",
        "quote",
        "heading",
        "list",
        "code",
        "upload",
        "raw-html",
    }:
        # Block node nested where inline was expected.
        return _join_blocks(_render_block(node, stats))

    _record(stats, node_type if isinstance(node_type, str) else None)
    return _render_inline_children(node.get("children") or [], stats)


def _is_media_url(url: str) -> bool:
    """Return True for storage/CDN or direct file URLs to omit from output."""
    lowered = url.strip().lower()
    if not lowered:
        return False
    if "digitaloceanspaces.com" in lowered:
        return True
    return bool(
        re.search(
            r"\.(?:jpe?g|png|gif|webp|svg|mp4|webm|mp3|wav|pdf)(?:\?|#|$)", lowered
        )
    )


def _markdown_link(label: str, url: str | None) -> str:
    """Render a markdown link, dropping empty labels and media URLs."""
    label = label.strip()
    if not label:
        return ""
    if isinstance(url, str) and url.strip() and not _is_media_url(url):
        return f"[{label}]({url.strip()})"
    return label


def _format_text(text: str, fmt: Any) -> str:
    if not text:
        return ""
    try:
        mask = int(fmt)
    except (TypeError, ValueError):
        mask = 0

    out = text
    # Code innermost, then strike, bold, italic. Underline has no md form.
    if mask & FORMAT_CODE:
        out = f"`{out}`"
    if mask & FORMAT_STRIKETHROUGH:
        out = f"~~{out}~~"
    if mask & FORMAT_BOLD:
        out = f"**{out}**"
    if mask & FORMAT_ITALIC:
        out = f"*{out}*"
    return out


# --- HTML (raw-html nodes) -------------------------------------------------


def html_to_markdown(html: str) -> str:
    """Convert an HTML fragment to markdown using only the standard library."""
    parser = _HTMLToMarkdown()
    parser.feed(html)
    parser.close()
    return parser.output().strip()


class _HTMLToMarkdown(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._blocks: list[str] = []
        self._inline: list[str] = []
        self._link_href: list[str | None] = []
        self._list_stack: list[str] = []  # "ul" | "ol"
        self._list_index: list[int] = []
        self._list_items: list[list[str]] = []
        self._in_pre = False
        self._in_code = False
        self._in_blockquote = 0
        self._ignore_depth = 0
        self._heading: int | None = None
        self._in_figcaption = False
        self._pending_li = False

    def output(self) -> str:
        self._flush_inline_as_block()
        self._flush_list_items()
        return _join_blocks(self._blocks)

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag = tag.lower()
        attr = {k.lower(): (v or "") for k, v in attrs}

        if tag in {
            "script",
            "style",
            "svg",
            "iframe",
            "video",
            "audio",
            "source",
            "button",
        }:
            self._ignore_depth += 1
            return
        if self._ignore_depth:
            return

        if tag == "br":
            self._inline.append("\n")
        elif tag == "hr":
            self._flush_inline_as_block()
            self._blocks.append("---")
        elif tag in {"strong", "b"}:
            self._inline.append("**")
        elif tag in {"em", "i"}:
            self._inline.append("*")
        elif tag == "del":
            self._inline.append("~~")
        elif tag == "code" and not self._in_pre:
            self._inline.append("`")
            self._in_code = True
        elif tag == "a":
            self._link_href.append(attr.get("href"))
            self._inline.append("[")
        elif tag == "img":
            # Drop media URLs; keep nothing (alt ignored per upload policy spirit).
            return
        elif tag in {"h1", "h2", "h3", "h4", "h5", "h6"}:
            self._flush_inline_as_block()
            self._heading = int(tag[1])
        elif tag == "p":
            self._flush_inline_as_block()
        elif tag == "blockquote":
            self._flush_inline_as_block()
            self._in_blockquote += 1
        elif tag == "pre":
            self._flush_inline_as_block()
            self._in_pre = True
        elif tag in {"ul", "ol"}:
            self._flush_inline_as_block()
            if not self._list_stack:
                # Top-level list starts a new item buffer.
                self._list_items.append([])
            self._list_stack.append(tag)
            self._list_index.append(0)
        elif tag == "li":
            self._flush_inline_as_block()
            self._pending_li = True
        elif tag == "figcaption":
            self._flush_inline_as_block()
            self._in_figcaption = True
        elif tag == "dt":
            self._flush_inline_as_block()
        elif tag in {"td", "th"}:
            if (
                self._inline
                and not self._inline[-1].endswith(" | ")
                and any(part.strip() for part in self._inline)
            ):
                self._inline.append(" | ")
        elif tag in {
            "dd",
            "div",
            "span",
            "figure",
            "table",
            "thead",
            "tbody",
            "tr",
            "dl",
        }:
            # structural wrappers — no markdown markers
            return

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if tag in {
            "script",
            "style",
            "svg",
            "iframe",
            "video",
            "audio",
            "source",
            "button",
        }:
            if self._ignore_depth:
                self._ignore_depth -= 1
            return
        if self._ignore_depth:
            return

        if tag in {"strong", "b"}:
            self._inline.append("**")
        elif tag in {"em", "i"}:
            self._inline.append("*")
        elif tag == "del":
            self._inline.append("~~")
        elif tag == "code" and self._in_code and not self._in_pre:
            self._inline.append("`")
            self._in_code = False
        elif tag == "a":
            href = self._link_href.pop() if self._link_href else None
            parts: list[str] = []
            while self._inline and self._inline[-1] != "[":
                parts.append(self._inline.pop())
            if self._inline and self._inline[-1] == "[":
                self._inline.pop()
            label = "".join(reversed(parts))
            rendered = _markdown_link(label, href)
            if rendered:
                self._inline.append(rendered)
        elif tag in {"h1", "h2", "h3", "h4", "h5", "h6"}:
            text = self._take_inline().strip()
            level = self._heading or int(tag[1])
            self._heading = None
            if text:
                block = f"{'#' * level} {text}"
                self._blocks.append(self._maybe_quote(block))
        elif tag == "p":
            text = self._take_inline().strip()
            if text:
                self._blocks.append(self._maybe_quote(text))
        elif tag == "blockquote":
            text = self._take_inline().strip()
            if text:
                self._blocks.append(self._maybe_quote(text))
            if self._in_blockquote:
                self._in_blockquote -= 1
        elif tag == "pre":
            body = self._take_inline().strip("\n")
            self._in_pre = False
            self._blocks.append(f"```\n{body}\n```")
        elif tag == "li":
            text = self._take_inline().strip()
            if not text and not self._pending_li:
                return
            kind = self._list_stack[-1] if self._list_stack else "ul"
            if kind == "ol":
                if self._list_index:
                    self._list_index[-1] += 1
                    n = self._list_index[-1]
                else:
                    n = 1
                prefix = f"{n}."
            else:
                prefix = "-"
            indent = "  " * max(len(self._list_stack) - 1, 0)
            block = f"{indent}{prefix} {text}".rstrip()
            if self._list_items:
                self._list_items[-1].append(block)
            else:
                self._blocks.append(block)
            self._pending_li = False
        elif tag in {"ul", "ol"}:
            self._flush_inline_as_block()
            if self._list_stack:
                self._list_stack.pop()
            if self._list_index:
                self._list_index.pop()
            # Flush when the outermost list closes.
            if not self._list_stack:
                self._flush_list_items()
        elif tag == "figcaption":
            text = self._take_inline().strip()
            self._in_figcaption = False
            if text:
                self._blocks.append(f"*{text}*")
        elif tag == "dt":
            text = self._take_inline().strip()
            if text:
                self._blocks.append(f"**{text}**")
        elif tag == "dd":
            text = self._take_inline().strip()
            if text:
                self._blocks.append(text)
        elif tag in {"tr"}:
            text = self._take_inline().strip(" |")
            if text:
                self._blocks.append(text)

    def handle_data(self, data: str) -> None:
        if self._ignore_depth:
            return
        if not data:
            return
        if self._in_pre:
            self._inline.append(data)
            return
        # Collapse non-pre whitespace runs except keep intentional newlines from <br>.
        cleaned = re.sub(r"[ \t\r\f\v]+", " ", data)
        cleaned = cleaned.replace("\n", " ")
        self._inline.append(cleaned)

    def handle_entityref(self, name: str) -> None:
        self.handle_data(html_lib.unescape(f"&{name};"))

    def handle_charref(self, name: str) -> None:
        self.handle_data(html_lib.unescape(f"&#{name};"))

    def _maybe_quote(self, text: str) -> str:
        if self._in_blockquote <= 0:
            return text
        lines = text.splitlines() or [text]
        return "\n".join(f"> {line}" if line else ">" for line in lines)

    def _take_inline(self) -> str:
        text = "".join(self._inline)
        self._inline.clear()
        # tidy spaces around markdown markers
        text = re.sub(r"[ \t]+\n", "\n", text)
        text = re.sub(r"\n[ \t]+", "\n", text)
        text = re.sub(r" {2,}", " ", text)
        return text.strip(" ")

    def _flush_inline_as_block(self) -> None:
        text = self._take_inline().strip()
        if text:
            self._blocks.append(self._maybe_quote(text))

    def _flush_list_items(self) -> None:
        if not self._list_items:
            return
        items = self._list_items.pop()
        if items:
            self._blocks.append("\n".join(items))
