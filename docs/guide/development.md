# Development

## Development

See [`docs/ARCHITECTURE.md`](../ARCHITECTURE.md) for the code map — how
`src/fleet/` is organized into `core`, `state`, `beads`, `orchestrator`,
`coders`, `integrations`, `observability`, `serve`, and `cli`, and where
each concept lives.

CI runs `just check` (ruff + pytest + UI build with tsc + vite build) on every push and pull request.
Run checks locally with `just check` (or `just check-all` to include the
integration suite). UI-only recipes: `just ui-build`, `just ui-check`,
`just ui-types`.
Enable the pre-commit hooks with `uv run pre-commit install`.
