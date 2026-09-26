"""tweet_watch worker: R1-R6 steps plus the ordered run flow (scaffold)."""

from __future__ import annotations

import logging
import os
import re
import tempfile
import warnings
from collections.abc import Callable, Mapping, Sequence
from datetime import date
from pathlib import Path

from fleet.tweet_watch.kb_files import SEED_HANDLES, load_state, read_watchlist, save_state
from fleet.tweet_watch.x_fetch import FetchError, Tweet, fetch_tweets

logger = logging.getLogger(__name__)

WATCHLIST_PATH = Path("/Users/sergii/.ai/knowledge/media/x/watchlist.md")
STATE_PATH = Path("/Users/sergii/.ai/knowledge/media/x/watch_state.json")
INTERESTS_PATH = Path("/Users/sergii/.ai/knowledge/media/INTERESTS.md")
REPLIES_DIR = Path("/Users/sergii/.ai/knowledge/media/x/replies")


def ensure_watchlist(watchlist_path: Path = WATCHLIST_PATH) -> list[str]:
    """Ensure the watchlist exists, then read it.

    If the file is missing, ``mkdir -p`` the parent and atomically create it
    with exactly the 5 M1 seed handles in spec order (one per line, LF,
    single trailing newline), then return them. An existing file is never
    overwritten — its M1 parse is returned as-is (possibly ``[]``). A
    directory path, an unreadable file, a failed create, or a file lost
    between ensure and read aborts with an error naming the path.
    """
    path = Path(watchlist_path)
    if path.is_dir():
        raise OSError(f"{path}: watchlist path is a directory")
    if not path.exists():
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            raise OSError(f"{path}: cannot create parent dir: {exc}") from exc
        payload = "\n".join(SEED_HANDLES) + "\n"
        try:
            fd, tmp_name = tempfile.mkstemp(
                dir=str(path.parent), prefix=path.name + ".", suffix=".tmp"
            )
            try:
                with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as tmp_file:
                    tmp_file.write(payload)
                os.replace(tmp_name, path)
            except BaseException:
                try:
                    os.unlink(tmp_name)
                except OSError:
                    pass
                raise
        except OSError as exc:
            if str(path) in str(exc):
                raise
            raise OSError(f"{path}: cannot create watchlist file: {exc}") from exc
        return list(SEED_HANDLES)
    try:
        return read_watchlist(path)
    except OSError as exc:
        if str(path) in str(exc):
            raise
        raise OSError(f"{path}: cannot read watchlist file: {exc}") from exc


def find_new_tweets(
    handles: Sequence[str],
    state_path: Path = STATE_PATH,
    run_command: Callable[[tuple[str, ...]], str] | None = None,
) -> list[Tweet]:
    """Fetch candidates via M2 and emit only tweets newer than stored state.

    Missing state entry means every candidate for that handle is new.
    Comparison uses the tweet ``id`` only: numeric when both ids are
    all-digit, otherwise a string fallback. Duplicate ``(handle, id)``
    records emit once. A failed handle warns and is skipped while
    siblings continue; a run-wide check failure aborts with state
    untouched. State advances to the newest seen id per successful
    handle, never regresses, and is left byte-identical when nothing
    is new. Before saving, the file is re-read and merged per-handle
    maxima so overlapping runs never roll back each other.
    """
    wanted: list[str] = []
    for handle in handles:
        if handle not in wanted:
            wanted.append(handle)
    if not wanted:
        return []
    path = Path(state_path)
    baseline = load_state(path)

    pending = list(wanted)
    candidates: list[Tweet] = []
    while pending:
        try:
            candidates = fetch_tweets(pending, run_command=run_command)
        except FetchError as exc:
            if exc.handle in pending:
                warnings.warn(str(exc), UserWarning, stacklevel=2)
                pending = [h for h in pending if h != exc.handle]
                continue
            raise
        break

    fresh: list[Tweet] = []
    maxima: dict[str, str] = {}
    seen: set[tuple[str, str]] = set()
    for tweet in candidates:
        key = (tweet.handle, tweet.id)
        if key in seen:
            continue
        seen.add(key)
        stored = baseline.get(tweet.handle)
        if stored is None or _is_newer_id(tweet.id, stored):
            fresh.append(tweet)
            current = maxima.get(tweet.handle)
            if current is None or _is_newer_id(tweet.id, current):
                maxima[tweet.handle] = tweet.id
    if not maxima:
        return []

    merged = dict(baseline)
    for handle, new_max in maxima.items():
        current = merged.get(handle)
        if current is None or _is_newer_id(new_max, current):
            merged[handle] = new_max
    if path.exists():
        reloaded = load_state(path)
        for handle, value in reloaded.items():
            current = merged.get(handle)
            if current is None or _is_newer_id(value, current):
                merged[handle] = value
    save_state(path, merged)
    return fresh


def _is_newer_id(candidate: str, stored: str) -> bool:
    if (
        candidate.isascii()
        and candidate.isdigit()
        and stored.isascii()
        and stored.isdigit()
    ):
        return int(candidate) > int(stored)
    logger.debug("non-numeric tweet id comparison: %r vs %r", candidate, stored)
    return candidate > stored


def score_tweet(tweet_text: str, interests_text: str) -> str:
    """Score one tweet HIGH, MEDIUM, or LOW against INTERESTS.md content.

    Pure function of (tweet text, interests text): same inputs always yield
    the same label, no file reads, no reply-history reads, no shared state.
    Core signals score HIGH (needs substance: two distinct core signals, or
    one plus a number/claim), Adjacent signals score MEDIUM, everything else
    is LOW. An explicit LOW exclusion beats an adjacent match, but
    substantive core content still wins over a bait tail. Empty tweet text
    scores LOW. Empty interests or interests with no Core/Adjacent topics
    raise instead of silently scoring LOW. Curated signal units only count
    when their key term appears in the given interests text, so a foreign
    interests file never yields HIGH on unrelated tweets.
    """
    sections = _split_interest_sections(interests_text)
    core_text = sections["core"]
    adjacent_text = sections["adjacent"]
    if not _has_content_words(core_text) and not _has_content_words(adjacent_text):
        raise ValueError("INTERESTS.md contains no scorable topics")
    interests_norm = interests_text.casefold()

    text = _normalize_for_scoring(tweet_text or "")
    if not text:
        logger.debug("scoring empty tweet text as LOW")
        return "LOW"

    core_hits = _count_active_units(text, interests_norm, _CORE_UNITS)
    adjacent_hits = _count_active_units(text, interests_norm, _ADJACENT_UNITS)
    low_hit = _count_active_units(text, interests_norm, _LOW_UNITS) > 0 or bool(
        _PRICE_RE.search(text) and "price" in interests_norm
    )

    if core_hits >= 2:
        return "HIGH"
    if core_hits == 1 and _has_substance(text):
        return "HIGH"
    if low_hit:
        return "LOW"
    if core_hits == 1 or adjacent_hits >= 1:
        return "MEDIUM"
    if _generic_topic_overlap(core_text, adjacent_text, text):
        return "MEDIUM"
    return "LOW"


_HEADER_RE = re.compile(r"^\s{0,3}#{1,6}\s*(.+?)\s*$", re.MULTILINE)
_URL_RE = re.compile(r"https?://\S+|www\.\S+", re.IGNORECASE)
_ZERO_WIDTH_RE = re.compile("[\u200b\u200c\u200d\ufeff\u00ad\u2060\u180e]")
_DASH_RE = re.compile("[‐‑‒–—―−]")
_SEPARATOR_RE = re.compile(r"[/_#@|]+")
_WS_RE = re.compile(r"\s+")
_WORD_RE = re.compile(r"[a-z\u0400-\u04ff]{4,}")
_DIGIT_RE = re.compile(r"\d")
_TOKEN_RE = re.compile(r"[a-z\u0400-\u04ff0-9]+")
_CONTENT_RE = re.compile(r"[a-z\u0400-\u04ff]{3,}")
_PRICE_RE = re.compile(r"\$\s?\d")

_STOPWORDS = frozenset(
    {
        "this", "that", "with", "from", "have", "been", "were", "will",
        "would", "there", "their", "about", "into", "your", "what", "when",
        "them", "then", "than", "also", "just", "like", "more", "most",
        "over", "such", "only", "very", "they", "them",
    }
)

# (normalized phrase, gate term that must appear in the interests text)
_CORE_UNITS: tuple[tuple[str, str], ...] = (
    ("beads", "beads"),
    ("worker loop", "worker loop"),
    ("orchestrat", "orchestrat"),
    ("headless", "headless"),
    ("harness", "harness"),
    ("fleet", "fleet"),
    ("supervisor", "supervisor"),
    ("opencode", "opencode"),
    ("claude code", "claude"),
    ("muse spark", "spark"),
    ("claude fable", "fable"),
    ("typesafe", "typesafe"),
    ("jev", "jev"),
    ("calibrat", "calibrat"),
    ("verifier", "verifier"),
    ("eval", "eval"),
    ("ihbench", "ihbench"),
    ("interruption", "interruption"),
    ("stt", "stt"),
    ("tts", "tts"),
    ("turn taking", "turn"),
    ("telephony", "telephony"),
    ("speech to speech", "speech"),
    ("pipelin", "pipelin"),
    ("tasks per dollar", "tasks"),
    ("token economic", "token"),
    ("cost engineer", "cost"),
    ("cheap local", "cheap"),
    ("frontier model", "frontier"),
    ("coding agent", "coding agent"),
    ("voice agent", "voice agent"),
    ("latency", "latency"),
    ("voice pipeline", "voice"),
)

_ADJACENT_UNITS: tuple[tuple[str, str], ...] = (
    ("swarm", "swarm"),
    ("emergent coordination", "emergent"),
    ("collective memory", "collective"),
    ("agent societ", "societ"),
    ("second brain", "second brain"),
    ("personal knowledge", "personal knowledge"),
    ("recall", "recall"),
    ("memory layer", "memory"),
    ("enterprise", "enterprise"),
    ("applied ai", "applied ai"),
    ("trend outlook", "trend"),
    ("kv cache", "kv"),
    ("inference memory", "inference"),
    ("hybrid", "hybrid"),
    ("ai worker", "ai"),
)

_LOW_UNITS: tuple[tuple[str, str], ...] = (
    ("giveaway", "giveaway"),
    ("retweet to win", "giveaway"),
    ("retweet to enter", "bait"),
    ("retweet to", "giveaway"),
    ("follow and tag", "bait"),
    ("tag 3 friends", "giveaway"),
    ("tag friends", "giveaway"),
    ("win 1 eth", "giveaway"),
    ("btc", "price"),
    ("eth", "giveaway"),
    ("moon", "meme"),
    ("buying", "price"),
    ("to $", "price"),
    ("stock pick", "stock"),
    ("finfluencer", "finfluencer"),
    ("price", "price"),
)


def _split_interest_sections(interests_text: str | None) -> dict[str, str]:
    if interests_text is None or not interests_text.strip():
        raise ValueError("INTERESTS.md is missing or empty: no scorable topics")
    matches = list(_HEADER_RE.finditer(interests_text))
    if not matches:
        raise ValueError("INTERESTS.md has no scorable topics")
    sections = {"core": [], "adjacent": [], "low": []}
    for index, match in enumerate(matches):
        title = match.group(1).casefold()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(interests_text)
        body = interests_text[match.end() : end]
        if "core" in title:
            sections["core"].append(body)
        elif "adjacent" in title:
            sections["adjacent"].append(body)
        elif re.search(r"\blow\b", title) or title.strip().startswith("low"):
            sections["low"].append(body)
    return {kind: "\n".join(bodies) for kind, bodies in sections.items()}


def _has_content_words(section_text: str) -> bool:
    return bool(_CONTENT_RE.search(section_text.casefold()))


def _normalize_for_scoring(raw: str) -> str:
    text = raw.casefold()
    text = _URL_RE.sub(" ", text)
    text = _ZERO_WIDTH_RE.sub("", text)
    text = _DASH_RE.sub(" ", text)
    text = _SEPARATOR_RE.sub(" ", text)
    return _WS_RE.sub(" ", text).strip()


def _unit_present(text: str, phrase: str) -> bool:
    if len(phrase) <= 4 and " " not in phrase:
        return re.search(r"\b" + re.escape(phrase), text) is not None
    return phrase in text


def _count_active_units(
    text: str, interests_norm: str, units: tuple[tuple[str, str], ...]
) -> int:
    hits = 0
    for phrase, gate in units:
        if gate in interests_norm and _unit_present(text, phrase):
            hits += 1
    return hits


def _has_substance(text: str) -> bool:
    alnum = len(_TOKEN_RE.findall(text))
    words = _TOKEN_RE.findall(text)
    return alnum >= 60 and (bool(_DIGIT_RE.search(text)) or len(words) >= 12)


def _generic_topic_overlap(core_text: str, adjacent_text: str, text: str) -> bool:
    tweet_tokens = set(_WORD_RE.findall(text)) - _STOPWORDS
    if not tweet_tokens:
        return False
    for section in (core_text, adjacent_text):
        section_tokens = set(_WORD_RE.findall(section.casefold())) - _STOPWORDS
        if tweet_tokens & section_tokens:
            return True
    return False


def is_duplicate(draft_text: str, recent_texts: Sequence[str]) -> bool:
    """Near-identical recency check for a draft.

    Compares normalized text (case-folded, whitespace-collapsed,
    punctuation-insensitive, URLs/mentions/hashtags stripped) and the point
    made, not exact bytes. Empty or content-free drafts return True (flagged
    for rewrite, never proposed). Empty recent bodies never block.
    """
    if draft_text is None or not str(draft_text).strip():
        return True
    if _is_content_free(str(draft_text)):
        return True
    try:
        recents = list(recent_texts) if recent_texts is not None else []
    except TypeError:
        return False
    bodies: list[str] = []
    for item in recents:
        if item is None:
            continue
        text = str(item)
        if not text.strip():
            continue
        if not _normalize_for_dupe(text):
            continue
        bodies.append(text)
    if not bodies:
        return False
    draft_norm = _normalize_for_dupe(str(draft_text))
    draft_tokens = _dupe_tokens(str(draft_text))
    draft_numbers = _distinctive_numbers(str(draft_text))
    draft_cyrillic = bool(_CYRILLIC_RE.search(str(draft_text)))
    for body in bodies:
        norm = _normalize_for_dupe(body)
        if draft_norm and draft_norm == norm:
            return True
        recent_tokens = _dupe_tokens(body)
        if draft_tokens and recent_tokens:
            inter = draft_tokens & recent_tokens
            union = draft_tokens | recent_tokens
            jaccard = len(inter) / len(union) if union else 0.0
            smallest = min(len(draft_tokens), len(recent_tokens))
            containment = len(inter) / smallest if smallest else 0.0
            if jaccard >= 0.4 or containment >= 0.55:
                return True
        shared = draft_numbers & _distinctive_numbers(body)
        if shared:
            recent_cyrillic = bool(_CYRILLIC_RE.search(body))
            if draft_cyrillic != recent_cyrillic:
                return True
            if draft_tokens and recent_tokens:
                inter = draft_tokens & recent_tokens
                union = draft_tokens | recent_tokens
                jaccard = len(inter) / len(union) if union else 0.0
                smallest = min(len(draft_tokens), len(recent_tokens))
                containment = len(inter) / smallest if smallest else 0.0
                if jaccard >= 0.15 or containment >= 0.25:
                    return True
    return False


_URL_STRIP_RE = re.compile(r"https?://\S+|www\.\S+", re.IGNORECASE)
_MENTION_RE = re.compile(r"@[\w\u0400-\u04ff]+")
_HASHTAG_RE = re.compile(r"#[\w\u0400-\u04ff]+")
_PUNCT_RE = re.compile(r"[^a-z\u0400-\u04ff0-9\s]")
_WS_COLLAPSE_RE = re.compile(r"\s+")
_TOKEN_RE_DUPE = re.compile(r"[a-z\u0400-\u04ff0-9]+")
_NUMBER_RE = re.compile(r"\d+(?:[.,]\d+)?")
_CYRILLIC_RE = re.compile(r"[\u0400-\u04ff]")

_DUPE_STOPWORDS = frozenset(
    {
        "this", "that", "with", "from", "have", "been", "were", "will",
        "would", "there", "their", "about", "into", "your", "what", "when",
        "them", "then", "than", "also", "just", "like", "more", "most",
        "over", "such", "only", "very", "they",
        "and", "the", "for", "are", "was", "has", "had", "with", "are",
        "a", "an", "is", "it", "its", "as", "be", "to", "of", "in",
        "on", "at", "by", "we", "our", "you", "these", "those", "but",
        "can", "should", "could", "may", "might", "must", "shall", "do",
        "does", "did", "after", "before", "through", "during", "above",
        "below", "out", "off", "under", "again", "further", "once",
        "here", "where", "why", "how", "all", "any", "both", "each",
        "few", "other", "some", "own", "too",
    }
)


def _strip_noise(raw: str) -> str:
    text = raw.casefold()
    text = _URL_STRIP_RE.sub(" ", text)
    text = _MENTION_RE.sub(" ", text)
    text = _HASHTAG_RE.sub(" ", text)
    return text


def _normalize_for_dupe(raw: str) -> str:
    text = _strip_noise(raw)
    text = _PUNCT_RE.sub(" ", text)
    return _WS_COLLAPSE_RE.sub(" ", text).strip()


def _dupe_tokens(raw: str) -> set[str]:
    norm = _normalize_for_dupe(raw)
    return {
        token
        for token in _TOKEN_RE_DUPE.findall(norm)
        if len(token) >= 4 and token not in _DUPE_STOPWORDS
    }


def _is_content_free(raw: str) -> bool:
    stripped = _strip_noise(raw)
    tokens = [t for t in _TOKEN_RE_DUPE.findall(stripped) if len(t) >= 3]
    return len(tokens) < 3


def _distinctive_numbers(raw: str) -> set[str]:
    found: set[str] = set()
    for match in _NUMBER_RE.findall(raw):
        norm = match.replace(",", ".")
        digits = norm.replace(".", "")
        if len(digits) < 2 and "." not in norm:
            continue
        stripped = norm.lstrip("0").rstrip("0").strip(".") or "0"
        found.add(stripped)
    return found


def compose_draft(tweet: Tweet, interests_text: str) -> str:
    """SCAFFOLD (not implemented): draft a reply post adding something new.

    Must do: lead with one concrete observation or number, teaching tone,
    plain language with no INTERESTS.md hype words, abbreviations explained
    on first use; never praise-only, never a restatement of the source
    tweet; never over the X post length limit (rewrite/trim, never
    mid-word auto-truncate).
    Serves: R5 (draft half of the proposal; the link half comes from Tweet).
    Depends on: nothing (stdlib only).
    Depended on by: run.
    """
    raise NotImplementedError


def propose_tweet(tweet: Tweet, draft_text: str, ask: Callable[[str], str]) -> str:
    """SCAFFOLD (not implemented): propose one HIGH tweet via ask_human.

    Must do: call ``ask`` exactly once with both the tweet link and the
    draft text (a call missing either half is a bug — skip, don't retry
    as-is); never propose MEDIUM/LOW, empty-text, link-less, praise-only,
    restating, hype-worded, or over-limit drafts — rewrite or skip first;
    without an R4 pass verdict, propose nothing (fail closed); return the
    operator's answer verbatim for R6; tool failure is recorded as
    unproposed (never a decline, never a confirmation) and the batch
    continues.
    Serves: R5.
    Depends on: the ask_human tool (injected as ``ask``).
    Depended on by: run.
    """
    raise NotImplementedError


def parse_confirmation(answer_text: str, today: date) -> tuple[str, str] | None:
    """SCAFFOLD (not implemented): extract (reply_id, post_date) or None.

    Must do: a confirmation states the reply was posted AND supplies the
    posted reply id (bare numeric id or an x.com URL containing it);
    anything less — decline, ambiguity, "posted" with no id, malformed id —
    returns None (never invent an id); an explicit posting date in
    non-``YYYY-MM-DD`` shape returns None; no date at all uses ``today``.
    Serves: R6 (confirm-to-file gate).
    Depends on: nothing (stdlib only).
    Depended on by: persist_reply, run.
    """
    raise NotImplementedError


def persist_reply(
    source_url: str,
    source_body: str,
    posted_text: str,
    reply_id: str,
    post_date: str,
    replies_dir: Path = REPLIES_DIR,
) -> Path:
    """SCAFFOLD (not implemented): store one confirmed reply file.

    Must do: store the operator-confirmed posted text (not a stale draft)
    via M3 at ``<date>-<id>.md`` in the existing per-tweet format; empty
    posted text or a bad date/id writes nothing (error naming the value);
    unconfirmed drafts leave no trace in the replies dir; return the path
    written.
    Serves: R6.
    Depends on: reply_files.write_reply.
    Depended on by: run.
    """
    raise NotImplementedError


def run(
    ask: Callable[[str], str] | None = None,
    today: date | None = None,
    interests_text: str | None = None,
    recent_texts: Sequence[str] | None = None,
    state_snapshot: Mapping[str, str] | None = None,
) -> None:
    """One R1->R6 pass in order.

    R1 ensure+read watchlist; R2 fetch new tweets and persist state; read
    INTERESTS.md fresh once per run (abort proposals if missing/unreadable);
    R3 score each new tweet; read last-3-days reply texts via M3 (fail closed
    on unreadable); R4 drop near-identical drafts (intra-batch drafts
    deduped too); R5 one ask_human call per surviving HIGH tweet; R6 store
    each confirmed reply. Optional params are test seams; None means read
    the real KB paths.
    """
    from datetime import date as _date

    from fleet.tweet_watch.reply_files import list_recent, read_reply_text

    run_day = today if today is not None else _date.today()
    ask_fn = ask if ask is not None else (lambda prompt: "")

    handles = ensure_watchlist(Path(WATCHLIST_PATH))
    tweets = find_new_tweets(list(handles), Path(STATE_PATH))

    if interests_text is None:
        interests_path = Path(INTERESTS_PATH)
        try:
            interests_text = interests_path.read_text(encoding="utf-8")
        except OSError as exc:
            raise OSError(
                f"{interests_path}: cannot read INTERESTS.md: {exc}"
            ) from exc

    if recent_texts is None:
        replies_dir = Path(REPLIES_DIR)
        recent_paths = list_recent(replies_dir, run_day)
        recents: list[str] = [read_reply_text(p) for p in recent_paths]
    else:
        recents = list(recent_texts)

    seen_ids: set[str] = set()
    batch_drafts: list[str] = []
    failures: list[BaseException] = []
    for tweet in tweets:
        if tweet.id in seen_ids:
            continue
        seen_ids.add(tweet.id)
        label = score_tweet(tweet.text, interests_text)
        if label != "HIGH":
            continue
        draft = compose_draft(tweet, interests_text)
        if is_duplicate(draft, [*recents, *batch_drafts]):
            continue
        try:
            answer = propose_tweet(tweet, draft, ask_fn)
        except Exception as exc:  # noqa: BLE001 - batch continues, re-raised below
            logger.exception("proposal failed for tweet %s", tweet.id)
            failures.append(exc)
            continue
        batch_drafts.append(draft)
        try:
            confirmed = parse_confirmation(answer, run_day)
        except Exception:  # noqa: BLE001 - bad confirmation never stores
            logger.exception("confirmation parse failed for tweet %s", tweet.id)
            continue
        if confirmed is None:
            continue
        reply_id, post_date = confirmed
        persist_reply(
            tweet.url, tweet.text, draft, reply_id, post_date, Path(REPLIES_DIR)
        )
    if failures:
        raise failures[0]
