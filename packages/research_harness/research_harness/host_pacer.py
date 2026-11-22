"""One request clock per rate-limited source, shared by every process that can reach the clock file.

arXiv, NCBI and Semantic Scholar limit requests per client address (S2's keyed tier per key), not per
process. Each provider paced itself with a class attribute and a threading.Lock, which two retrieval
processes (a CLI and an MCP server, two seats) do not share: their first requests left 17 µs apart.
``pace(name, interval)`` keeps the last request time in a small file and holds an exclusive flock on it
while it waits, so every process sharing that file waits for the same clock.

Where the file lives:
- by default ``$XDG_CACHE_HOME/research-harness/pace`` (``~/.cache/...``): this user's own directory,
  created 0700 and used only when it is a real directory this uid owns that no one else can write, so
  every process of one account shares one clock and nothing is ever opened to another account;
- ``$RH_PACE_DIR`` when the operator names one (a group directory shared by seats): used as it is (created
  under the operator's umask when missing), never chmod'd; a file created there is 0660 under the umask.
Neither the directory nor the file is followed through a symlink.

Waiting: while another process holds the lock, the wait continues as long as the stamp in the file keeps
advancing (a live holder advances it on every request); after two intervals with no advance (a stopped or
hostile holder), this call paces on the file's last stamp without the lock and still writes its own stamp.
Where the file cannot be used at all, pacing falls back to this process alone.
"""

from __future__ import annotations

import os
import stat
import threading
import time
from pathlib import Path

try:
    import fcntl
except ImportError:  # pragma: no cover - not on the supported hosts
    fcntl = None  # type: ignore[assignment]

_LOCAL_LAST: dict[str, float] = {}
_LOCAL_GUARD = threading.Lock()
_LOCAL_LOCKS: dict[str, threading.Lock] = {}
_POLL_S = 0.02
# The longest a caller waits on a holder that keeps advancing the stamp: max(10 intervals, this).
MAX_WAIT_FLOOR_S = 30.0


def pace_dir() -> tuple[Path, bool] | None:
    """The pace directory and whether the operator named it; None when there is no home to put it in."""
    named = os.environ.get("RH_PACE_DIR")
    if named:
        return Path(named), True
    xdg = os.environ.get("XDG_CACHE_HOME")
    try:
        cache = (
            Path(xdg) if xdg and os.path.isabs(xdg) else Path.home() / ".cache"
        )  # XDG: absolute only
    except (RuntimeError, KeyError):  # no HOME and no passwd entry
        return None
    return cache / "research-harness" / "pace", False


def _open(name: str) -> int | None:
    if fcntl is None:
        return None
    where = pace_dir()
    if where is None:
        return None
    directory, named = where
    try:
        os.makedirs(directory.parent, exist_ok=True)
        try:
            os.mkdir(
                directory, 0o700 if not named else 0o777
            )  # a named one keeps the operator's umask
        except FileExistsError:
            pass  # another process made it first; what it is gets checked below
        # O_NOFOLLOW refuses a symlink planted at the path; the checks read the directory actually opened.
        dir_fd = os.open(
            directory, os.O_RDONLY | os.O_DIRECTORY | getattr(os, "O_NOFOLLOW", 0)
        )
        try:
            info = os.fstat(dir_fd)
            if not named and (info.st_uid != os.getuid() or info.st_mode & 0o022):
                return (
                    None  # the default must be this user's and writable by no one else
                )
            if named and (
                info.st_uid not in (os.getuid(), 0)
                or (info.st_mode & 0o002 and not info.st_mode & stat.S_ISVTX)
            ):
                return None  # an operator's directory: theirs or root's, and not open to all without sticky
            for attempt in range(3):
                try:
                    fd = os.open(
                        f"{name}.pace",
                        os.O_RDWR | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0),
                        0o660 if named else 0o600,
                        dir_fd=dir_fd,
                    )
                    break
                except FileNotFoundError:
                    # macOS answers ENOENT to an O_CREAT that races another process creating the name
                    if attempt == 2:
                        raise
        finally:
            os.close(dir_fd)
    except OSError:
        return None
    info = os.fstat(fd)
    if (
        not stat.S_ISREG(info.st_mode) or info.st_nlink != 1
    ):  # a hard link to someone else's file
        os.close(fd)
        return None
    return fd


def _stamp(fd: int) -> float:
    try:
        return float(os.pread(fd, 64, 0).decode("ascii").strip() or 0)
    except (OSError, ValueError, UnicodeDecodeError):
        return 0.0


def _record(fd: int) -> None:
    stamp = repr(time.time()).encode("ascii")
    os.ftruncate(fd, 0)
    os.pwrite(fd, stamp, 0)


def _wait_after(last: float, min_interval: float) -> None:
    wait = last + min_interval - time.time()
    if wait > 0:
        time.sleep(
            min(wait, min_interval)
        )  # a stamp in the future costs at most one interval


def _lock(fd: int, min_interval: float) -> bool:
    """Take the lock, waiting while a live holder keeps advancing the stamp; False after two intervals
    with no advance, or after max(10 intervals, 30 s) in all (a holder that keeps rewriting the stamp
    without releasing)."""
    seen, idle_since = _stamp(fd), time.monotonic()
    deadline = idle_since + max(10 * min_interval, MAX_WAIT_FLOOR_S)
    while True:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            return True
        except (BlockingIOError, PermissionError):
            pass
        now = _stamp(fd)
        if now != seen:
            seen, idle_since = now, time.monotonic()
        elif time.monotonic() - idle_since >= 2 * min_interval:
            return False
        if time.monotonic() >= deadline:
            return False
        time.sleep(_POLL_S)


def _local_pace(name: str, min_interval: float) -> None:
    with _LOCAL_GUARD:
        guard = _LOCAL_LOCKS.setdefault(name, threading.Lock())
    with guard:  # one source's wait does not hold up another's
        wait = _LOCAL_LAST.get(name, 0.0) + min_interval - time.monotonic()
        if wait > 0:
            time.sleep(min(wait, min_interval))
        _LOCAL_LAST[name] = time.monotonic()


def pace(name: str, min_interval: float) -> None:
    """Return once ``min_interval`` seconds have passed since the last ``name`` request on this clock,
    and record this one."""
    if min_interval <= 0:
        return
    fd = _open(name)
    if fd is None:
        _local_pace(name, min_interval)
        return
    try:
        if _lock(fd, min_interval):
            try:
                _wait_after(_stamp(fd), min_interval)
                _record(fd)
            finally:
                fcntl.flock(fd, fcntl.LOCK_UN)
        else:
            _wait_after(_stamp(fd), min_interval)
            _record(fd)
    finally:
        os.close(fd)
