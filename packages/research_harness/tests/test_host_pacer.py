"""C-78: rate-limited sources are paced per host, not per process.

ArxivProvider, PubMedProvider and SemanticScholarProvider each kept their last request time in a
class attribute behind a threading.Lock; two processes on one host did not share it, and at RH
9e9c4c8 the first requests of two processes left 17 µs apart (repro draft C-78). Offline: nothing
is sent; each process records the instant it would have sent.
"""

from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

from research_harness import host_pacer

INTERVAL = 0.6
CHILD = """
import sys, time
from research_harness.paper_source_clients import ArxivProvider, PubMedProvider
provider = {"arxiv": lambda: ArxivProvider(fetcher=lambda *a, **k: ""),
            "pubmed": lambda: PubMedProvider(fetcher=lambda *a, **k: "")}[sys.argv[1]]()
for _ in range(2):
    provider._wait_for_rate_limit()
    print(time.time(), flush=True)
"""


def _stamps(source: str, n_procs: int, pace_dir) -> list[float]:
    # The children import the research_harness this test imports, not whatever the venv's .pth names.
    package_root = str(Path(host_pacer.__file__).resolve().parents[1])
    env = {
        **os.environ,
        "ARXIV_MIN_INTERVAL_SEC": str(INTERVAL),
        "PUBMED_MIN_INTERVAL_SEC": str(INTERVAL),
        "RH_PACE_DIR": str(pace_dir),
        "PYTHONDONTWRITEBYTECODE": "1",
        "PYTHONPATH": os.pathsep.join(
            filter(None, [package_root, os.environ.get("PYTHONPATH")])
        ),
    }
    procs = [
        subprocess.Popen(
            [sys.executable, "-W", "ignore", "-c", CHILD, source],
            stdout=subprocess.PIPE,
            text=True,
            env=env,
        )
        for _ in range(n_procs)
    ]
    return sorted(float(x) for p in procs for x in p.communicate(timeout=60)[0].split())


@pytest.mark.parametrize("source", ["arxiv", "pubmed"])
def test_two_processes_share_one_clock(tmp_path, source):
    stamps = _stamps(source, 2, tmp_path / "pace")
    gaps = [b - a for a, b in zip(stamps, stamps[1:])]
    assert len(stamps) == 4 and min(gaps) >= INTERVAL * 0.95, gaps


def test_one_process_is_paced_as_before(tmp_path):
    stamps = _stamps("arxiv", 1, tmp_path / "pace")
    assert stamps[1] - stamps[0] >= INTERVAL * 0.95


def test_a_future_stamp_delays_by_at_most_one_interval(tmp_path, monkeypatch):
    monkeypatch.setenv("RH_PACE_DIR", str(tmp_path))
    (tmp_path / "arxiv.pace").write_text(repr(time.time() + 3600))
    started = time.monotonic()
    host_pacer.pace("arxiv", 0.2)
    assert time.monotonic() - started < 0.5


def test_an_unwritable_directory_falls_back_to_this_process(tmp_path, monkeypatch):
    blocked = tmp_path / "file-not-dir"
    blocked.write_text("")
    monkeypatch.setenv("RH_PACE_DIR", str(blocked / "pace"))
    started = time.monotonic()
    host_pacer.pace("fallback-test", 0.2)
    host_pacer.pace("fallback-test", 0.2)
    assert time.monotonic() - started >= 0.19


def test_the_default_clock_is_this_users_own_directory(tmp_path, monkeypatch):
    monkeypatch.delenv("RH_PACE_DIR", raising=False)
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "cache"))
    host_pacer.pace("perm-test", 0.01)
    directory = tmp_path / "cache" / "research-harness" / "pace"
    assert directory.stat().st_mode & 0o777 == 0o700
    assert (directory / "perm-test.pace").stat().st_mode & 0o777 == 0o600


def test_a_symlink_planted_at_the_default_path_is_refused_and_nothing_is_opened_up(
    tmp_path, monkeypatch
):
    """Review: a link at the shared default led the pacer to chmod the victim directory 1777 and drop a
    0666 file in it. The default is now per user, and a link there is not used."""
    monkeypatch.delenv("RH_PACE_DIR", raising=False)
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "cache"))
    victim = tmp_path / "victim-ssh"
    victim.mkdir(mode=0o700)
    (tmp_path / "cache" / "research-harness").mkdir(parents=True)
    (tmp_path / "cache" / "research-harness" / "pace").symlink_to(victim)
    started = time.monotonic()
    host_pacer.pace("linked-dir", 0.1)
    host_pacer.pace("linked-dir", 0.1)
    assert time.monotonic() - started >= 0.09  # still paced, in this process
    assert victim.stat().st_mode & 0o7777 == 0o700 and list(victim.iterdir()) == []


def test_a_directory_others_can_write_is_not_the_default_clock(tmp_path, monkeypatch):
    monkeypatch.delenv("RH_PACE_DIR", raising=False)
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "cache"))
    directory = tmp_path / "cache" / "research-harness" / "pace"
    directory.mkdir(parents=True)
    directory.chmod(0o777)
    host_pacer.pace("loose", 0.01)
    assert not (directory / "loose.pace").exists()


ONCE = """
import sys, time
from research_harness.paper_source_clients import ArxivProvider
ArxivProvider(fetcher=lambda *a, **k: "")._wait_for_rate_limit()
print(time.time(), flush=True)
"""


def test_seven_processes_contending_keep_the_interval(tmp_path):
    """Review: with a fixed two-interval patience, seven processes at 1.0 s sent four requests within
    81 ms. A waiter now keeps waiting while the holders keep advancing the stamp."""
    interval = 0.3
    package_root = str(Path(host_pacer.__file__).resolve().parents[1])
    env = {
        **os.environ,
        "ARXIV_MIN_INTERVAL_SEC": str(interval),
        "RH_PACE_DIR": str(tmp_path / "pace"),
        "PYTHONDONTWRITEBYTECODE": "1",
        "PYTHONPATH": os.pathsep.join(
            filter(None, [package_root, os.environ.get("PYTHONPATH")])
        ),
    }
    (tmp_path / "pace").mkdir()
    procs = [
        subprocess.Popen(
            [sys.executable, "-W", "ignore", "-c", ONCE],
            stdout=subprocess.PIPE,
            text=True,
            env=env,
        )
        for _ in range(7)
    ]
    stamps = sorted(float(p.communicate(timeout=60)[0]) for p in procs)
    gaps = [b - a for a, b in zip(stamps, stamps[1:])]
    assert len(stamps) == 7 and min(gaps) >= interval * 0.9, gaps


def test_a_planted_link_is_not_followed(tmp_path, monkeypatch):
    """The pace file is truncated and rewritten; a link another account put in the shared directory
    must not redirect that write (the pacing then falls back to this process)."""
    pace = tmp_path / "pace"
    pace.mkdir()
    victim = tmp_path / "victim.txt"
    victim.write_text("keep me")
    (pace / "linked.pace").symlink_to(victim)
    monkeypatch.setenv("RH_PACE_DIR", str(pace))
    host_pacer.pace("linked", 0.01)
    assert victim.read_text() == "keep me"


HOLDER = """
import fcntl, os, sys, time
fd = os.open(sys.argv[1], os.O_RDWR | os.O_CREAT, 0o666)
fcntl.flock(fd, fcntl.LOCK_EX)
print("held", flush=True)
time.sleep(30)
"""


def test_a_holder_that_never_releases_delays_a_search_by_at_most_two_intervals(
    tmp_path, monkeypatch
):
    """Any account can flock the shared file and sit on it (or be stopped mid-pace with Ctrl-Z)."""
    pace = tmp_path / "pace"
    pace.mkdir()
    holder = subprocess.Popen(
        [sys.executable, "-c", HOLDER, str(pace / "held.pace")],
        stdout=subprocess.PIPE,
        text=True,
    )
    try:
        assert holder.stdout.readline().strip() == "held"
        monkeypatch.setenv("RH_PACE_DIR", str(pace))
        started = time.monotonic()
        host_pacer.pace("held", 0.2)
        assert time.monotonic() - started < 0.2 * 2 + 0.3
    finally:
        holder.kill()
        holder.wait()


def test_a_file_the_operator_directory_creates_is_group_shared(tmp_path, monkeypatch):
    pace = tmp_path / "group"
    pace.mkdir()
    pace.chmod(0o2770)  # the operator's group directory
    monkeypatch.setenv("RH_PACE_DIR", str(pace))
    host_pacer.pace("group-test", 0.01)
    assert (pace / "group-test.pace").stat().st_mode & 0o777 == 0o660 & ~_umask()
    assert pace.stat().st_mode & 0o7777 == 0o2770  # never chmod'd


def _umask() -> int:
    mask = os.umask(0)
    os.umask(mask)
    return mask


def test_an_operator_named_directory_keeps_its_mode(tmp_path, monkeypatch):
    pace = tmp_path / "pace"
    pace.mkdir(mode=0o700)
    monkeypatch.setenv("RH_PACE_DIR", str(pace))
    host_pacer.pace("mode-test", 0.01)
    assert pace.stat().st_mode & 0o7777 == 0o700


def test_semantic_scholar_is_paced_per_key_once_keyed(monkeypatch):
    from research_harness import paper_source_clients as clients

    names = []
    monkeypatch.setattr(clients, "pace", lambda name, interval: names.append(name))
    monkeypatch.setattr(
        clients,
        "get_breaker",
        lambda *a, **k: type("B", (), {"call": staticmethod(lambda f, u, h: {})})(),
    )
    provider = clients.SemanticScholarProvider(
        api_key="key-one", fetcher=lambda *a, **k: {}
    )
    provider._rate_limited_fetch(
        "https://api.semanticscholar.org/x", {"x-api-key": "key-one"}
    )
    provider._rate_limited_fetch(
        "https://api.semanticscholar.org/x", {"x-api-key": "key-two"}
    )
    provider._rate_limited_fetch("https://api.semanticscholar.org/x", {})
    assert (
        names[0] != names[1]
        and names[0].startswith("semantic_scholar-")
        and names[2] == "semantic_scholar"
    )
    assert "key-one" not in names[0]


@pytest.mark.serial
def test_threads_of_one_process_share_the_clock_without_queueing_behind_a_process_lock(
    tmp_path, monkeypatch
):
    import threading

    monkeypatch.setenv("RH_PACE_DIR", str(tmp_path / "pace"))
    stamps = []

    def one():
        host_pacer.pace("threads", 0.2)
        stamps.append(time.time())

    workers = [threading.Thread(target=one) for _ in range(4)]
    for worker in workers:
        worker.start()
    for worker in workers:
        worker.join()
    stamps.sort()
    assert min(b - a for a, b in zip(stamps, stamps[1:])) >= 0.2 * 0.9


ADVANCER = """
import fcntl, os, sys, time
fd = os.open(sys.argv[1], os.O_RDWR | os.O_CREAT, 0o660)
fcntl.flock(fd, fcntl.LOCK_EX)
print("held", flush=True)
while True:
    os.ftruncate(fd, 0)
    os.pwrite(fd, repr(time.time()).encode(), 0)
    time.sleep(0.02)
"""


def test_a_holder_that_keeps_advancing_the_stamp_cannot_hold_a_search_forever(
    tmp_path, monkeypatch
):
    pace = tmp_path / "pace"
    pace.mkdir()
    monkeypatch.setattr(host_pacer, "MAX_WAIT_FLOOR_S", 0.5)
    holder = subprocess.Popen(
        [sys.executable, "-c", ADVANCER, str(pace / "adv.pace")],
        stdout=subprocess.PIPE,
        text=True,
    )
    try:
        assert holder.stdout.readline().strip() == "held"
        monkeypatch.setenv("RH_PACE_DIR", str(pace))
        started = time.monotonic()
        host_pacer.pace("adv", 0.02)  # cap = max(10 x 0.02, 0.5) = 0.5 s
        assert time.monotonic() - started < 0.5 + 0.3
    finally:
        holder.kill()
        holder.wait()


def test_no_home_and_a_relative_xdg_are_handled(monkeypatch, tmp_path):
    from pathlib import Path as _Path

    monkeypatch.delenv("RH_PACE_DIR", raising=False)
    monkeypatch.setenv("XDG_CACHE_HOME", "relative/cache")
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    assert host_pacer.pace_dir() == (
        tmp_path / "home" / ".cache" / "research-harness" / "pace",
        False,
    )
    monkeypatch.delenv("XDG_CACHE_HOME")
    monkeypatch.setattr(
        _Path,
        "home",
        classmethod(lambda cls: (_ for _ in ()).throw(RuntimeError("no home"))),
    )
    assert host_pacer.pace_dir() is None
    started = time.monotonic()
    host_pacer.pace("nohome", 0.05)
    host_pacer.pace("nohome", 0.05)
    assert time.monotonic() - started >= 0.045  # paced per process


def test_a_hard_linked_pace_file_is_not_used(tmp_path, monkeypatch):
    pace = tmp_path / "pace"
    pace.mkdir()
    victim = tmp_path / "victim.txt"
    victim.write_text("keep me")
    import os as _os

    _os.link(victim, pace / "hard.pace")
    monkeypatch.setenv("RH_PACE_DIR", str(pace))
    host_pacer.pace("hard", 0.01)
    assert victim.read_text() == "keep me"


def test_an_operator_directory_open_to_all_without_the_sticky_bit_is_refused(
    tmp_path, monkeypatch
):
    pace = tmp_path / "pace"
    pace.mkdir()
    pace.chmod(0o777)
    monkeypatch.setenv("RH_PACE_DIR", str(pace))
    host_pacer.pace("open", 0.01)
    assert not (pace / "open.pace").exists()
    pace.chmod(0o1777)
    host_pacer.pace("sticky", 0.01)
    assert (pace / "sticky.pace").exists()
