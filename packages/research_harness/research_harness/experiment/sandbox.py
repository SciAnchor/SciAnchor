"""Confined runner for model-generated experiment code.

Runs experiment code under the OS boundary in ``confine.py``: writes only
beneath the work directory, no
network, no fork on macOS. Where no verified backend exists the run is refused
with ``ConfinementUnavailable``. Captures stdout/stderr and parses metrics.

Adapted from AutoResearchClaw (MIT license).
"""

from __future__ import annotations

import hashlib
import logging
import os
import re
import stat
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

from .confine import run_confined
from .metric_parser import detect_nan_divergence, parse_metrics

logger = logging.getLogger(__name__)

# Experiments receive no parent credentials unless the caller names them.
DEFAULT_ENV_ALLOWLIST: frozenset[str] = frozenset()
# A confined experiment has no network, so a credential can only end up in its outputs.
# ponytail: name heuristic; a secret under a neutral name still passes.
CREDENTIAL_NAME = re.compile(
    r"KEY|TOKEN|SECRET|PASSW|CREDENTIAL|AUTH|COOKIE|SESSION", re.I
)


def build_experiment_env(
    *,
    extra_env: dict[str, str] | None = None,
    allowlist: frozenset[str] | set[str] | None = None,
    include_path: bool = True,
) -> dict[str, str]:
    """Compose the subprocess env for an experiment.

    Starts with the explicitly allowlisted subset of the parent env plus basic
    process variables, then overlays ``extra_env`` (spec-declared extras).
    """
    allow = frozenset(allowlist) if allowlist is not None else DEFAULT_ENV_ALLOWLIST
    env: dict[str, str] = {}

    # Minimum infrastructure vars for Python startup.
    baseline = ["PATH", "LANG", "LC_ALL", "TERM", "TMPDIR"]
    if include_path:
        for key in baseline:
            val = os.environ.get(key)
            if val is not None:
                env[key] = val

    # Allowlisted secrets from parent.
    for key in allow:
        val = os.environ.get(key)
        if val:
            env[key] = val

    # Spec-level extras win over parent.
    if extra_env:
        for key, val in extra_env.items():
            env[key] = str(val)

    return env


def _safe_relative_path(value: str, *, field_name: str) -> Path:
    if not isinstance(value, str) or not value:
        raise ValueError(f"{field_name} must be a non-empty safe relative path")
    path = Path(value)
    if path.is_absolute() or ".." in path.parts or path == Path("."):
        raise ValueError(f"{field_name} must be a safe relative path: {value!r}")
    return path


def _reject_symlink_components(root: Path, relative_path: Path) -> None:
    current = root
    for part in relative_path.parts:
        current /= part
        if current.is_symlink():
            raise ValueError(
                f"experiment file path contains a symlink: {relative_path}"
            )


def _open_experiment_directory(root_fd: int, parts: tuple[str, ...]) -> int:
    current_fd = os.dup(root_fd)
    try:
        for part in parts:
            try:
                os.mkdir(part, mode=0o700, dir_fd=current_fd)
            except FileExistsError:
                pass
            next_fd = os.open(
                part,
                os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
                dir_fd=current_fd,
            )
            os.close(current_fd)
            current_fd = next_fd
        return current_fd
    except OSError as exc:
        os.close(current_fd)
        raise ValueError(
            "experiment file path contains a symlink or unsafe component"
        ) from exc


def _write_experiment_file(root_fd: int, relative_path: Path, content: str) -> None:
    parent_fd = _open_experiment_directory(root_fd, relative_path.parts[:-1])
    file_fd = -1
    try:
        file_fd = os.open(
            relative_path.name,
            os.O_WRONLY | os.O_CREAT | os.O_NOFOLLOW | os.O_NONBLOCK,
            0o600,
            dir_fd=parent_fd,
        )
        info = os.fstat(file_fd)
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
            raise ValueError("experiment file must be a single-link regular file")
        os.ftruncate(file_fd, 0)
        with os.fdopen(file_fd, "w", encoding="utf-8") as stream:
            file_fd = -1
            stream.write(content)
    except OSError as exc:
        raise ValueError(
            "experiment file path contains a symlink or unsafe component"
        ) from exc
    finally:
        if file_fd >= 0:
            os.close(file_fd)
        os.close(parent_fd)


@dataclass(frozen=True)
class SandboxResult:
    """Result of running an experiment subprocess."""

    returncode: int
    stdout: str
    stderr: str
    elapsed_sec: float
    metrics: dict[str, float] = field(default_factory=dict)
    timed_out: bool = False
    divergence: str = ""
    code_hash: str = ""


def run_experiment(
    code: str | None = None,
    *,
    files: dict[str, str] | None = None,
    entry_point: str = "main.py",
    timeout_sec: float = 300.0,
    work_dir: Path | None = None,
    env: dict[str, str] | None = None,
    extra_env: dict[str, str] | None = None,
    env_allowlist: frozenset[str] | set[str] | None = None,
) -> SandboxResult:
    """Execute experiment code under OS confinement (see ``confine.run_confined``).

    Accepts either a single-file ``code`` string (written to ``entry_point``)
    or a multi-file ``files`` dict (all written to ``work_dir``, entry_point
    decides the invocation target). Uses the RH interpreter (``sys.executable``)
    so the experiment inherits RH's installed Python packages.

    When ``env`` is provided it is used verbatim. Otherwise only parent
    variables named by ``env_allowlist`` are copied, then ``extra_env`` is
    overlaid. A variable whose name looks like a credential is refused
    (``CREDENTIAL_NAME``): the child has no network to use it on.
    """
    import time

    # Normalize inputs: prefer files, fall back to code.
    if files is None:
        files = {}
    if code and entry_point not in files:
        files = dict(files)
        files[entry_point] = code
    if not files:
        raise ValueError("run_experiment requires either 'code' or 'files'")
    entry_relative = _safe_relative_path(entry_point, field_name="entry_point")
    if entry_point not in files:
        raise ValueError(
            f"entry_point {entry_point!r} not present in files: {sorted(files)}"
        )
    relative_files = {
        rel_path: _safe_relative_path(rel_path, field_name="file path")
        for rel_path in files
    }

    entry_code = files[entry_point]
    code_hash = hashlib.sha256(entry_code.encode()).hexdigest()[:16]

    # Create work directory
    if work_dir is None:
        tmp = tempfile.mkdtemp(prefix="rh_experiment_")
        work_dir = Path(tmp)
    work_dir.mkdir(parents=True, exist_ok=True)
    if work_dir.is_symlink():
        raise ValueError(f"experiment work_dir must not be a symlink: {work_dir}")
    for relative_path in relative_files.values():
        _reject_symlink_components(work_dir, relative_path)

    # Write through a pinned root descriptor so a symlink swap cannot redirect writes.
    try:
        work_fd = os.open(
            work_dir,
            os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
        )
    except OSError as exc:
        raise ValueError("experiment work_dir must not be a symlink") from exc
    try:
        for rel_path, content in files.items():
            _write_experiment_file(work_fd, relative_files[rel_path], content)
    finally:
        os.close(work_fd)

    for relative_path in relative_files.values():
        _reject_symlink_components(work_dir, relative_path)

    entry_path = work_dir / entry_relative

    # Compose subprocess env.
    if env is None:
        run_env = build_experiment_env(extra_env=extra_env, allowlist=env_allowlist)
    else:
        run_env = dict(env)
        if extra_env:
            for k, v in extra_env.items():
                run_env[k] = str(v)

    credentials = sorted(name for name in run_env if CREDENTIAL_NAME.search(name))
    if credentials:
        raise ValueError(
            f"experiment env names credential variables {credentials}; confined experiments "
            "have no network, so credentials are never passed to them"
        )

    # Nothing outside the work directory is writable, so temporary files go there too.
    run_env["TMPDIR"] = str(work_dir.resolve())

    # Run
    start = time.monotonic()
    timed_out = False
    try:
        result = run_confined(
            [sys.executable, str(entry_path)],
            cwd=work_dir,
            write_root=work_dir,
            timeout_s=timeout_sec,
            env=run_env,
            capture_output=True,
        )
        elapsed = time.monotonic() - start
        stdout = (result.stdout or b"").decode("utf-8", errors="replace")
        stderr = (result.stderr or b"").decode("utf-8", errors="replace")
        returncode = result.returncode
    except subprocess.TimeoutExpired as exc:
        elapsed = time.monotonic() - start
        timed_out = True
        stdout = exc.stdout.decode("utf-8", errors="replace") if exc.stdout else ""
        stderr = exc.stderr.decode("utf-8", errors="replace") if exc.stderr else ""
        returncode = -1

    # Parse metrics and detect divergence
    metrics = parse_metrics(stdout)
    divergence = detect_nan_divergence(stdout, stderr)

    return SandboxResult(
        returncode=returncode,
        stdout=stdout[-5000:],  # Cap to avoid memory issues
        stderr=stderr[-2000:],
        elapsed_sec=elapsed,
        metrics=metrics,
        timed_out=timed_out,
        divergence=divergence,
        code_hash=code_hash,
    )


def is_improvement(
    new_value: float,
    best_value: float,
    *,
    direction: str = "maximize",
    min_delta: float = 0.0,
) -> bool:
    """Check if new_value improves over best_value."""
    if direction == "maximize":
        return new_value > best_value + min_delta
    return new_value < best_value - min_delta
