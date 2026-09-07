#!/usr/bin/env python3
"""MCP server: fetch a URL and distill it with the local model.

A dependency-free clone of Claude Code's WebFetch. The ``web_fetch`` tool fetches
a page, strips it to text (stdlib only), then asks the local ollama model (the
same OpenAI-compatible endpoint opencode uses) to answer a prompt about it,
returning ONLY the distilled answer — not the raw page — so large pages never
flood the calling agent's context.

Run standalone: python -m fleet.integrations.web_fetch.server   (stdio transport).
Config via env: FLEET_WEBFETCH_MODEL (model name; if unset, the first model the
endpoint reports is used) and FLEET_WEBFETCH_OLLAMA_URL (default below).
"""

from __future__ import annotations

import json
import os
import urllib.request
from html.parser import HTMLParser
from typing import Any

from mcp.server.fastmcp import FastMCP

_DEFAULT_OLLAMA_URL = "http://127.0.0.1:11435/v1"
_FETCH_TIMEOUT_S = 30
_LLM_TIMEOUT_S = 120
_MAX_PAGE_CHARS = 40000  # bound what we feed the model
_MAX_BYTES = 5_000_000

mcp = FastMCP(
    "web_fetch",
    instructions=(
        "Fetch a web page and get a concise, distilled answer to a question about "
        "it. Call `web_fetch` with a `url` and a `prompt` describing what you want "
        "from the page; a local model reads the page and returns only the relevant "
        "answer, not the raw HTML. Good for docs, articles, and reference pages. "
        "Ask one focused question per call."
    ),
)


class _TextExtractor(HTMLParser):
    """Collect visible text, skipping script/style/noscript."""

    def __init__(self) -> None:
        super().__init__()
        self._skip = 0
        self._parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: Any) -> None:
        if tag in ("script", "style", "noscript"):
            self._skip += 1

    def handle_endtag(self, tag: str) -> None:
        if tag in ("script", "style", "noscript") and self._skip:
            self._skip -= 1

    def handle_data(self, data: str) -> None:
        if self._skip == 0:
            text = data.strip()
            if text:
                self._parts.append(text)

    def text(self) -> str:
        return "\n".join(self._parts)


def _base_url() -> str:
    return os.environ.get("FLEET_WEBFETCH_OLLAMA_URL", _DEFAULT_OLLAMA_URL).rstrip("/")


def _fetch(url: str) -> str:
    if not url.lower().startswith(("http://", "https://")):
        raise ValueError("url must be http(s)")
    req = urllib.request.Request(url, headers={"User-Agent": "fleet-web_fetch/1.0"})
    with urllib.request.urlopen(req, timeout=_FETCH_TIMEOUT_S) as resp:  # noqa: S310
        raw = resp.read(_MAX_BYTES)
    parser = _TextExtractor()
    parser.feed(raw.decode("utf-8", errors="replace"))
    return parser.text()


def _model() -> str:
    m = os.environ.get("FLEET_WEBFETCH_MODEL", "").strip()
    if m:
        return m
    req = urllib.request.Request(f"{_base_url()}/models")
    with urllib.request.urlopen(req, timeout=_FETCH_TIMEOUT_S) as resp:  # noqa: S310
        data = json.loads(resp.read())
    models = data.get("data") or []
    if not models:
        raise RuntimeError("no model available and FLEET_WEBFETCH_MODEL is unset")
    return models[0]["id"]


def _distill(page: str, prompt: str, truncated: bool) -> str:
    note = " (page was truncated)" if truncated else ""
    body = {
        "model": _model(),
        "messages": [
            {
                "role": "system",
                "content": (
                    "You extract information from web pages. Using ONLY the page "
                    "content provided, answer the user's request concisely. If the "
                    "answer is not present in the content, say so plainly."
                ),
            },
            {
                "role": "user",
                "content": f"Request: {prompt}\n\nPage content{note}:\n{page}",
            },
        ],
        "stream": False,
        "temperature": 0,
    }
    req = urllib.request.Request(
        f"{_base_url()}/chat/completions",
        data=json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=_LLM_TIMEOUT_S) as resp:  # noqa: S310
        data = json.loads(resp.read())
    return data["choices"][0]["message"]["content"]


@mcp.tool()
def web_fetch(url: str, prompt: str) -> dict[str, Any]:
    """Fetch a URL and return a distilled answer to ``prompt`` about its content.

    Args:
        url: The http(s) URL to fetch.
        prompt: What you want to know from the page.

    Returns:
        {"url", "answer", "chars", "truncated"} on success, or {"url", "error"} on
        failure. ``answer`` is the local model's concise answer using only the page.
    """
    try:
        page = _fetch(url)
    except Exception as e:  # noqa: BLE001
        return {"url": url, "error": f"fetch failed: {e}"}
    truncated = len(page) > _MAX_PAGE_CHARS
    try:
        answer = _distill(page[:_MAX_PAGE_CHARS], prompt, truncated)
    except Exception as e:  # noqa: BLE001
        return {"url": url, "error": f"distill failed: {e}"}
    return {"url": url, "answer": answer, "chars": len(page), "truncated": truncated}


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
