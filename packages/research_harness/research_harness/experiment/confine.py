"""Run model-generated experiment code inside an OS boundary, or refuse to run it.

Descriptor checks in the parent decide what may be *attested*; they cannot stop the child
writing outside its experiment root, reading the host, or opening a socket. That takes the
kernel. On macOS the boundary is a Seatbelt profile: deny by default, writes only beneath one
root, reads only beneath declared roots plus the interpreter and system libraries, no network.
On Linux it is one bwrap per call: empty root, all namespaces unshared, declared roots bound
read-only and one root writable; bwrap must be root-owned and a probe run in this process must
pass first. Every other platform fails closed: a silent fallback to a bare subprocess would
make the confinement claim false exactly where nobody is looking.

Stdlib only, so stage agents on a shared host can read this file without importing anything
else.
"""

from __future__ import annotations

import json
import os
import signal
import stat
import subprocess
import sys
import sysconfig
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

SANDBOX_EXEC = Path("/usr/bin/sandbox-exec")
BWRAP = Path("/usr/bin/bwrap")
_bwrap_verified = False  # set once per process after the probe passes


class ConfinementUnavailable(RuntimeError):
    """No verified OS confinement backend exists here; the command was not started."""


def _quoted(value: Path) -> str:
    return json.dumps(str(value))


def _ancestors(path: Path) -> set[Path]:
    """Directories Seatbelt must let the child traverse before an allowed subtree."""
    current = path.absolute()
    found = {current}
    while current.parent != current:
        current = current.parent
        found.add(current)
    return found


def seatbelt_profile(
    *,
    write_root: Path,
    read_roots: Sequence[Path] = (),
    executables: Sequence[Path] = (),
    exec_roots: Sequence[Path] = (),
    allow_fork: bool = True,
) -> str:
    """Deny-default Seatbelt profile: one write root, path-scoped reads and execs, no network.

    `executables` are exact binaries the child may exec; `exec_roots` are subtrees it may exec
    from. Denying fork also stops descendants escaping process-group cleanup with `setsid`.
    """
    roots = {
        write_root.absolute(),
        write_root.resolve(),
        *(path.absolute() for path in read_roots),
        *(path.resolve() for path in read_roots),
        Path(sys.base_prefix).absolute(),
        Path(sys.base_prefix).resolve(),
        Path(sysconfig.get_path("stdlib")).resolve(),
        Path("/System/Library"),
        Path("/usr/lib"),
        Path("/usr/share"),
        Path("/private/etc"),
    }
    allowed_executables = {
        *(path.resolve() for path in executables),
        *(path.absolute() for path in executables),
        Path(sys.executable).resolve(),
        Path(sys.base_prefix).resolve() / "Resources/Python.app/Contents/MacOS/Python",
    }
    ancestors: set[Path] = set()
    for path in roots:
        ancestors.update(_ancestors(path))
    read_rules = " ".join(
        [
            *(f"(subpath {_quoted(path)})" for path in roots),
            *(f"(literal {_quoted(path)})" for path in ancestors),
        ]
    )
    exec_rules = " ".join(
        [
            *(f"(literal {_quoted(path)})" for path in allowed_executables),
            *(f"(subpath {_quoted(path)})" for path in exec_roots),
        ]
    )
    fork_rule = () if allow_fork else ("(deny process-fork)",)
    return " ".join(
        (
            "(version 1)",
            "(deny default)",
            "(allow file-read-metadata)",
            f"(allow file-read* {read_rules})",
            "(allow file-write* "
            f"(subpath {_quoted(write_root.absolute())}) "
            f"(subpath {_quoted(write_root.resolve())}))",
            '(allow file-read* file-write-data (literal "/dev/null"))',
            # Python's framework launcher needs process-info operations in addition to fork.
            # Exec stays deny-by-default and is reopened only for the paths selected above.
            "(allow process*)",
            *fork_rule,
            "(deny process-exec)",
            f"(allow process-exec {exec_rules})",
            "(allow sysctl-read)",
            "(allow mach-lookup)",
            "(deny network*)",
        )
    )


def _bwrap_owner_uid(st: os.stat_result) -> int:
    return st.st_uid


_PROBE = """
import os, socket, subprocess, sys, time
rw, ro, hidden = sys.argv[1:4]
open(os.path.join(rw, "ok"), "w").write("1")
try:
    open(os.path.join(ro, "escaped"), "w")
    sys.exit("read-only root is writable")
except OSError:
    pass
if os.path.exists(hidden):
    sys.exit("an unbound host path is visible")
names = [line.split(":")[0].strip() for line in open("/proc/net/dev").readlines()[2:]]
if names != ["lo"]:
    sys.exit(f"interfaces {names}")
try:
    socket.create_connection(("1.1.1.1", 53), 2)
    sys.exit("network reachable")
except OSError:
    pass
subprocess.Popen([sys.executable, "-I", "-c",
                  f"import time; time.sleep(0.5); open({os.path.join(rw, 'late')!r}, 'w')"],
                 start_new_session=True)
"""


def _probe_bwrap() -> None:
    """Run the real prefix once: write inside only, nothing else visible, loopback only,
    and no descendant alive after the job exits."""
    import tempfile
    import time

    try:
        with tempfile.TemporaryDirectory(prefix="confine-probe-") as tmp:
            rw, ro, hidden = Path(tmp, "rw"), Path(tmp, "ro"), Path(tmp, "hidden")
            for path in (rw, ro, hidden):
                path.mkdir()
            prefix = _bwrap_prefix(rw, [ro], cwd=rw, env={})
            done = subprocess.run(
                [
                    *prefix,
                    sys.executable,
                    "-I",
                    "-c",
                    _PROBE,
                    *(str(path.resolve()) for path in (rw, ro, hidden)),
                ],
                capture_output=True,
                text=True,
                timeout=60,
                start_new_session=True,
            )
            time.sleep(1)
            if (
                done.returncode != 0
                or not (rw / "ok").is_file()
                or (ro / "escaped").exists()
                or (rw / "late").exists()
            ):
                raise ConfinementUnavailable(
                    f"bwrap probe failed ({done.returncode}): {(done.stdout + done.stderr)[-400:]}"
                )
    except (OSError, subprocess.TimeoutExpired) as error:
        raise ConfinementUnavailable(f"bwrap probe did not run: {error}") from error


# Merged-usr hosts make these symlinks into /usr; they are recreated as symlinks, not bound.
_LINUX_TOP = ("/bin", "/sbin", "/lib", "/lib32", "/lib64")
# Only what the dynamic loader and Python read from /etc; the rest can hold host secrets.
_LINUX_ETC = (
    "/etc/ld.so.cache",
    "/etc/localtime",
    "/etc/passwd",
    "/etc/group",
    "/etc/nsswitch.conf",
    "/etc/fonts",
)


def _bwrap_prefix(
    write_root: Path, read_roots: Sequence[Path], *, cwd: Path, env: Mapping[str, str]
) -> list[str]:
    """Empty root, every namespace unshared, declared roots read-only, one writable root."""
    interpreter = {Path(sys.prefix), Path(sys.exec_prefix), Path(sys.base_prefix)}
    args = [
        str(BWRAP),
        "--unshare-all",
        "--die-with-parent",
        "--new-session",
        "--cap-drop",
        "ALL",
        "--clearenv",
        "--proc",
        "/proc",
        "--dev",
        "/dev",
        "--tmpfs",
        "/tmp",
        "--ro-bind",
        "/usr",
        "/usr",
    ]
    for top in _LINUX_TOP:
        if os.path.islink(top):
            args += ["--symlink", os.readlink(top), top]
        elif os.path.isdir(top):
            args += ["--ro-bind", top, top]
    for name in _LINUX_ETC:
        args += ["--ro-bind-try", name, name]
    for root in dict.fromkeys(p.resolve() for p in [*interpreter, *read_roots]):
        if root.exists():
            args += ["--ro-bind", str(root), str(root)]
    args += ["--bind", str(write_root.resolve()), str(write_root.resolve())]
    for key, value in env.items():
        args += ["--setenv", key, value]
    return [*args, "--chdir", str(Path(cwd).resolve()), "--"]


def _verify_bwrap() -> None:
    global _bwrap_verified
    if _bwrap_verified:
        return
    try:
        st = BWRAP.stat()
    except OSError as error:
        raise ConfinementUnavailable(
            f"bwrap unavailable at {BWRAP}: {error}"
        ) from error
    if not stat.S_ISREG(st.st_mode) or _bwrap_owner_uid(st) != 0 or st.st_mode & 0o022:
        raise ConfinementUnavailable(
            f"bwrap at {BWRAP} is not a root-owned, non-writable file"
        )
    _probe_bwrap()
    _bwrap_verified = True


def _command_prefix(
    write_root: Path,
    read_roots: Sequence[Path],
    allow_fork: bool,
    *,
    cwd: Path,
    env: Mapping[str, str],
) -> list[str]:
    if sys.platform.startswith("linux"):
        # A pid namespace kills every descendant when the job exits, so fork is safe here.
        _verify_bwrap()
        return _bwrap_prefix(write_root, read_roots, cwd=cwd, env=env)
    if sys.platform != "darwin" or not SANDBOX_EXEC.is_file():
        raise ConfinementUnavailable(
            f"no verified OS confinement backend on {sys.platform}; refusing to run "
            "model-generated code as a bare subprocess"
        )
    interpreter = {Path(sys.prefix), Path(sys.exec_prefix), Path(sys.base_prefix)}
    system = {Path("/bin"), Path("/usr/bin"), Path("/private/var/select")}
    readable = [*read_roots, *interpreter, *system]
    return [
        str(SANDBOX_EXEC),
        "-p",
        seatbelt_profile(
            write_root=write_root,
            read_roots=readable,
            exec_roots=[write_root, *readable],
            allow_fork=allow_fork,
        ),
    ]


def run_confined(
    argv: Sequence[str],
    *,
    cwd: str | os.PathLike[str],
    write_root: str | os.PathLike[str],
    read_roots: Sequence[str | os.PathLike[str]] = (),
    timeout_s: float,
    env: Mapping[str, str],
    capture_output: bool = False,
    allow_fork: bool = False,
) -> subprocess.CompletedProcess[Any]:
    """Run `argv` confined; raise `subprocess.TimeoutExpired` after killing its process group.

    The child may write only beneath `write_root`, read `read_roots` plus the interpreter and
    system libraries, and has no network. No descendant outlives the call: on Linux the pid
    namespace dies with the job; on macOS fork is denied unless `allow_fork`.
    """
    # ponytail: with allow_fork a descendant that calls setsid survives killpg (macOS has no
    # pid namespace); only callers whose verdict such a process cannot forge may pass it.
    prefix = _command_prefix(
        Path(write_root),
        [Path(root) for root in read_roots],
        allow_fork,
        cwd=Path(cwd),
        env=env,
    )
    command = list(argv)
    pipe = subprocess.PIPE if capture_output else None
    process = subprocess.Popen(
        [*prefix, *command],
        cwd=cwd,
        env=dict(env),
        stdout=pipe,
        stderr=pipe,
        start_new_session=True,
    )
    try:
        stdout, stderr = process.communicate(timeout=timeout_s)
    finally:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except (ProcessLookupError, PermissionError):
            pass
        if process.poll() is None:
            process.kill()
            process.wait()
    return subprocess.CompletedProcess(command, process.returncode, stdout, stderr)
