"""Runs: one execution of a flow (docs/27_sep_upgrade/DESIGN.md §3.4).

store.py owns `$FLEET_HOME/runs.db` (tables `runs`, `step_runs`);
run_dir.py owns the run folder on disk (`flow.yaml` copy, one step
directory per step run); state.py builds the template context from a
run's inputs and its steps' outputs. Imports `core`, `state` and `flows`.
"""
