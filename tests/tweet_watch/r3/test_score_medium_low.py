"""R3: adjacent topics score MEDIUM, everything else LOW."""

from fleet.tweet_watch.worker import score_tweet


def test_swarm_research_scores_medium(interests_text: str) -> None:
    text = (
        "New swarm research preprint: emergent coordination in multi-agent "
        "societies via collective memory of past negotiations."
    )
    assert score_tweet(text, interests_text) == "MEDIUM"


def test_agent_memory_scores_medium(interests_text: str) -> None:
    text = (
        "Notes on agent memory layers: recall of the right context beats a "
        "bigger window; linked personal knowledge graphs for second brains."
    )
    assert score_tweet(text, interests_text) == "MEDIUM"


def test_enterprise_ai_scores_medium(interests_text: str) -> None:
    text = (
        "Applied AI anecdote: an AI worker inside our reporting tool cleared "
        "a backlog analysts called impossible, plus a technology trend "
        "outlook for next year."
    )
    assert score_tweet(text, interests_text) == "MEDIUM"


def test_ml_fundamentals_scores_medium(interests_text: str) -> None:
    text = (
        "KV cache vs inference memory, from someone who builds: hybrid "
        "attention architectures cut serving memory 30% on long contexts."
    )
    assert score_tweet(text, interests_text) == "MEDIUM"


def test_price_talk_scores_low(interests_text: str) -> None:
    assert score_tweet("BTC to $200k by Friday, who is buying?", interests_text) == "LOW"


def test_meme_giveaway_scores_low(interests_text: str) -> None:
    text = "Retweet to win 1 ETH giveaway, tag 3 friends, moon soon 🚀🚀"
    assert score_tweet(text, interests_text) == "LOW"


def test_unrelated_topic_scores_low(interests_text: str) -> None:
    text = "My sourdough starter finally doubled after three weeks of feeding."
    assert score_tweet(text, interests_text) == "LOW"
