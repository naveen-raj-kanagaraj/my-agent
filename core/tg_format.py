"""Turn the light Markdown that AI models write into Telegram's HTML formatting.

Supports: ```code blocks```, `inline code`, **bold**, *italic* / _italic_, [text](url), headings
(# Title -> bold line), bullet lists (- / * -> bullet). Everything else is escaped, so stray
characters can never break the message.
"""
import html
import re

_CODE_BLOCK = re.compile(r"```([\w+#.-]*)\n?(.*?)```", re.S)
_INLINE_CODE = re.compile(r"`([^`\n]+)`")
_LINK = re.compile(r"\[([^\]\n]+)\]\((https?://[^)\s]+)\)")
_BOLD = re.compile(r"\*\*(.+?)\*\*", re.S)
_ITALIC_STAR = re.compile(r"(?<![\w*])\*(?!\s)([^*\n]+?)(?<!\s)\*(?![\w*])")
_ITALIC_UND = re.compile(r"(?<![\w_])_(?!\s)([^_\n]+?)(?<!\s)_(?![\w_])")


def to_html(text: str) -> str:
    placeholders = []

    def keep(s: str) -> str:
        placeholders.append(s)
        return f"\x00{len(placeholders) - 1}\x00"

    def code_block(m):
        lang, body = m.group(1), m.group(2).rstrip("\n")
        cls = f' class="language-{html.escape(lang)}"' if lang else ""
        return keep(f"<pre><code{cls}>{html.escape(body)}</code></pre>")

    text = _CODE_BLOCK.sub(code_block, text)
    text = _INLINE_CODE.sub(lambda m: keep(f"<code>{html.escape(m.group(1))}</code>"), text)
    text = _LINK.sub(lambda m: keep(f'<a href="{html.escape(m.group(2), quote=True)}">{html.escape(m.group(1))}</a>'), text)

    text = html.escape(text, quote=False)
    lines = []
    for line in text.split("\n"):
        h = re.match(r"^\s{0,3}#{1,6}\s+(.*)$", line)
        if h:
            line = f"<b>{h.group(1).strip()}</b>"
        else:
            line = re.sub(r"^(\s*)[-*•]\s+", r"\1• ", line)
        lines.append(line)
    text = "\n".join(lines)
    text = _BOLD.sub(r"<b>\1</b>", text)
    text = _ITALIC_STAR.sub(r"<i>\1</i>", text)
    text = _ITALIC_UND.sub(r"<i>\1</i>", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return re.sub(r"\x00(\d+)\x00", lambda m: placeholders[int(m.group(1))], text).strip()


def split_for_telegram(text: str, limit: int = 3500) -> list:
    """Split Markdown into chunks at paragraph/line breaks, never inside a code block."""
    if len(text) <= limit:
        return [text]
    chunks, cur, in_code = [], "", False
    for para in re.split(r"(\n)", text):
        # Decide on a split before this line, using whether we're inside a code block *now*.
        if len(cur) + len(para) > limit and not in_code and cur.strip():
            chunks.append(cur)
            cur = ""
        cur += para
        if para.count("```") % 2:
            in_code = not in_code
        while len(cur) > 3900:  # one huge line or code block: hard split (Telegram max is 4096)
            chunks.append(cur[:limit])
            cur = cur[limit:]
    if cur.strip():
        chunks.append(cur)
    return chunks
