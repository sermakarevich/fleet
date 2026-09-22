"""Fetch the text behind a URL for the summary_get builder.

Called by `builders/summary_get.py`. One function per source kind, chosen
from the URL alone (`detect`): YouTube through the `yt` CLI, X/Twitter
through the `x` CLI, PDFs (including arXiv) through `pdftotext`, anything
else as a web page stripped to text with the standard library. Every
subprocess carries a timeout; every failure surfaces as `SourceError`
with the route that was tried, so the run fails loudly at start instead
of opening beads for a source nobody could read.
"""

from __future__ import annotations

import html
import json
import re
import shutil
import subprocess
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from enum import StrEnum
from html.parser import HTMLParser
from pathlib import Path

from fleet.core.errors import FleetError

_FETCH_TIMEOUT_S = 60
_CLI_TIMEOUT_S = 180
_MAX_BYTES = 50_000_000
_USER_AGENT = "Mozilla/5.0 (compatible; fleet-summary_get/1.0)"
_HTTP_TOO_MANY_REQUESTS = 429
_HTTP_SERVER_ERROR = 500

_YOUTUBE_HOSTS = ("youtube.com", "www.youtube.com", "m.youtube.com", "youtu.be")
_X_HOSTS = ("x.com", "www.x.com", "twitter.com", "www.twitter.com", "mobile.twitter.com")
_ARXIV_ID_RE = re.compile(r"arxiv\.org/(?:abs|pdf|html)/([0-9]{4}\.[0-9]{4,5}(?:v[0-9]+)?)")
_LOCAL_TEXT_SUFFIXES = frozenset({".md", ".markdown", ".txt"})
_BLOCK_TAGS = frozenset(
    {"p", "div", "br", "li", "ul", "ol", "tr", "table", "section", "article", "blockquote", "pre"}
)
_HEADING_TAGS = {"h1": "#", "h2": "##", "h3": "###", "h4": "####"}

#: (pattern, transient, message) read out of a CLI's whole output. A rich
#: traceback ends in boilerplate ("...no open issues which already describe
#: your problem!"), so the last line is a useless detail; these say what
#: actually went wrong and whether the URL deserves another try.
_CLI_CAUSES: tuple[tuple[re.Pattern[str], bool, str], ...] = (
    (
        re.compile(r"IpBlocked|RequestBlocked|blocking requests from your IP", re.I),
        True,
        "YouTube is blocking this machine's IP (too many requests); retry later",
    ),
    (
        re.compile(r"\b429\b|too many requests|rate.?limit", re.I),
        True,
        "rate limited by the server; retry later",
    ),
    (
        re.compile(r"PoTokenRequired", re.I),
        True,
        "YouTube asked for a proof-of-origin token; retry later",
    ),
    (
        re.compile(r"\b5\d\d\b|temporarily unavailable|service unavailable", re.I),
        True,
        "the server failed temporarily; retry later",
    ),
    (
        re.compile(r"transcripts are disabled", re.I),
        False,
        "transcripts are disabled for this video",
    ),
    (
        re.compile(r"NoTranscriptFound|no transcript", re.I),
        False,
        "no transcript in the wanted languages",
    ),
    (
        re.compile(r"VideoUnavailable|video unavailable|\b404\b|not found", re.I),
        False,
        "the source is gone (404 / unavailable)",
    ),
)


class SourceError(FleetError):
    """The source behind a URL could not be fetched or read.

    ``transient`` marks a failure that says nothing about the source: a
    rate limit, an IP block, a timeout, a server-side 5xx. The same URL
    is likely to work later, so callers retry it instead of writing the
    source off. A dead link, a disabled transcript or an empty page is
    permanent and leaves ``transient`` false.
    """

    def __init__(self, message: str, *, transient: bool = False) -> None:
        """Remember the message and whether retrying could help."""
        super().__init__(message)
        self.transient = transient


class SourceKind(StrEnum):
    """Which route fetches a URL."""

    youtube = "youtube"
    x = "x"
    pdf = "pdf"
    article = "article"


#: Per-kind politeness: how many fetches of this kind may run at once and
#: how long to wait between two of them. The spawn step starts many runs in
#: parallel and each one shells out to a CLI, which is what got this machine
#: rate limited by YouTube; `x` is serialized because every call costs money.
_KIND_LIMITS: dict[str, tuple[int, float]] = {
    SourceKind.youtube: (1, 1.5),
    SourceKind.x: (1, 1.0),
}


@dataclass(frozen=True, slots=True)
class Source:
    """Fetched source: its kind, a title hint and the full text as markdown."""

    url: str
    kind: SourceKind
    title: str
    text: str
    tool: str


def _local_path(url: str) -> Path | None:
    """Absolute local path for `file://` URLs and bare paths; None when not local."""
    text = url.strip()
    if text.startswith("file://"):
        return Path(urllib.request.url2pathname(text[len("file://") :])).expanduser()
    parsed = urllib.parse.urlparse(text)
    if parsed.scheme == "" and parsed.path.startswith("/"):
        return Path(parsed.path).expanduser()
    if text.startswith("/") or text.startswith("~/"):
        return Path(text).expanduser()
    return None


def detect(url: str) -> SourceKind:
    """Pick the fetch route from the URL's host and path, or from a local file suffix."""
    local = _local_path(url)
    if local is not None:
        suffix = local.suffix.lower()
        if suffix == ".pdf":
            return SourceKind.pdf
        if suffix in _LOCAL_TEXT_SUFFIXES:
            return SourceKind.article
        raise SourceError(f"url {url!r}: local files must be .pdf, .md or .txt")
    parsed = urllib.parse.urlparse(url.strip())
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        raise SourceError(f"url {url!r}: must be an http(s) URL or an absolute local path")
    host = parsed.netloc.lower()
    if host in _YOUTUBE_HOSTS:
        return SourceKind.youtube
    if host in _X_HOSTS:
        return SourceKind.x
    if _ARXIV_ID_RE.search(url) or parsed.path.lower().endswith(".pdf"):
        return SourceKind.pdf
    return SourceKind.article


def fetch(url: str, work_dir: Path) -> Source:
    """Fetch one URL by its detected route; `work_dir` receives downloads."""
    local = _local_path(url)
    if local is not None:
        return _fetch_local_file(url, local, detect(url), work_dir)
    kind = detect(url)
    if kind is SourceKind.youtube:
        return _fetch_youtube(url)
    if kind is SourceKind.x:
        return _fetch_x(url)
    if kind is SourceKind.pdf:
        return _fetch_pdf(url, work_dir)
    return _fetch_article(url)


def _fetch_local_file(url: str, path: Path, kind: SourceKind, work_dir: Path) -> Source:
    """Read a local file straight off disk: PDFs through pdftotext, text as-is."""
    if not path.is_file():
        raise SourceError(f"fetch {url}: no such file")
    if path.stat().st_size > _MAX_BYTES:
        raise SourceError(f"fetch {url}: file exceeds {_MAX_BYTES} bytes")
    work_dir.mkdir(parents=True, exist_ok=True)
    staged = work_dir / f"source{path.suffix.lower()}"
    if path.resolve() != staged.resolve():
        staged.write_bytes(path.read_bytes())
    if kind is SourceKind.pdf:
        if shutil.which("pdftotext") is None:
            raise SourceError("pdf: `pdftotext` (poppler) is not installed")
        text = _run(["pdftotext", "-layout", str(staged), "-"], what="pdf text")
        title = _pdf_title(staged, text)
        return Source(url=url, kind=kind, title=title, text=text, tool="pdftotext")
    text = staged.read_text(encoding="utf-8", errors="replace")
    if len(text.strip()) < 200:  # noqa: PLR2004  # same stub threshold as web articles
        raise SourceError(f"fetch {url}: file yielded only {len(text)} characters of text")
    first = next((line.strip() for line in text.splitlines() if line.strip()), path.name)
    return Source(url=url, kind=kind, title=first[:160], text=text, tool="local-file")


class _Throttle:
    """Cap how many fetches of one kind run at once, and space them out.

    The spawn step starts many workflow runs in parallel and every one of
    them fetches its source, so without this the CLIs hit a single host as
    fast as the pool allows. Shared process-wide; a fetch of an unlisted
    kind is not held back at all.
    """

    def __init__(self) -> None:
        """Start with no gates; each kind gets one the first time it is used."""
        self._guard = threading.Lock()
        self._gates: dict[str, tuple[threading.Semaphore, threading.Lock, list[float]]] = {}

    def _gate(self, kind: str) -> tuple[threading.Semaphore, threading.Lock, list[float]] | None:
        limit = _KIND_LIMITS.get(kind)
        if limit is None:
            return None
        with self._guard:
            gate = self._gates.get(kind)
            if gate is None:
                gate = (threading.Semaphore(limit[0]), threading.Lock(), [0.0])
                self._gates[kind] = gate
            return gate

    @contextmanager
    def hold(self, kind: str | None) -> Iterator[None]:
        """Wait for a slot of this kind, and for the gap since the last one."""
        gate = self._gate(kind) if kind is not None else None
        if gate is None:
            yield
            return
        slots, clock, last = gate
        gap = _KIND_LIMITS[kind][1]
        with slots:
            with clock:
                wait = last[0] + gap - time.monotonic()
                if wait > 0:
                    time.sleep(wait)
                last[0] = time.monotonic()
            yield


_THROTTLE = _Throttle()


def _cli_failure(what: str, argv: list[str], output: str, returncode: int) -> SourceError:
    """Name the cause in a CLI's output and say whether a retry could help."""
    for pattern, transient, message in _CLI_CAUSES:
        if pattern.search(output):
            return SourceError(f"{what}: `{' '.join(argv)}` failed: {message}", transient=transient)
    lines = [line.strip() for line in output.strip().splitlines() if line.strip()]
    tail = lines[-1] if lines else f"exit {returncode}"
    return SourceError(f"{what}: `{' '.join(argv)}` failed: {tail}")


def _run(argv: list[str], *, what: str, kind: str | None = None) -> str:
    """Run one CLI and return stdout; missing binary or failure is a SourceError."""
    if shutil.which(argv[0]) is None:
        raise SourceError(f"{what}: `{argv[0]}` is not installed or not on PATH")
    try:
        with _THROTTLE.hold(kind):
            done = subprocess.run(
                argv, capture_output=True, text=True, timeout=_CLI_TIMEOUT_S, check=False
            )
    except subprocess.TimeoutExpired:
        raise SourceError(f"{what}: `{' '.join(argv)}` timed out", transient=True) from None
    if done.returncode != 0:
        raise _cli_failure(what, argv, f"{done.stderr}\n{done.stdout}", done.returncode)
    if not done.stdout.strip():
        raise SourceError(f"{what}: `{' '.join(argv)}` returned no text")
    return done.stdout


def _http_get(url: str) -> tuple[bytes, str]:
    """GET one URL; return (body, content-type)."""
    request = urllib.request.Request(url, headers={"User-Agent": _USER_AGENT})
    try:
        with urllib.request.urlopen(request, timeout=_FETCH_TIMEOUT_S) as response:  # noqa: S310
            return response.read(_MAX_BYTES), str(response.headers.get("Content-Type", ""))
    except (urllib.error.URLError, OSError, ValueError) as exc:
        raise SourceError(f"fetch {url}: {exc}", transient=_http_transient(exc)) from None


def _http_transient(exc: BaseException) -> bool:
    """True when a failed GET says nothing about the URL, only about now."""
    if isinstance(exc, urllib.error.HTTPError):
        return exc.code == _HTTP_TOO_MANY_REQUESTS or exc.code >= _HTTP_SERVER_ERROR
    # A refused connection, a DNS hiccup or a timeout is about the network.
    return isinstance(exc, urllib.error.URLError | TimeoutError | ConnectionError)


def _fetch_youtube(url: str) -> Source:
    """Transcript through the `yt` CLI; title through YouTube's oEmbed endpoint."""
    text = _run(
        ["yt", "transcript", url, "--format", "txt"],
        what="youtube transcript",
        kind=SourceKind.youtube,
    )
    return Source(url=url, kind=SourceKind.youtube, title=_youtube_title(url), text=text, tool="yt")


def _youtube_title(url: str) -> str:
    """Video title from oEmbed; the URL itself when that lookup fails."""
    query = urllib.parse.urlencode({"url": url, "format": "json"})
    try:
        body, _ = _http_get(f"https://www.youtube.com/oembed?{query}")
        return str(json.loads(body).get("title") or url)
    except (SourceError, ValueError):
        return url


def _fetch_x(url: str) -> Source:
    """Tweet or thread as markdown through the `x` CLI (costs paid credits)."""
    text = _run(
        ["x", "tweet", url, "--thread", "--format", "md"], what="x thread", kind=SourceKind.x
    )
    first = next((line.strip("# ").strip() for line in text.splitlines() if line.strip()), url)
    return Source(url=url, kind=SourceKind.x, title=first[:120], text=text, tool="x")


def _pdf_url(url: str) -> str:
    """arXiv abs/html links point at the PDF; other URLs are used as given."""
    match = _ARXIV_ID_RE.search(url)
    if match is not None:
        return f"https://arxiv.org/pdf/{match.group(1)}"
    return url


def _fetch_pdf(url: str, work_dir: Path) -> Source:
    """Download the PDF into `work_dir` and extract its text with pdftotext."""
    if shutil.which("pdftotext") is None:
        raise SourceError("pdf: `pdftotext` (poppler) is not installed")
    body, _ = _http_get(_pdf_url(url))
    work_dir.mkdir(parents=True, exist_ok=True)
    path = work_dir / "source.pdf"
    path.write_bytes(body)
    text = _run(["pdftotext", "-layout", str(path), "-"], what="pdf text")
    return Source(
        url=url, kind=SourceKind.pdf, title=_pdf_title(path, text), text=text, tool="pdftotext"
    )


def _pdf_title(path: Path, text: str) -> str:
    """PDF metadata title when present, else the first non-empty text line."""
    if shutil.which("pdfinfo") is not None:
        try:
            info = subprocess.run(
                ["pdfinfo", str(path)],
                capture_output=True,
                text=True,
                timeout=_FETCH_TIMEOUT_S,
                check=False,
            ).stdout
        except subprocess.TimeoutExpired:
            info = ""
        for line in info.splitlines():
            if line.startswith("Title:") and line[6:].strip():
                return line[6:].strip()[:120]
    first = next((line.strip() for line in text.splitlines() if line.strip()), path.name)
    return first[:120]


class _MarkdownExtractor(HTMLParser):
    """Visible page text with headings kept as markdown and block breaks kept."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._skip = 0
        self._parts: list[str] = []
        self._heading: str | None = None
        self.title = ""
        self._in_title = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in ("script", "style", "noscript", "nav", "footer", "header", "aside", "svg"):
            self._skip += 1
        elif tag == "title":
            self._in_title = True
        elif tag in _HEADING_TAGS and self._skip == 0:
            self._heading = _HEADING_TAGS[tag]
            self._parts.append(f"\n\n{self._heading} ")
        elif tag in _BLOCK_TAGS and self._skip == 0:
            self._parts.append("\n\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in ("script", "style", "noscript", "nav", "footer", "header", "aside", "svg"):
            self._skip = max(0, self._skip - 1)
        elif tag == "title":
            self._in_title = False
        elif tag in _HEADING_TAGS:
            self._heading = None
            self._parts.append("\n\n")
        elif tag in _BLOCK_TAGS:
            self._parts.append("\n\n")

    def handle_data(self, data: str) -> None:
        if self._in_title:
            self.title += data
        if self._skip == 0 and data.strip():
            self._parts.append(re.sub(r"\s+", " ", data) if self._heading else data)

    def text(self) -> str:
        joined = "".join(self._parts)
        joined = re.sub(r"[ \t]+\n", "\n", joined)
        joined = re.sub(r"\n{3,}", "\n\n", joined)
        return html.unescape(joined).strip()


def _fetch_article(url: str) -> Source:
    """Web page stripped to markdown-ish text; PDFs served without .pdf go to pdftotext."""
    body, content_type = _http_get(url)
    if "application/pdf" in content_type.lower() or body[:5] == b"%PDF-":
        raise SourceError(
            f"fetch {url}: served a PDF without a .pdf path; pass the PDF link directly"
        )
    parser = _MarkdownExtractor()
    parser.feed(body.decode("utf-8", errors="replace"))
    text = parser.text()
    if len(text) < 200:  # noqa: PLR2004  # a real article is longer than a stub page
        raise SourceError(f"fetch {url}: page yielded only {len(text)} characters of text")
    title = re.sub(r"\s+", " ", parser.title).strip() or url
    return Source(url=url, kind=SourceKind.article, title=title[:160], text=text, tool="urllib")
