# ask_human broker

## The ask_human question broker (bundled MCP server)

Headless agents have no built-in way to ask you anything — Claude Code filters the `AskUserQuestion` tool out of `claude -p` sessions. Fleet's agents instead call the `ask_human_question` MCP tool, which records the question in a shared SQLite store and **blocks the agent until a human answers** from any frontend. Fleet bundles this broker as `fleet.ask_human` (vendored from the standalone agent-chat project), so a fleet install is self-contained.

```
 fleet agent ──── ask_human_question("Deploy?", ["yes","no"])
      │                                              ▲
      ▼  INSERT pending row, then block-poll         │ {"answer": "yes"}
 ┌──────────────────────┐     ┌──────────────────┐  │
 │ fleet ask-human serve │ ──► │ SQLite questions │ ──┘
 │ (MCP server, stdio)   │     │ table (WAL)      │
 └──────────────────────┘     └──────────────────┘
                                  ▲           ▲
                       web UI inbox tab    Telegram reply
                        fleet ask-human     (see section above)
```

The SQLite store is the single source of truth; every frontend is a thin client. Answering is an atomic `UPDATE … WHERE status='pending'`, so the first responder wins and channels can never double-answer.

### Setup

Register the bundled server with Claude Code once (requires the `claude` CLI on
your `PATH`):

```bash
fleet ask-human install        # remove + claude mcp add ask_human --scope user -- fleet ask-human serve
claude mcp list                # verify
```

Use `--scope project` or `--scope local` to register at a different Claude Code
scope (default is `user`).

Agents spawned by the fleet supervisor pick up the user-scope registration automatically. If you previously registered an `ask_human` server from another location, `install` replaces that registration (the other copy's files are left untouched — both point at the same DB).

### Answering questions

Every frontend writes to the same store, so use whichever is closest:

- **Fleet web UI** — the Inbox tab in `fleet serve` (questions appear live). Use this as your primary interface.
- **Telegram** — reply to the question notification (see [Answering chat questions from Telegram](telegram.md#answering-chat-questions-from-telegram)).

On an options question the operator is never boxed in: a free-text `note` can supplement or replace the selection, and agents are instructed to treat it as authoritative.

### Configuration

| Env | Default | Purpose |
|-----|---------|---------|
| `ASK_HUMAN_DB` | `~/.claude/ask_human/questions.db` | shared SQLite file (set the same for server + frontends) |
