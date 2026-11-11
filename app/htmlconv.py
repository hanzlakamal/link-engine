"""Convert the clean article HTML Claude writes (h2/h3/p/ul/ol/li/a/strong/em/blockquote) into the
formats other platforms want: Markdown (DEV, Hashnode, Write.as), Telegraph nodes, plain text."""
from __future__ import annotations

from bs4 import BeautifulSoup, NavigableString, Tag

TELEGRAPH_TAGS = {"a", "aside", "b", "blockquote", "br", "code", "em", "figcaption", "figure", "h3", "h4", "hr", "i",
                  "iframe", "img", "li", "ol", "p", "pre", "s", "strong", "u", "ul", "video"}


def _inline_md(node) -> str:
    if isinstance(node, NavigableString):
        return str(node)
    if not isinstance(node, Tag):
        return ""
    inner = "".join(_inline_md(c) for c in node.children)
    if node.name in ("strong", "b"):
        return f"**{inner.strip()}**" if inner.strip() else ""
    if node.name in ("em", "i"):
        return f"*{inner.strip()}*" if inner.strip() else ""
    if node.name == "a":
        href = node.get("href", "")
        return f"[{inner.strip()}]({href})" if href else inner
    if node.name == "br":
        return "\n"
    if node.name == "code":
        return f"`{inner}`"
    return inner


def to_markdown(html: str) -> str:
    soup = BeautifulSoup(html or "", "html.parser")
    out: list[str] = []

    def block(el):
        if isinstance(el, NavigableString):
            t = str(el).strip()
            if t:
                out.append(t)
            return
        if not isinstance(el, Tag):
            return
        n = el.name
        if n in ("h1", "h2", "h3", "h4"):
            out.append("#" * max(int(n[1]), 2) + " " + _inline_md(el).strip())
        elif n == "p":
            t = _inline_md(el).strip()
            if t:
                out.append(t)
        elif n in ("ul", "ol"):
            items = [li for li in el.find_all("li", recursive=False)]
            out.append("\n".join((f"{i}. " if n == "ol" else "- ") + _inline_md(li).strip()
                                 for i, li in enumerate(items, 1)))
        elif n == "blockquote":
            out.append("> " + _inline_md(el).strip())
        elif n == "hr":
            out.append("---")
        else:
            for c in el.children:
                block(c)

    for c in soup.children:
        block(c)
    return "\n\n".join(x for x in out if x).strip() + "\n"


def to_telegraph_nodes(html: str) -> list:
    """Telegraph accepts a limited tag set; h2 -> h3, h3 -> h4, unknown tags are unwrapped."""
    soup = BeautifulSoup(html or "", "html.parser")

    def conv(el):
        if isinstance(el, NavigableString):
            t = str(el)
            return t if t.strip() or t == " " else None
        if not isinstance(el, Tag):
            return None
        name = {"h1": "h3", "h2": "h3", "h3": "h4", "h5": "h4", "h6": "h4"}.get(el.name, el.name)
        kids = [k for k in (conv(c) for c in el.children) if k is not None]
        flat = []
        for k in kids:
            flat.extend(k if isinstance(k, list) else [k])
        if name not in TELEGRAPH_TAGS:
            return flat or None
        node = {"tag": name}
        if name == "a" and el.get("href"):
            node["attrs"] = {"href": el["href"]}
        if flat:
            node["children"] = flat
        return node

    nodes = []
    for c in soup.children:
        r = conv(c)
        if r is None:
            continue
        nodes.extend(r if isinstance(r, list) else [r])
    # top-level bare strings must sit inside a paragraph
    return [{"tag": "p", "children": [n]} if isinstance(n, str) else n for n in nodes if n != " "]


def to_text(html: str) -> str:
    return " ".join(BeautifulSoup(html or "", "html.parser").get_text(" ").split())


def links_in(html: str) -> list[str]:
    return [a.get("href", "") for a in BeautifulSoup(html or "", "html.parser").find_all("a") if a.get("href")]
