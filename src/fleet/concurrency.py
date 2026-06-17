def parse_overrides(raw: str) -> dict[str, int]:
    """Parse "claude:2,opencode:4" into {"claude": 2, "opencode": 4}.

    Blank or malformed entries and non-positive counts are ignored.
    """
    result: dict[str, int] = {}
    for part in raw.split(","):
        part = part.strip()
        if not part or ":" not in part:
            continue
        name, _, value = part.partition(":")
        name = name.strip()
        try:
            count = int(value.strip())
        except ValueError:
            continue
        if name and count > 0:
            result[name] = count
    return result


def cap_for_coder(coder: str, max_concurrent: int, overrides: str) -> int:
    """Concurrency cap for `coder`: its override if listed, else `max_concurrent`."""
    return parse_overrides(overrides).get(coder, max_concurrent)


def running_by_coder(tasks, default_coder: str) -> dict[str, int]:
    """Count how many of `tasks` run under each coder.

    `tasks` is any iterable of objects with a `.coder` attribute (None means
    the task uses the default coder).
    """
    counts: dict[str, int] = {}
    for task in tasks:
        coder = getattr(task, "coder", None) or default_coder
        counts[coder] = counts.get(coder, 0) + 1
    return counts
