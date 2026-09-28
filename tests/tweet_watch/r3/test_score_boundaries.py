"""R3 failures F6-F11: boundary values."""

from fleet.tweet_watch.worker import score_tweet


def test_f6_core_content_with_bait_tail_stays_high(interests_text: str) -> None:
    text = (
        "Fleet worker-loop postmortem: batching independent beads cut "
        "orchestrator idle time 40%, supervisor retries converged in two "
        "rounds. Details below — also doing a small sticker giveaway, "
        "retweet to enter!"
    )
    assert score_tweet(text, interests_text) == "HIGH"


def test_f6_pure_giveaway_with_buzzword_scores_low(interests_text: str) -> None:
    text = "Retweet to win! AI agent course + $500 giveaway, follow and tag!"
    assert score_tweet(text, interests_text) == "LOW"


def test_f7_swarm_with_worker_loops_scores_high(interests_text: str) -> None:
    text = (
        "Swarm post with numbers: our worker loops drain a shared beads "
        "queue at 120 tasks-per-hour with a fleet supervisor rebalancing."
    )
    assert score_tweet(text, interests_text) == "HIGH"


def test_f7_enterprise_with_eval_numbers_scores_high(interests_text: str) -> None:
    text = (
        "Enterprise rollout writeup: the eval harness gates deploys on "
        "TypeSafe Jev verifier verdicts, recovery score up 18 points."
    )
    assert score_tweet(text, interests_text) == "HIGH"


def test_f7_pure_adjacent_framing_stays_medium(interests_text: str) -> None:
    text = (
        "Swarm research thoughts: emergent coordination patterns in "
        "multi-agent societies and how collective memory might evolve."
    )
    assert score_tweet(text, interests_text) == "MEDIUM"


def test_f7_deterministic_on_boundary(interests_text: str) -> None:
    text = (
        "Swarm post with numbers: our worker loops drain a shared beads "
        "queue at 120 tasks-per-hour with a fleet supervisor rebalancing."
    )
    assert score_tweet(text, interests_text) == score_tweet(text, interests_text)


def test_f8_bare_kv_cache_is_medium_not_high(interests_text: str) -> None:
    assert score_tweet("KV cache", interests_text) == "MEDIUM"


def test_f8_bare_fleet_is_medium_not_high(interests_text: str) -> None:
    assert score_tweet("fleet", interests_text) == "MEDIUM"


def test_f8_bare_price_meme_is_low(interests_text: str) -> None:
    assert score_tweet("BTC moon 🚀", interests_text) == "LOW"


def test_f9_long_thread_substance_at_end_scores_high(interests_text: str) -> None:
    filler = "Day %d of shipping: standup notes, small fixes, docs. " * 120
    tail = (
        "And the real lesson: pipelined STT/TTS with streaming cut our "
        "voice agent turn-taking latency from 900ms to 420ms on telephony."
    )
    assert score_tweet(filler + tail, interests_text) == "HIGH"


def test_f10_content_free_agreement_scores_low(interests_text: str) -> None:
    assert score_tweet("+1, exactly this", interests_text) == "LOW"


def test_f10_quote_link_without_content_scores_low(interests_text: str) -> None:
    text = "this 👇 https://x.com/someone/status/1234567890"
    assert score_tweet(text, interests_text) == "LOW"


def test_f11_low_exclusion_beats_adjacent_match(interests_text: str) -> None:
    text = (
        "My stock picks for next quarter: three finfluencer favorites, plus "
        "how AI in the enterprise lifts their margins."
    )
    assert score_tweet(text, interests_text) == "LOW"
