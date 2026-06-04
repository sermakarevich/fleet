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

# remove build artefacts and caches
clean:
    rm -rf .pytest_cache .venv *.egg-info src/fleet/__pycache__ src/fleet/*/__pycache__ tests/__pycache__ tests/*/__pycache__
