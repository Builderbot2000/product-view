"""HTML -> Confluence storage format.

Storage format is XHTML plus Confluence's `ac:`/`ri:` elements, and the REST API
rejects anything that is not well-formed XML. So the page is re-serialized
rather than passed through: void elements are self-closed, text is re-escaped
(named entities such as &nbsp; are not XML and would be refused), and only
<body> is kept.

What cannot live in storage format is converted, not silently lost:

- <img> with a local path or data: URI -> a page attachment + <ac:image>
- <img> with an http(s) URL             -> <ac:image> pointing at the URL
- inline <svg>                          -> an .svg attachment + <ac:image>
- <details><summary>                    -> the expand macro
- <script>, <style>, <head>, on* attributes, <button> -> dropped
"""

from __future__ import annotations

import base64
import binascii
import mimetypes
import re
from dataclasses import dataclass, field
from html import escape
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import unquote

VOID = {"area", "br", "col", "embed", "hr", "img", "input", "link", "meta", "source", "track", "wbr"}
# Subtrees dropped with their content.
DROP = {"head", "script", "style", "template", "button", "noscript"}
# Tags dropped but whose children are kept.
UNWRAP = {"html", "body"}


@dataclass
class Attachment:
    filename: str
    data: bytes
    media_type: str


@dataclass
class StoragePage:
    body: str
    attachments: list[Attachment] = field(default_factory=list)


def convert(html: str, base_dir: Path | None = None) -> StoragePage:
    """Convert an HTML document; `base_dir` resolves relative image paths."""
    parser = _Converter(base_dir)
    parser.feed(html)
    parser.close()
    return StoragePage(body="".join(parser.out).strip(), attachments=parser.attachments)


def convert_file(path: Path) -> StoragePage:
    return convert(path.read_text(encoding="utf-8"), base_dir=path.parent)


def _attrs(attrs: list[tuple[str, str | None]]) -> str:
    parts = []
    for name, value in attrs:
        if name.startswith("on"):
            continue
        parts.append(f' {name}="{escape(value if value is not None else name, quote=True)}"')
    return "".join(parts)


class _Converter(HTMLParser):
    def __init__(self, base_dir: Path | None) -> None:
        super().__init__(convert_charrefs=True)
        self.base_dir = base_dir
        self.out: list[str] = []
        self.attachments: list[Attachment] = []
        self._names: set[str] = set()
        self._drop_depth = 0          # >0 while inside a DROP subtree
        self._drop_tag: str | None = None
        self._svg: list[str] | None = None   # raw markup of the <svg> being captured
        self._svg_depth = 0
        self._svg_label = ""
        self._summary: list[str] | None = None  # text of the <summary> being read
        self._details_open: list[bool] = []     # per <details>: body opened yet?

    # -- attachments -------------------------------------------------------

    def _unique(self, filename: str) -> str:
        stem, dot, ext = filename.rpartition(".")
        if not dot:
            stem, ext = filename, ""
        name, n = filename, 1
        while name in self._names:
            n += 1
            name = f"{stem}-{n}.{ext}" if ext else f"{stem}-{n}"
        self._names.add(name)
        return name

    def _attach(self, filename: str, data: bytes, media_type: str) -> str:
        name = self._unique(filename)
        self.attachments.append(Attachment(name, data, media_type))
        return name

    def _image(self, attachment: str | None = None, url: str | None = None,
               alt: str = "", width: str | None = None, height: str | None = None) -> str:
        a = f' ac:alt="{escape(alt, quote=True)}"' if alt else ""
        if width:
            a += f' ac:width="{escape(width, quote=True)}"'
        if height:
            a += f' ac:height="{escape(height, quote=True)}"'
        if attachment:
            inner = f'<ri:attachment ri:filename="{escape(attachment, quote=True)}" />'
        else:
            inner = f'<ri:url ri:value="{escape(url or "", quote=True)}" />'
        return f"<ac:image{a}>{inner}</ac:image>"

    def _img(self, attrs: dict[str, str | None]) -> str:
        src = attrs.get("src") or ""
        alt, width, height = attrs.get("alt") or "", attrs.get("width"), attrs.get("height")
        if src.startswith(("http://", "https://")):
            return self._image(url=src, alt=alt, width=width, height=height)
        if src.startswith("data:"):
            m = re.match(r"data:([\w.+/-]+)?(;base64)?,(.*)", src, re.S)
            if not m:
                return ""
            media_type = m.group(1) or "application/octet-stream"
            try:
                data = (base64.b64decode(m.group(3)) if m.group(2)
                        else unquote(m.group(3)).encode("utf-8"))
            except (binascii.Error, ValueError):
                return ""
            ext = mimetypes.guess_extension(media_type) or ".bin"
            name = self._attach(f"image{ext}", data, media_type)
            return self._image(attachment=name, alt=alt, width=width, height=height)
        if self.base_dir is None:
            return ""
        path = (self.base_dir / unquote(src)).resolve()
        if not path.is_file():
            raise FileNotFoundError(f"image not found: {src} (looked in {self.base_dir})")
        media_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        name = self._attach(path.name, path.read_bytes(), media_type)
        return self._image(attachment=name, alt=alt, width=width, height=height)

    # -- output helpers ----------------------------------------------------

    def _emit(self, text: str) -> None:
        if self._summary is not None:
            return  # summary text is collected separately, as the macro title
        if self._details_open and not self._details_open[-1]:
            # First content inside <details> with no <summary>: open the body.
            self._open_expand("Details")
        self.out.append(text)

    def _open_expand(self, title: str) -> None:
        self.out.append(
            '<ac:structured-macro ac:name="expand">'
            f'<ac:parameter ac:name="title">{escape(title, quote=False)}</ac:parameter>'
            "<ac:rich-text-body>"
        )
        self._details_open[-1] = True

    # -- parser callbacks --------------------------------------------------

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if self._drop_depth:
            if tag == self._drop_tag:
                self._drop_depth += 1
            return
        if self._svg is not None:
            self._svg.append(f"<{tag}{_attrs(attrs)}>")
            if tag == "svg":
                self._svg_depth += 1
            return
        if tag in DROP:
            self._drop_tag, self._drop_depth = tag, 1
            return
        if tag in UNWRAP:
            return
        if tag == "svg":
            a = dict(attrs)
            a.setdefault("xmlns", "http://www.w3.org/2000/svg")
            self._svg, self._svg_depth = [f"<svg{_attrs(list(a.items()))}>"], 1
            self._svg_label = a.get("aria-label") or ""
            return
        if tag == "details":
            self._details_open.append(False)
            return
        if tag == "summary" and self._details_open and not self._details_open[-1]:
            self._summary = []
            return
        if tag == "img":
            self._emit(self._img(dict(attrs)))
            return
        if tag in VOID:
            self._emit(f"<{tag}{_attrs(attrs)} />")
            return
        self._emit(f"<{tag}{_attrs(attrs)}>")

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if self._svg is not None:
            self._svg.append(f"<{tag}{_attrs(attrs)} />")
            return
        self.handle_starttag(tag, attrs)
        if tag not in VOID and not self._drop_depth:
            self.handle_endtag(tag)

    def handle_endtag(self, tag: str) -> None:
        if self._drop_depth:
            if tag == self._drop_tag:
                self._drop_depth -= 1
            return
        if self._svg is not None:
            self._svg.append(f"</{tag}>")
            if tag == "svg":
                self._svg_depth -= 1
                if self._svg_depth == 0:
                    data = "".join(self._svg).encode("utf-8")
                    self._svg = None
                    name = self._attach("chart.svg", data, "image/svg+xml")
                    self._emit(self._image(attachment=name, alt=self._svg_label))
            return
        if tag in UNWRAP or tag in VOID:
            return
        if tag == "summary" and self._summary is not None:
            title = " ".join("".join(self._summary).split()) or "Details"
            self._summary = None
            self._open_expand(title)
            return
        if tag == "details":
            if not self._details_open:
                return
            opened = self._details_open.pop()
            if opened:
                self.out.append("</ac:rich-text-body></ac:structured-macro>")
            return
        self._emit(f"</{tag}>")

    def handle_data(self, data: str) -> None:
        if self._drop_depth:
            return
        if self._svg is not None:
            self._svg.append(escape(data, quote=False))
            return
        if self._summary is not None:
            self._summary.append(data)
            return
        if self._details_open and not self._details_open[-1] and not data.strip():
            return  # whitespace between <details> and <summary>
        self._emit(escape(data, quote=False))

    def handle_comment(self, data: str) -> None:
        pass  # comments carry no content and "--" inside one is invalid XML
