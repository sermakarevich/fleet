# fleet — Python supervisor for running coding agents in parallel

New here? Read [docs/OVERVIEW.md](docs/OVERVIEW.md) first.

<p align="center">
  <img src="assets/fleet_mini.png" alt="fleet logo">
</p>

<p align="center">
  <a href="https://docs.google.com/presentation/d/1O_pXyKdtpRG2ORD1xw7svifjpCol96wIVvOU6kOMDlI/edit?usp=sharing">
    <img src="https://img.shields.io/badge/Slides-fleet_overview-FBBC04?style=for-the-badge&logo=googleslides&logoColor=white" alt="Slides — fleet overview presentation">
  </a>
</p>

`fleet` is a lightweight Python supervisor that claims tasks from a
**centralized** [beads](https://github.com/gastownhall/beads) queue and runs
them in parallel through a coder (`claude`, `agy`, or `codex` CLI) in a headless loop. Each task
remembers the project working directory it was created in, plus an optional
per-task coder/model override, so a single supervisor can drive work across
many projects — and across multiple agent backends — spawning many concurrent agents - from one machine.

Fleet ships with a full-featured web UI (`fleet serve`) that covers the entire agent lifecycle — create and configure tasks, monitor live progress and logs, and answer questions from blocked agents, all from a single dashboard with four tabs: **Workers** (runs, schedules and a needs-attention strip), **Workflows** (definitions, runs, schedules), **Inbox** (questions waiting for a human) and **Settings** (every runtime knob).

- **Event triggers** — start a task on a signal (e.g. auto-investigate a blocked task); see [Triggers (start a task on a signal)](docs/OVERVIEW.md#triggers-start-a-task-on-a-signal).

## Documentation

Open the **Docs** tab in the web UI (`fleet serve`, http://localhost:7890/docs) or read the same pages here:

- [Overview](docs/OVERVIEW.md) — plain-language tour, life of one task
- [Concepts](docs/guide/concepts.md) — the vocabulary: bead, task, worker, coder, supervisor …
- [Getting started](docs/guide/getting-started.md) — install, first task, start the supervisor
- [How it works](docs/guide/how-it-works.md) — centralized model, blocked tasks, triage, epics, jobs
- [Command reference](docs/guide/commands.md)
- [Configuration](docs/CONFIG.md)
- [Telegram](docs/guide/telegram.md) — notifications, inbound tasks, answering from chat
- [ask_human broker](docs/guide/ask-human.md)
- [Coders](docs/guide/coders.md) — opencode, pi, Bedrock, writing your own
- [Development](docs/guide/development.md)
- [Architecture](docs/ARCHITECTURE.md) · [Worker contract](docs/WORKER_CONTRACT.md) · [Decisions (ADRs)](docs/adr/README.md)

## Quick start

```bash
git clone https://github.com/sermakarevich/fleet.git
uv tool install --editable ./fleet
fleet init                                  # initialize ~/.fleet
cd /path/to/your/project
fleet bd create --title "Implement feature X"
fleet run start                             # start the supervisor daemon
fleet serve start                           # web UI at http://localhost:7890
```

Full walkthrough: [Getting started](docs/guide/getting-started.md)
