"""Free web tools for providers without a hosted web search (e.g. OpenRouter).

`web_search` uses DuckDuckGo through the `ddgs` package (no API key) and
`fetch_page` downloads a page and returns its readable text.
"""

from __future__ import annotations

import urllib.request
from html.parser import HTMLParser

from .tools import tool

MAX_PAGE_CHARS = 12000


@tool
def web_search(query: str, max_results: int = 6) -> list[dict]:
    """Search the web with DuckDuckGo. Returns titles, URLs and snippets.

    Args:
        query: What to search for.
        max_results: How many results to return (1-10).
    """
    from ddgs import DDGS

    hits = DDGS().text(query, max_results=max(1, min(max_results, 10)))
    return [{"title": h.get("title"), "url": h.get("href"), "snippet": h.get("body")} for h in hits]


class _TextExtractor(HTMLParser):
    _SKIP = {"script", "style", "noscript", "svg", "nav", "footer", "header", "form"}

    def __init__(self) -> None:
        super().__init__()
        self.parts: list[str] = []
        self._skip_depth = 0

    def handle_starttag(self, tag, attrs):
        if tag in self._SKIP:
            self._skip_depth += 1

    def handle_endtag(self, tag):
        if tag in self._SKIP and self._skip_depth:
            self._skip_depth -= 1

    def handle_data(self, data):
        if not self._skip_depth and data.strip():
            self.parts.append(data.strip())


def html_to_text(html: str) -> str:
    parser = _TextExtractor()
    parser.feed(html)
    return "\n".join(parser.parts)


@tool
def fetch_page(url: str) -> str:
    """Download a web page and return its main text (truncated if long).

    Args:
        url: The full http(s) URL to read, usually one returned by web_search.
    """
    if not url.startswith(("http://", "https://")):
        raise ValueError("url must start with http:// or https://")
    request = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (Clarivance agent)"})
    with urllib.request.urlopen(request, timeout=20) as response:
        charset = response.headers.get_content_charset() or "utf-8"
        body = response.read(2_000_000).decode(charset, errors="replace")
    text = html_to_text(body) if "<" in body[:1000] else body
    if len(text) > MAX_PAGE_CHARS:
        text = text[:MAX_PAGE_CHARS] + "\n[truncated]"
    return text
