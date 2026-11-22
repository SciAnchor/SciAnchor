"""从 argparse 命令树生成机器可读的 CLI 契约。"""

from __future__ import annotations

import argparse
from enum import Enum
from pathlib import Path
from typing import Any


_RUNTIME_FLAGS = {
    "environment",
    "env_file",
    "no_progress",
    "log_mode",
    "log_level",
    "log_file",
    "event_file",
    "verbose",
    "debug",
}


def _subcommands(parser: argparse.ArgumentParser) -> dict[str, argparse.ArgumentParser]:
    for action in parser._actions:
        if isinstance(action, argparse._SubParsersAction):
            return dict(action.choices)
    return {}


def _find(parser: argparse.ArgumentParser, path: list[str]) -> argparse.ArgumentParser:
    current = parser
    for part in path:
        choices = _subcommands(current)
        if part not in choices:
            available = ", ".join(sorted(choices)) or "无"
            raise ValueError(f"未知命令路径：{' '.join(path)}；当前可选：{available}")
        current = choices[part]
    return current


def _json_default(value: Any) -> Any:
    """Project argparse defaults into deterministic JSON-compatible values."""

    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    if isinstance(value, Enum):
        return _json_default(value.value)
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, dict):
        return {str(key): _json_default(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_default(item) for item in value]
    if isinstance(value, (set, frozenset)):
        return sorted((_json_default(item) for item in value), key=str)
    return str(value)


def _argument(action: argparse.Action) -> dict[str, Any] | None:
    if action.dest in {"help", "command"} or action.dest in _RUNTIME_FLAGS:
        return None
    payload: dict[str, Any] = {
        "name": action.dest.replace("_", "-"),
        "required": bool(getattr(action, "required", False)),
    }
    if action.option_strings:
        payload["flags"] = list(action.option_strings)
    else:
        payload["positional"] = True
        payload["required"] = action.nargs not in {"?", "*"}
    if action.choices is not None:
        payload["choices"] = list(action.choices)
    if action.default is not None and action.default is not argparse.SUPPRESS:
        payload["default"] = _json_default(action.default)
    if action.help and action.help is not argparse.SUPPRESS:
        payload["description"] = action.help.replace("%%", "%")
    return payload


def _constraints(parser: argparse.ArgumentParser) -> list[dict[str, Any]]:
    constraints: list[dict[str, Any]] = []
    for group in parser._mutually_exclusive_groups:
        options = [
            action.dest.replace("_", "-")
            for action in group._group_actions
            if action.dest not in {"help", "command"}
        ]
        if len(options) < 2:
            continue
        constraints.append(
            {
                "type": "exactly_one" if group.required else "at_most_one",
                "arguments": options,
            }
        )
    return constraints


def command_metadata(path: list[str]) -> dict[str, str]:
    joined = " ".join(path)
    read_only = (
        joined.startswith("paper search")
        or joined.startswith("paper graph")
        or joined.startswith("paper lookup")
        or joined.startswith("system ")
        or joined in {"version", "doctor", "schema", "config"}
        or joined.startswith("job list")
        or joined.startswith("job show")
        or joined.startswith("job wait")
    )
    detachable = joined.startswith(
        (
            "paper search",
            "paper graph",
            "paper lookup",
            "paper download",
            "paper parse",
            "seed-pack add",
            "seed-pack enrich",
            "dataset geo download",
            "dataset archive download",
        )
    )
    return {
        "risk": "read" if read_only else "write",
        "execution": "detachable" if detachable else "foreground",
    }


def command_schema(root: argparse.ArgumentParser, path: list[str]) -> dict[str, Any]:
    if path == ["config"]:
        from paperfetch.core.settings import config_schema_payload

        return config_schema_payload()
    if not path:
        return {
            "commands": [
                {"name": name, "description": parser.description or ""}
                for name, parser in sorted(_subcommands(root).items())
            ]
        }
    parser = _find(root, path)
    arguments = [
        value for action in parser._actions if (value := _argument(action)) is not None
    ]
    constraints = _constraints(parser)
    children = [
        {"name": name, "description": child.description or ""}
        for name, child in sorted(_subcommands(parser).items())
    ]
    return {
        "command": " ".join(path),
        "description": parser.description or "",
        **command_metadata(path),
        "arguments": arguments,
        **({"constraints": constraints} if constraints else {}),
        **({"subcommands": children} if children else {}),
    }
