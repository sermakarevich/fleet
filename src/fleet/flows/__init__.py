"""Flows: YAML-defined graphs of steps (docs/27_sep_upgrade/DESIGN.md §3.2).

A flow is one YAML file: named steps, `needs` edges, inputs, and `on:`
(what starts it). model.py holds the frozen dataclasses and validation;
templates.py renders `{{ ... }}` text; tools.py holds declared executables;
graph.py answers "which steps and items are ready"; folders.py reads flow
and tool files from an ordered list of folders. This package imports `core`
only; `runs`, `pool`, the supervisor, `serve` and `cli` import it.
"""
