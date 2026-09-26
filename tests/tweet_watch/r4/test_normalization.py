"""R4 recency dedupe, normalization (F4-F6). Unit under test: fleet.tweet_watch.worker.is_duplicate."""

from __future__ import annotations

from fleet.tweet_watch.worker import is_duplicate

VERIFIER_BODY = (
    "Verifier models cut false approves. We saw 30% fewer bad merges "
    "after adding a second-pass verifier to the merge queue."
)


def test_f6_case_whitespace_punctuation_only_differences_blocked() -> None:
    draft = (
        "  VERIFIER models cut FALSE approves...\n"
        "We saw   30% fewer bad merges\nafter adding a second-pass "
        "verifier to the merge queue!!! "
    )
    assert is_duplicate(draft, [VERIFIER_BODY]) is True


def test_f5_swapped_link_blocked() -> None:
    recent = VERIFIER_BODY + " Details: https://x.com/someone/status/123 #evals"
    draft = VERIFIER_BODY + " Details: https://x.com/other/status/999 #ml"
    assert is_duplicate(draft, [recent]) is True


def test_f5_swapped_handle_blocked() -> None:
    recent = VERIFIER_BODY + " cc @typesafeai"
    draft = VERIFIER_BODY + " cc @cloneisjun"
    assert is_duplicate(draft, [recent]) is True


def test_f4_same_point_in_different_language_blocked() -> None:
    # Translation is not a new angle: same claim, same evidence.
    draft_uk = (
        "Моделі-верифікатори зменшують кількість хибних схвалень: після "
        "додавання верифікатора другим проходом у чергу злиттів ми "
        "побачили на 30% менше поганих злиттів."
    )
    assert is_duplicate(draft_uk, [VERIFIER_BODY]) is True


def test_f4_new_angle_in_different_language_passes() -> None:
    # Guards against an implementation that blocks all non-English text.
    draft_uk = (
        "Щодо верифікаторів, нове спостереження: вартість перевірки "
        "становить $0,004 на завдання при нашому обсязі, виміряно за "
        "злиттями минулого тижня."
    )
    assert is_duplicate(draft_uk, [VERIFIER_BODY]) is False
