# fleet — convenience commands. Run `just` to list them.

FLEET_HOME := env_var_or_default("FLEET_HOME", home_directory() / ".fleet")

# default: show available recipes
default:
    @just --list

# install / sync dependencies into .venv
sync:
    uv sync

# run the test suite
test *ARGS:
    uv run pytest {{ARGS}}

# lint: ruff check over source, tests and helper scripts
lint:
    uv run ruff check src tests bin

# format source, tests and helper scripts
fmt:
    uv run ruff format src tests bin

# fail if anything needs formatting
fmt-check:
    uv run ruff format --check src tests bin

# static types for the fleet package
typecheck:
    uv run mypy src

# one command that says "green": lint + format check + types + unit tests
check: lint fmt-check typecheck
    uv run pytest -q -p no:cacheprovider tests --ignore=tests/integration

# check plus the integration suite
check-all: check
    uv run pytest -q -p no:cacheprovider tests/integration

# initialize the centralized fleet home (~/.fleet by default, $FLEET_HOME otherwise)
init:
    uv run fleet init

# run the supervisor in the foreground (Ctrl-C to stop; coder comes from config)
run:
    uv run fleet run foreground

# manage the supervisor daemon: just supervisor start|stop|restart|status
supervisor cmd="status":
    uv run fleet run {{cmd}}

# manage the UI server daemon: just serve start|stop|restart|status
serve cmd="status":
    uv run fleet serve {{cmd}}

# list ready tasks
ready:
    uv run fleet ready

# show a task
show task_id:
    uv run fleet show {{task_id}}

# show runtime config
config:
    uv run fleet config show

# set runtime config key(s): just set max_concurrent=2 claim_poll_interval_sec=3
set +PAIRS:
    uv run fleet config set {{PAIRS}}

# shrink the beads dolt DB: export a JSONL safety copy, squash all history, GC
beads-gc:
    cd "${FLEET_HOME:-$HOME/.fleet}" && bd export -o "beads_export_$(date +%Y-%m-%d).jsonl" && bd flatten --force && bd gc --skip-decay --force

# remove build artefacts and caches (never the .venv itself)
clean:
    rm -rf .pytest_cache *.egg-info src/fleet/__pycache__ src/fleet/*/__pycache__ tests/__pycache__ tests/*/__pycache__

# install the web UI's node dependencies
ui-install:
    cd src/fleet/ui && npm install

# build the web UI and copy dist/ to $FLEET_HOME/ui_dist
ui-build: ui-install
    cd src/fleet/ui && npm run build
    mkdir -p "{{FLEET_HOME}}"
    rm -rf "{{FLEET_HOME}}/ui_dist"
    cp -r src/fleet/ui/dist "{{FLEET_HOME}}/ui_dist"
    @echo "UI built → {{FLEET_HOME}}/ui_dist"

# typecheck the web UI without emitting output
ui-check:
    cd src/fleet/ui && npx tsc --noEmit

# run the Vite dev server with hot reload (for working on the UI itself)
ui-dev:
    cd src/fleet/ui && npm run dev

# establish the ssh tunnel to rtx ollama (local 11435 -> rtx 11434); no-op if already up
ollama-tunnel:
    @curl -s --max-time 2 http://127.0.0.1:11435/api/tags > /dev/null 2>&1 && echo "tunnel already up (127.0.0.1:11435)" || (ssh -f -N -o ExitOnForwardFailure=no -L 11435:127.0.0.1:11434 rtx && echo "tunnel established (127.0.0.1:11435 -> rtx:11434)")
