# Coders

## opencode coder

The `opencode` coder runs the [opencode](https://opencode.ai) CLI locally and routes LLM inference to an Ollama instance on a remote GPU box ("rtx") through an SSH tunnel.

### Architecture

- **Binary:** `opencode` on your `PATH` (tested with v1.3.17 at `~/.opencode/bin/opencode`).
- **Backend:** Ollama on the rtx box, reached via an SSH tunnel: `127.0.0.1:11435` → `rtx:127.0.0.1:11434`. Port 11434 is reserved for a local Ollama install; fleet uses 11435.
- **Config injection:** Before each spawn, fleet writes/refreshes an `ollama-rtx` provider entry in the target project's `opencode.json`. This is how opencode discovers the remote Ollama — environment variables (`OPENCODE_CONFIG`, `OLLAMA_HOST`) are ignored by opencode 1.3.17.

### One-time setup

The supervisor brings the tunnel up automatically on start (`fleet run start` / `fleet run foreground`): it probes `127.0.0.1:11435` and, if nothing answers, runs `ssh -f -N -L 127.0.0.1:11435:127.0.0.1:11434 rtx` in the background. A failure is logged as a warning and does not stop the supervisor (claude/agy/codex tasks do not need Ollama). You can also do it by hand:

```bash
fleet tunnel          # ensure the tunnel is up; exit 1 if it cannot be started
```

Set `ollama_ssh_host` to use a different SSH host alias than `rtx` (`fleet config set ollama_ssh_host=gpubox`). The local port is taken from `opencode_ollama_url`; a non-loopback URL disables the tunnel step.

Alternatively, establish it once per session with `just` (or use VS Code's port-forward panel for port 11435):

```bash
just ollama-tunnel   # no-op if the tunnel is already up
```

To verify the backend is reachable:

```bash
curl http://127.0.0.1:11435/api/tags
```

### Default model

The default model is **`gpt-oss:20b`** — a 13 GB model that fits the RTX 4090 and supports tool calls. Other models available on rtx: `qwen3.5:27b`, `deepseek-r1:32b`, `gemma4:26b`, `gemma4:31b`, etc.

### Picking a different model per task

Pass `--coder opencode --model <name>` at create time:

```bash
fleet bd create --coder opencode --model "qwen3.5:27b" --title "Heavy refactor on qwen"
```

The model string is resolved as follows:
- Bare name (e.g. `qwen3.5:27b`) → `ollama-rtx/qwen3.5:27b`
- Full provider/model id (e.g. `ollama-rtx/deepseek-r1:32b`) → used verbatim
- Claude aliases (`sonnet`, `opus`, `haiku`) → replaced with `gpt-oss:20b` (fleet's global config default leaks these names into every coder)

### opencode_ollama_url config key

If your tunnel uses a different port or host, set the `opencode_ollama_url` config key:

```bash
fleet config set opencode_ollama_url=http://127.0.0.1:12345/v1
```

### opencode.json in your project

Fleet writes/refreshes an `ollama-rtx` provider entry in the target project's `opencode.json` before each spawn. Your other settings in that file (theme, other providers, etc.) are preserved. Whether to `gitignore` or commit `opencode.json` is up to you.

---

## pi coder

The `pi` coder runs the local `pi` CLI and emits JSON event lines (modelled on the opencode coder's event stream).

- Inference goes to the same local Ollama backend as the opencode coder. Before each spawn, fleet writes/refreshes a `pi-ollama` provider entry in the target project's `pi.json`.
- **Default model:** `qwen3.6:latest`.
- Pin a different model per task: `fleet bd create --coder pi --model <name> --title "..."`.

---

## Using AWS Bedrock models (opencode coder)

Fleet can route opencode tasks to **Claude on Amazon Bedrock** — Anthropic models
served through AWS — instead of the default Ollama backend.

### Model naming

Pass the full bedrock model id via `--model` with the `amazon-bedrock/` prefix:

```
fleet bd create --title "My task" --body-file spec.md -p 2 \
  --coder opencode --model "amazon-bedrock/us.anthropic.claude-sonnet-4-5-20250929-v1:0" \
  --cwd /path/to/repo
```

The inference-profile prefix (`us.` / `eu.` / `apac.`) must match the AWS region
in use.

### Credentials (three options, in order of preference)

1. **AWS profile / SSO** — `fleet config set opencode_bedrock_profile=<aws-profile>`
2. **Supervisor shell environment** — inherit `AWS_PROFILE`, `AWS_ACCESS_KEY_ID`,
   `AWS_SECRET_ACCESS_KEY`, etc. from your shell (works with zero fleet config).
3. **Bedrock API key** — set `AWS_BEARER_TOKEN_BEDROCK` in the supervisor's environment.

Region: `fleet config set opencode_bedrock_region=us-east-1` or inherit `AWS_REGION`.

### Settings

Bedrock routing uses the `opencode_bedrock_region`, `opencode_bedrock_profile`,
and `context_windows` keys — see [docs/CONFIG.md](../CONFIG.md) for defaults
and examples.

> **Bedrock usage costs real money per token** (unlike local Ollama).
> Missing or invalid AWS credentials surface as error events on the task —
> fleet performs no preflight check for credentials.

---

## Adding a custom coder

Fleet ships with five built-in coders (`claude`, `agy`, `codex`, `opencode`, `pi`), but you can
wrap any CLI agent in four small steps.

### Step 1 — Implement the `Coder` base class

Create a file in `src/fleet/coders/`, e.g. `src/fleet/coders/mycoder.py`:

```python
import json
from datetime import datetime, timezone
from pathlib import Path

from fleet.coders.base import Coder
from fleet.schemas import Event, Task

_TEMPLATES_DIR = Path(__file__).parent.parent / "templates"
_INSTRUCTION_PATH = _TEMPLATES_DIR / "INSTRUCTION.md"
_HEADER_PATH = _TEMPLATES_DIR / "coder_header.md.tmpl"


class MyCoder(Coder):
    name = "mycoder"          # unique name used in fleet bd create --coder
    context_limit = 128_000   # drives context-usage % logging

    def __init__(self, model: str = "my-default-model") -> None:
        self.model = model

    def build_argv(self, task: Task, task_dir: Path) -> list[str]:
        """Return the argv list passed to asyncio.create_subprocess_exec()."""
        artifacts_dir = task_dir / "artifacts"
        instructions = _INSTRUCTION_PATH.read_text(encoding="utf-8").strip()
        invocation_line = f"Invocation directory: {task.cwd}" if task.cwd else ""
        header = _HEADER_PATH.read_text(encoding="utf-8").format(
            task_id=task.id,
            task_title=task.title,
            task_description=task.description or "",
            task_dir=task_dir,
            invocation_line=invocation_line,
        ).strip()
        prompt = f"{header}\n\n---\n\n{instructions}"
        return ["mycli", "--model", self.model, "--json", prompt]

    def env(self, task: Task, task_dir: Path) -> dict[str, str]:
        """Return env-var overlay merged on top of os.environ before spawn.

        These two keys are REQUIRED — the agent reads them to locate its
        task directory and write STATE.md / RESULT.json.
        """
        return {
            "FLEET_TASK_ID": task.id,
            "FLEET_TASK_DIR": str(task_dir),
        }

    def normalize_event(self, raw_line: str) -> Event | None:
        """Parse one stdout line from the subprocess into a normalized Event.

        Return None for any line you want to discard.  Must be pure — no I/O.
        """
        if not raw_line.strip():
            return None
        try:
            data = json.loads(raw_line)
        except (json.JSONDecodeError, ValueError):
            return None
        ts = datetime.now(tz=timezone.utc)
        kind = data.get("type", "")
        if kind == "started":
            return Event(kind="session_started", raw=data, ts=ts)
        if kind == "finished":
            return Event(kind="session_ended", raw=data, ts=ts, usage=data.get("usage"))
        return None
```

**Contracts to honour:**
- `build_argv` — the last positional element is almost always the full prompt;
  construct it from the shared templates so the agent receives the Fleet task
  protocol and artifact-directory instructions.
- `env` — always emit `FLEET_TASK_ID`, `FLEET_TASK_DIR`;
  never put `ANTHROPIC_API_KEY` here (the CLI owns that).
- `normalize_event` — return `None` for anything you don't understand; the
  runner skips `None` events safely. Must be **pure** (no I/O, no logging).

### Step 2 — Register the coder

Add one line to `src/fleet/coders/__init__.py`:

```python
from fleet.coders.mycoder import MyCoder   # add this import

_REGISTRY: dict[str, type[Coder]] = {
    "claude":   ClaudeCoder,
    "agy":      AgyCoder,
    "codex":    CodexCoder,
    "mycoder":  MyCoder,    # add this entry
}
```

### Step 3 — Use your coder

```bash
# set as the default for all tasks
fleet config set coder=mycoder

# or pin it to individual tasks at creation time
fleet bd create --coder mycoder --model my-model --title "Task for my coder"
```

That's it — the supervisor discovers the coder through `_REGISTRY`, so no
further configuration is needed.
