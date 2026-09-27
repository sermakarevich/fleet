# tweet_watch — final gate (autocode step 11/11)

Date: 2026-09-27. Branch: `autocode/tweet_watch`.

## Commands

- `uv run ruff check src tests bin` → All checks passed (was 87 findings, all in
  `src/fleet/tweet_watch` + `tests/tweet_watch`; `main` worktree verified clean).
- `uv run ruff format --check src/fleet/tweet_watch tests/tweet_watch` →
  113 files already formatted. (Repo-wide `--check` still lists the same 17
  pre-existing drifts as `main`; untouched.)
- `uv run mypy src` → 3 errors, all pre-existing on `main` (verified identical
  in a `main` worktree with the same toolchain) in files this branch does not
  touch: `workflows/builders/sources.py:335`, `workflows/builders/__init__.py:59`,
  `cli/tasks.py:151`. The one error in this branch's code
  (`tweet_watch/worker.py:279`) was fixed. Left the 3 alone: with
  `warn_unused_ignores` they look like local-toolchain (mypy 2.3.1 / py3.14 vs
  CI py3.12) artifacts, and "fixing" them risks breaking CI.
- `uv run pytest -q -p no:cacheprovider tests --ignore=tests/integration` →
  **2886 passed** in ~79s. Zero failures; BASELINE.md allowed-reds: none needed.
- `uv run pytest tests/tweet_watch -q -p no:cacheprovider` → **490 passed**.

## Fixes made at the gate (code only, no test semantics changed)

- `worker.py`: extracted `_fetch_candidates` / `_select_fresh` / `_merge_maxima`
  (PLR0912), merged two MEDIUM paths in `score_tweet` (PLR0911), extracted
  `_DraftFeatures` / `_matches_recent_body` / `_token_overlap_hits` from
  `is_duplicate` (PLR0911), extracted `_confirmation_date` from
  `parse_confirmation` (PLR0911), named all magic-value constants (PLR2004),
  annotated `sections` (mypy).
- `x_fetch.py`: extracted `_register_handles` / `_run_check` / `_parse_check_output` /
  `_select_wanted` / `_parse_record` (PLR0912/PLR0915), named stderr-tail limit,
  explicit `check=False` (PLW1510, returncode handled below).
- `tests/tweet_watch` (style only): import sorting (I001), `ruff format`
  rewraps, missing `from pathlib import Path` import (F821), function-level
  imports moved to top (PLC0415), `strict=False` on two `zip`s (B017→B905:
  behavior unchanged), `contextlib.suppress` (SIM105), bound-method instead of
  lambda (PLW0108), f-string (UP031), byte literals (UP012), alias from-imports
  (PLR0402), removed one unused import (F401), `noqa: B017` on four
  `pytest.raises(Exception)` (broad-exception assertion is the test's intent).

## Result

Gate: **green**. Full suite 2886 passed, tweet_watch 490 passed, lint clean,
format clean on branch files, typecheck clean on branch files.

Code-green sha: `b134e1c8e4db8672160006a3092a5832e094d67d`
(full suite + lint + types verified on this tree; this file only adds docs).
Gate-record commit: the commit carrying this file
(`git log --oneline -1 -- docs/tweet_watch/GATE.md`); exact sha in outputs.json.
