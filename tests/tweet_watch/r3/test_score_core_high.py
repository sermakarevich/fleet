"""R3: core topics score HIGH; labels are reproducible."""

from fleet.tweet_watch.worker import score_tweet


def test_harness_tweet_scores_high(interests_text: str) -> None:
    text = (
        "Shipped a fleet of headless coding-agent worker loops draining a "
        "central beads queue with a supervisor retrying failed tasks. "
        "Throughput doubled once the orchestrator batched independent jobs."
    )
    assert score_tweet(text, interests_text) == "HIGH"


def test_coding_agent_pattern_scores_high(interests_text: str) -> None:
    text = (
        "Pattern that scales for me with opencode and Claude Code: one "
        "autonomous agent per bead, model pick Muse Spark for code and "
        "Claude Fable for design review."
    )
    assert score_tweet(text, interests_text) == "HIGH"


def test_verifier_model_scores_high(interests_text: str) -> None:
    text = (
        "TypeSafe Jev gives typed answers with calibrated probabilities; "
        "our eval harness gates releases on its verifier verdict, and "
        "post-interruption recovery (IHBench) is tracked as a separate skill."
    )
    assert score_tweet(text, interests_text) == "HIGH"


def test_voice_agent_scores_high(interests_text: str) -> None:
    text = (
        "Voice agent latency breakdown from today's calls: STT 180ms, "
        "turn-taking 120ms, TTS 240ms streaming. Pipelined beats "
        "speech-to-speech on telephony so far."
    )
    assert score_tweet(text, interests_text) == "HIGH"


def test_cost_engineering_scores_high(interests_text: str) -> None:
    text = (
        "Cost engineering our agent fleet: 42 tasks-per-dollar on cheap "
        "local models vs 3 on frontier models for the same repair queue."
    )
    assert score_tweet(text, interests_text) == "HIGH"


def test_same_inputs_same_label(interests_text: str) -> None:
    text = (
        "Shipped a fleet of headless coding-agent worker loops draining a "
        "central beads queue with a supervisor retrying failed tasks."
    )
    first = score_tweet(text, interests_text)
    second = score_tweet(text, interests_text)
    assert first == second == "HIGH"
