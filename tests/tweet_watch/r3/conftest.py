"""Shared INTERESTS.md fixture for R3 scoring tests.

Mirrors the real /Users/sergii/.ai/knowledge/media/INTERESTS.md sections
(Core -> HIGH, Adjacent -> MEDIUM, LOW exclusions) so tests run without
the KB file present.
"""

import pytest

INTERESTS_TEXT = """# INTERESTS.md

## Core (score HIGH)

1. **AI agent harnesses and orchestration** — building/running fleets of
   autonomous coding agents: central task queues (beads), headless worker
   loops, supervisors, multi-harness setups.
   Signals: fleet, beads, harness, orchestrator, worker loops, swarms at scale.
2. **Coding agents and AI-assisted coding patterns** — opencode, Claude Code,
   model picks (Muse Spark, Claude Fable for design).
3. **Agent evaluation and verifier models** — TypeSafe Jev (typed answers with
   calibrated probabilities), post-interruption recovery (IHBench), eval
   harnesses, verifier models, release pipelines.
4. **Voice agents** — real-time voice pipelines: STT/TTS and turn-taking,
   latency engineering, speech-to-speech vs pipelined, telephony.
5. **Agentic cost engineering** — token economics of agent fleets at scale:
   tasks-per-dollar, cheap local models vs frontier models.

## Adjacent (score MEDIUM)

6. **Multi-agent swarms and agent societies** — swarm research, emergent
   coordination, collective memory.
7. **Agent memory and second brains** — memory layers, recall of the right
   context, linked personal knowledge for agents.
8. **AI in the enterprise** — AI workers inside real tools, applied AI
   anecdotes, technology trend outlooks.
9. **ML fundamentals with receipts** — KV cache vs inference memory, hybrid
   architectures, from people who build.

## LOW (usually skip)

- Pure price talk, memes, giveaways, engagement bait.
- Stock picking / finfluencer content (one-off exception, not an interest).
- Anything Sergii already replied to with the same point in the last 3 days.

## Voice notes for proposed replies

- Plain language, no hype words.
- Lead with one concrete observation or number, not praise.
- Teaching tone.
"""


@pytest.fixture
def interests_text() -> str:
    return INTERESTS_TEXT
