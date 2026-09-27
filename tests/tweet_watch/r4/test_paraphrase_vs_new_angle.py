"""R4 recency dedupe, paraphrase vs new angle (F7/F10/F11).

Unit under test: fleet.tweet_watch.worker.is_duplicate.
"""

from __future__ import annotations

from fleet.tweet_watch.worker import is_duplicate

VERIFIER_BODY = (
    "Verifier models cut false approves. We saw 30% fewer bad merges "
    "after adding a second-pass verifier to the merge queue."
)


def test_f7_paraphrase_same_claim_same_evidence_blocked() -> None:
    draft = (
        "A second-pass verifier trimmed our bad merges by about a third — "
        "roughly 30% fewer false approves since we added it to the queue."
    )
    assert is_duplicate(draft, [VERIFIER_BODY]) is True


def test_f7_same_topic_with_new_number_passes() -> None:
    draft = (
        "On the verifier thread, the number that matters here is cost: "
        "$0.004 per verified task at our volume, measured over last "
        "week's merges — not in any earlier reply."
    )
    assert is_duplicate(draft, [VERIFIER_BODY]) is False


def test_f10_shared_generic_words_do_not_block() -> None:
    recent = ["Evals matter for agent quality.", "Costs add up at scale."]
    draft = (
        "I set a 60s default timeout on every tool call in the harness; "
        "it bounds the worst case without touching quality."
    )
    assert is_duplicate(draft, recent) is False


def test_f11_old_point_plus_new_material_flagged_for_rewrite() -> None:
    # Must not pass as-is (cut the repeated paragraph), not dropped outright.
    draft = (
        VERIFIER_BODY + "\n\nNew number on top: p95 verification latency is 1.8s "
        "per task at our volume."
    )
    assert is_duplicate(draft, [VERIFIER_BODY]) is True
