"""Flow `{{ ... }}` template rendering (DESIGN.md §3.2).

Renders flow-file templates over a run context built in
``fleet.runs.state``::

    {"inputs": {...}, "steps": {name: {"outputs": {...}, "items": [...]}},
     "item": Any, "index": int, "run": {"id": str, "date": str},
     "defaults": {...}, "args": {...}}

One module-level :class:`jinja2.sandbox.SandboxedEnvironment` with
``StrictUndefined`` backs every function; only Jinja built-in filters
(``default``, ``lower``, ``upper``, ``map``, ``list``, ``join``,
``tojson``, ``length``) are available, plus the ``read_file(path)``
global (absolute paths only, UTF-8 text, capped at
``READ_FILE_MAX_BYTES`` bytes). Every Jinja failure surfaces as
``fleet.core.errors.TemplateError`` naming the offending template.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import jinja2.sandbox
from jinja2 import StrictUndefined
from jinja2.exceptions import (
    SecurityError,
    TemplateRuntimeError,
    TemplateSyntaxError,
    UndefinedError,
)

from fleet.core.errors import TemplateError

Context = Mapping[str, Any]
"""Documented shape of a template context (built in ``fleet.runs.state``)."""

_FALSE_WORDS = frozenset({"false", "off", "no", "0", ""})
_TRUE_WORDS = frozenset({"true", "on", "yes", "1"})

_ENV = jinja2.sandbox.SandboxedEnvironment(
    undefined=StrictUndefined,
    autoescape=False,
    keep_trailing_newline=True,
)

READ_FILE_MAX_BYTES = 200_000
"""Largest file ``read_file`` will return, in bytes."""


def read_file(path: str) -> str:
    """Read the UTF-8 text file at absolute ``path`` for use in a template.

    Relative paths are rejected; a missing, unreadable, or undecodable
    file and an oversized file all raise :class:`TemplateError`. This is
    the only filesystem access available inside templates.
    """
    if not isinstance(path, str) or not os.path.isabs(path):
        raise TemplateError(f"read_file: path must be absolute: {path}")
    try:
        if os.path.getsize(path) > READ_FILE_MAX_BYTES:
            raise TemplateError(f"read_file: {path} is larger than {READ_FILE_MAX_BYTES} bytes")
        data = Path(path).read_bytes()
    except OSError as exc:
        raise TemplateError(f"read_file: cannot read {path}: {exc.strerror or exc}") from exc
    if len(data) > READ_FILE_MAX_BYTES:
        raise TemplateError(f"read_file: {path} is larger than {READ_FILE_MAX_BYTES} bytes")
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise TemplateError(f"read_file: cannot read {path}: {exc}") from exc


_ENV.globals["read_file"] = read_file


def _describe(template_text: str) -> str:
    """Quote the first 80 chars of a template for error messages."""
    return repr(template_text[:80])


def _wrap(template_text: str, error: Exception) -> TemplateError:
    """Build a TemplateError naming the template and the original message."""
    return TemplateError(f"cannot render template {_describe(template_text)}: {error}")


def is_template(text: str) -> bool:
    """Return True when ``text`` contains a ``{{`` or ``{%`` marker."""
    return "{{" in text or "{%" in text


def render(text: str, ctx: Context) -> str:
    """Render ``text`` as a template over ``ctx``; always returns a string."""
    try:
        return _ENV.from_string(text).render(**dict(ctx))
    except (TemplateSyntaxError, UndefinedError, SecurityError, TemplateRuntimeError) as exc:
        raise _wrap(text, exc) from exc


def render_value(text: str, ctx: Context) -> Any:
    """Evaluate ``text`` over ``ctx``, preserving the Python value.

    When ``text`` (stripped) is exactly one ``{{ expr }}`` expression,
    evaluate the expression and return its value (list, dict, bool, int,
    str, ...). Otherwise behave like :func:`render` and return a string.
    """
    stripped = text.strip()
    if (
        stripped.startswith("{{")
        and stripped.endswith("}}")
        and stripped.count("{{") == 1
        and stripped.count("}}") == 1
    ):
        expression = stripped[2:-2]
        try:
            compiled = _ENV.compile_expression(expression, undefined_to_none=False)
            return compiled(**dict(ctx))
        except (TemplateSyntaxError, UndefinedError, SecurityError, TemplateRuntimeError) as exc:
            raise _wrap(text, exc) from exc
    return render(text, ctx)


def render_bool(text: bool | str, ctx: Context) -> bool:
    """Render ``text`` as a boolean condition over ``ctx``.

    Bools pass through; strings go through :func:`render_value`, then a
    bool returns itself, ``true/on/yes/1`` (case-insensitive) is True,
    ``false/off/no/0/""`` is False, and anything else raises TemplateError.
    """
    if isinstance(text, bool):
        return text
    value = render_value(text, ctx)
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in _TRUE_WORDS:
            return True
        if lowered in _FALSE_WORDS:
            return False
    raise TemplateError(f"cannot interpret template {_describe(text)} as bool: {value!r}")


def render_mapping(values: Mapping[str, str], ctx: Context) -> dict[str, str]:
    """Render each value of ``values`` over ``ctx`` via :func:`render`."""
    return {key: render(item_text, ctx) for key, item_text in values.items()}
