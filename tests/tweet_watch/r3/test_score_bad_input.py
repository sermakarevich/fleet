"""R3 failures F1, F2, F5: bad or missing input, non-English text."""

from fleet.tweet_watch.worker import score_tweet

LABELS = {"HIGH", "MEDIUM", "LOW"}


def test_f1_empty_text_scores_low(interests_text: str) -> None:
    assert score_tweet("", interests_text) == "LOW"


def test_f1_whitespace_only_scores_low(interests_text: str) -> None:
    assert score_tweet("   \n\t  ", interests_text) == "LOW"


def test_f1_empty_text_still_returns_label(interests_text: str) -> None:
    label = score_tweet("", interests_text)
    assert isinstance(label, str) and label in LABELS


def test_f2_missing_body_scores_low_without_fetch(interests_text: str) -> None:
    # M2 may return {id, handle, url} with no body (deleted/protected).
    # Scoring sees only the empty text; it never fetches the URL.
    assert score_tweet("", interests_text) == "LOW"


def test_f5_non_english_core_topic_scores_high(interests_text: str) -> None:
    text = (
        "Запустив fleet з headless worker loops: beads-черга роздає задачі, "
        "harness перезапускає впалі джоби, пропускна здатність зросла вдвічі."
    )
    assert score_tweet(text, interests_text) == "HIGH"


def test_f5_undecipherable_non_english_scores_low(interests_text: str) -> None:
    text = "Ой, щось там, гарний день, кава, бувайте всі"
    assert score_tweet(text, interests_text) == "LOW"
