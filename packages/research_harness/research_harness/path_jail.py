"""Confine caller-supplied filesystem paths to one tree.

On a shared host RH runs under a service account that can read its own
installation and the admin git mirrors; the people calling it cannot, and must
not be able to borrow that account's eyes by naming one of those paths in a
tool argument or a CLI flag. ``RH_PATH_JAIL`` names the only tree a caller may
point at — the multi-tenant launcher sets it to the caller's home. Unset (every
single-user machine) means no jail, so developer workflows are untouched.

The check is on *caller-supplied* values only. RH's own internal paths never
pass through here, and free-text arguments are not scanned: only values whose
argument name says "this is a path" are, so prose that happens to contain a
slash is never refused.
"""

from __future__ import annotations

import os
import re
from collections.abc import Iterable, Mapping
from pathlib import Path

__all__ = ["PathJailError", "jail_root", "check_path", "check_arguments", "check_argv"]

# Argument names that denote a filesystem location. Derived from the public MCP
# schemas and the `rh` CLI options, matched as whole words on "_"-separated
# names so `code_path`, `output_dir`, `deposit_root` and `--target-file` all hit
# while `direction` and `root_collection` do not.
_PATH_WORDS = frozenset(
    {"path", "paths", "dir", "dirs", "root", "file", "files", "source", "filename"}
)

_URL_SCHEMES = ("http://", "https://", "ftp://", "doi:", "arxiv:", "s3://")

# A bare DOI is an identifier that happens to contain a slash, and `source` is a
# path word, so `paper_ingest` on `10.1038/s41586-021-03819-2` was refused on every
# jailed host while the same paper by URL or arXiv id went through. Only an ingest
# `source` in the registered form is exempt, with no traversal in the suffix, and only
# while nothing on disk carries its prefix's name: a link planted as `10.1234` would
# otherwise carry a path spelled like a DOI out of the jail unresolved.
_DOI_RE = re.compile(r"^10\.\d{4,9}/[^\s/]\S*$")
_IDENTIFIER_NAMES = frozenset({"source"})


def _is_doi_source(name: str | None, text: str) -> bool:
    if str(name or "").replace("-", "_").lower() not in _IDENTIFIER_NAMES:
        return False
    if not _DOI_RE.match(text) or ".." in text:
        return False
    return not os.path.lexists(os.path.expanduser(text.split("/", 1)[0]))


class PathJailError(ValueError):
    """A caller-supplied path resolved outside ``RH_PATH_JAIL``."""


def jail_root() -> Path | None:
    """The tree callers are confined to, or None when no jail is configured."""
    raw = os.environ.get("RH_PATH_JAIL", "").strip()
    if not raw:
        return None
    return Path(raw).expanduser().resolve()


def _is_path_name(name: str) -> bool:
    return bool(_PATH_WORDS & set(str(name).replace("-", "_").lower().split("_")))


def _looks_like_path(value: str) -> bool:
    text = value.strip()
    if not text or text.lower().startswith(_URL_SCHEMES):
        return False
    return text.startswith(("/", "~", "./", "../")) or "/" in text


def check_path(value: str, *, where: str = "argument", name: str | None = None) -> None:
    """Refuse ``value`` when a jail is configured and the path escapes it."""
    root = jail_root()
    if root is None or not isinstance(value, str) or not _looks_like_path(value):
        return
    if _is_doi_source(name, value.strip()):
        return
    # Resolve symlinks and ".." the same way the shell guard does, so neither a
    # link planted inside the jail nor a traversal reaches out of it.
    resolved = Path(os.path.realpath(os.path.expanduser(value.strip())))
    if resolved != root and root not in resolved.parents:
        raise PathJailError(
            f"refused: {where} points outside {root}. "
            "Paths must stay inside your own working tree."
        )


def check_arguments(arguments: Mapping[str, object], *, tool: str = "tool") -> None:
    """Walk a tool-argument mapping and refuse path values that escape the jail."""
    if jail_root() is None:
        return

    def walk(name: str, value: object) -> None:
        if isinstance(value, Mapping):
            for key, sub in value.items():
                walk(str(key), sub)
        elif isinstance(value, str):
            if _is_path_name(name):
                check_path(value, where=f"{tool} argument {name!r}", name=name)
        elif isinstance(value, Iterable) and not isinstance(value, (bytes, bytearray)):
            for item in value:
                walk(name, item)

    for key, value in arguments.items():
        walk(str(key), value)


def check_argv(argv: Iterable[str], *, prog: str = "rh") -> None:
    """Refuse escaping paths in a command line, in both ``--opt V`` and ``--opt=V``."""
    if jail_root() is None:
        return
    pending: str | None = None
    for raw in argv:
        if raw.startswith("--") and "=" in raw:
            name, _, value = raw[2:].partition("=")
            pending = None
            if _is_path_name(name):
                check_path(value, where=f"{prog} {raw.split('=')[0]}", name=name)
        elif raw.startswith("-"):
            pending = raw.lstrip("-") if _is_path_name(raw.lstrip("-")) else None
        else:
            if pending is not None:
                check_path(raw, where=f"{prog} --{pending}", name=pending)
            pending = None
