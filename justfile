# fleet — convenience commands. Run `just` to list them.

# default: show available recipes
default:
    @just --list

# install / sync dependencies into .venv
sync:
    uv sync

# run the test suite
test *ARGS:
    uv run pytest {{ARGS}}

# initialize the centralized fleet home (~/.fleet by default, $FLEET_HOME otherwise)
init:
    uv run fleet init

# start the supervisor (default coder: claude)
run coder="claude":
    uv run fleet run --coder {{coder}}

# start the supervisor and exit when the queue drains
run-once coder="claude":
    uv run fleet run --coder {{coder}} --once

# list ready tasks
ready:
    uv run fleet ready

# show a task
show task_id:
    uv run fleet show {{task_id}}

# show runtime config
config:
    uv run fleet config show

# set runtime config key(s): just set max_concurrent=2 retry_limit=5
set +PAIRS:
    uv run fleet config set {{PAIRS}}

# remove build artefacts and caches
clean:
    rm -rf .pytest_cache .venv *.egg-info src/fleet/__pycache__ src/fleet/*/__pycache__ tests/__pycache__ tests/*/__pycache__
