from __future__ import annotations

import json
import threading

import pytest

from paperfetch.datasets.acquisition import (
    AcquisitionBusy,
    AcquisitionConfigurationError,
    CrossProcessFileLock,
    DownloadCoordinator,
    HostRateLimiter,
    build_acquisition_plan,
    default_host_id,
    error_payload,
    resolve_http_route,
    write_acquisition_report,
)
from paperfetch.observability import (
    configure_observability,
    events_snapshot,
    reset_event_state,
)


def test_route_aware_resolves_to_strict_direct_without_proxy():
    decision = resolve_http_route("route-aware", None)

    assert decision.route == "direct"
    assert decision.proxy_url is None
    assert decision.audit_dict() == {
        "resolved_route": "direct",
        "proxy_ref": None,
    }


def test_default_host_id_handles_non_ascii_windows_hostname(monkeypatch):
    monkeypatch.setattr(
        "paperfetch.datasets.acquisition.socket.gethostname",
        lambda: "唐彬",
    )

    host_id = default_host_id()

    assert host_id.startswith("host:node-")
    assert len(host_id) == len("host:node-") + 12


def test_explicit_direct_ignores_configured_proxy():
    decision = resolve_http_route("direct", "http://user:secret@127.0.0.1:7897")

    assert decision.route == "direct"
    assert decision.proxy_url is None


def test_proxy_audit_never_contains_credentials():
    decision = resolve_http_route("proxy", "http://user:secret@127.0.0.1:7897")
    audit = decision.audit_dict()

    assert decision.proxy_url == "http://user:secret@127.0.0.1:7897"
    assert audit["resolved_route"] == "proxy"
    assert set(audit) == {"resolved_route", "proxy_ref"}
    assert "user" not in json.dumps(audit)
    assert "secret" not in json.dumps(audit)


def test_proxy_mode_requires_endpoint():
    with pytest.raises(AcquisitionConfigurationError) as raised:
        resolve_http_route("proxy", None)
    assert raised.value.error_code == "proxy_not_configured"
    assert raised.value.error_class == "invalid_configuration"
    assert "代理模式" in str(raised.value)


def test_error_payload_separates_stable_machine_codes_from_chinese_message():
    exc = AcquisitionConfigurationError(
        "数据集并发数必须在 1 到 4 之间",
        error_code="invalid_dataset_concurrency",
    )

    payload = error_payload(exc)

    assert payload == {
        "error_code": "invalid_dataset_concurrency",
        "error_class": "invalid_configuration",
        "message": "数据集并发数必须在 1 到 4 之间",
    }


def test_acquisition_plan_digest_is_stable_and_redacted(tmp_path):
    route = resolve_http_route("proxy", "http://user:secret@127.0.0.1:7897")
    kwargs = {
        "dataset_ref": "dataset:geo:GSE1@snapshot-1",
        "source": "ncbi-geo",
        "host_id": "host:test",
        "files": [
            {
                "filename": "GSE1_RAW.tar",
                "url": "https://example.test/GSE1_RAW.tar",
                "size_bytes": 10,
                "etag": '"one"',
            }
        ],
        "route": route,
        "output_dir": str(tmp_path / "GSE1"),
        "size_gate": {"blocked": False, "max_bytes": 20},
        "dataset_concurrency": 2,
        "producer_actor": "tester",
        "spc_git_sha": "a" * 40,
    }

    first = build_acquisition_plan(**kwargs)
    second = build_acquisition_plan(**kwargs)

    assert first["plan_id"] == second["plan_id"]
    assert first["content_digest"] == second["content_digest"]
    assert first["source_snapshot_digest"].startswith("sha256:")
    assert first["concurrency"] == {"datasets": 2, "files": 1}
    assert "secret" not in json.dumps(first)


@pytest.mark.parametrize(
    "url",
    [
        "https://user:secret@example.test/data.bin",
        "https://example.test/data.bin?X-Amz-Signature=secret",
        "https://example.test/data.bin?access_token=secret",
    ],
)
def test_acquisition_plan_rejects_sensitive_file_urls_without_echoing_them(
    tmp_path, url
):
    with pytest.raises(AcquisitionConfigurationError) as raised:
        build_acquisition_plan(
            dataset_ref="dataset:test:one@v1",
            source="test",
            host_id="host:test",
            files=[{"filename": "data.bin", "url": url, "size_bytes": 1}],
            route=resolve_http_route("direct", None),
            output_dir=str(tmp_path),
            size_gate={"blocked": False, "max_bytes": 1},
            dataset_concurrency=1,
        )

    assert raised.value.error_code == "sensitive_url_not_allowed"
    assert "secret" not in str(raised.value)


def test_coordinator_blocks_duplicate_dataset_across_available_host_slots(tmp_path):
    coordinator = DownloadCoordinator(
        tmp_path,
        dataset_concurrency=2,
        lock_timeout_seconds=0.15,
    )
    entered = threading.Event()
    release = threading.Event()

    def hold_first():
        with coordinator.acquire(dataset_key="geo:GSE1", source="ncbi-geo"):
            entered.set()
            release.wait(2)

    thread = threading.Thread(target=hold_first)
    thread.start()
    assert entered.wait(1)
    try:
        with pytest.raises(AcquisitionBusy) as raised:
            with coordinator.acquire(dataset_key="geo:GSE1", source="ncbi-geo"):
                pass
        assert raised.value.error_code == "resource_busy"
        assert "资源正忙" in str(raised.value)
    finally:
        release.set()
        thread.join(2)
    assert not thread.is_alive()


def test_coordinator_enforces_host_dataset_limit(tmp_path):
    coordinator = DownloadCoordinator(
        tmp_path,
        dataset_concurrency=2,
        lock_timeout_seconds=0.15,
    )
    entered = [threading.Event(), threading.Event()]
    release = threading.Event()

    def hold(index: int):
        with coordinator.acquire(
            dataset_key=f"geo:GSE{index}", source=f"source-{index}"
        ):
            entered[index].set()
            release.wait(2)

    threads = [threading.Thread(target=hold, args=(index,)) for index in range(2)]
    for thread in threads:
        thread.start()
    assert all(event.wait(1) for event in entered)
    try:
        with pytest.raises(AcquisitionBusy) as raised:
            with coordinator.acquire(dataset_key="geo:GSE3", source="source-3"):
                pass
        assert raised.value.error_code == "resource_busy"
        assert "下载槽位" in str(raised.value)
    finally:
        release.set()
        for thread in threads:
            thread.join(2)
    assert all(not thread.is_alive() for thread in threads)


def test_third_dataset_waits_for_one_of_two_host_slots(tmp_path):
    coordinator = DownloadCoordinator(
        tmp_path,
        dataset_concurrency=2,
        lock_timeout_seconds=1.0,
    )
    entered = [threading.Event(), threading.Event()]
    release = threading.Event()
    third_entered = threading.Event()
    third_lease = {}
    state = {"active": 0, "maximum": 0}
    state_lock = threading.Lock()

    def hold(index: int):
        with coordinator.acquire(
            dataset_key=f"dataset:{index}",
            source=f"source:{index}",
        ):
            with state_lock:
                state["active"] += 1
                state["maximum"] = max(state["maximum"], state["active"])
            entered[index].set()
            release.wait(2)
            with state_lock:
                state["active"] -= 1

    def run_third():
        with coordinator.acquire(
            dataset_key="dataset:third", source="source:third"
        ) as lease:
            with state_lock:
                state["active"] += 1
                state["maximum"] = max(state["maximum"], state["active"])
            third_lease.update(lease)
            third_entered.set()
            with state_lock:
                state["active"] -= 1

    holders = [threading.Thread(target=hold, args=(index,)) for index in range(2)]
    for thread in holders:
        thread.start()
    assert all(event.wait(1) for event in entered)
    third = threading.Thread(target=run_third)
    third.start()
    try:
        assert not third_entered.wait(0.1)
    finally:
        release.set()
        for thread in holders:
            thread.join(2)
        third.join(2)

    assert third_entered.is_set()
    assert third_lease["queued"] is True
    assert third_lease["contention"]["host_slot"] is True
    assert state["maximum"] == 2
    assert all(not thread.is_alive() for thread in [*holders, third])


def test_coordinator_allows_only_one_large_stream_per_source(tmp_path):
    coordinator = DownloadCoordinator(
        tmp_path,
        dataset_concurrency=2,
        lock_timeout_seconds=0.15,
    )
    entered = threading.Event()
    release = threading.Event()

    def hold_first():
        with coordinator.acquire(dataset_key="geo:GSE1", source="ncbi-geo"):
            entered.set()
            release.wait(2)

    thread = threading.Thread(target=hold_first)
    thread.start()
    assert entered.wait(1)
    try:
        with pytest.raises(AcquisitionBusy) as raised:
            with coordinator.acquire(dataset_key="geo:GSE2", source="ncbi-geo"):
                pass
        assert raised.value.error_code == "resource_busy"
    finally:
        release.set()
        thread.join(2)
    assert not thread.is_alive()


def test_waiting_duplicate_does_not_consume_an_active_download_slot(
    tmp_path, monkeypatch
):
    coordinator = DownloadCoordinator(
        tmp_path,
        dataset_concurrency=2,
        lock_timeout_seconds=0.5,
    )
    first_entered = threading.Event()
    duplicate_started = threading.Event()
    duplicate_lock_attempted = threading.Event()
    release_first = threading.Event()
    duplicate_finished = threading.Event()
    original_enter = CrossProcessFileLock.__enter__

    def observed_enter(lock):
        if (
            threading.current_thread().name == "duplicate-dataset"
            and lock.path.parent.name == "datasets"
        ):
            duplicate_lock_attempted.set()
        return original_enter(lock)

    monkeypatch.setattr(CrossProcessFileLock, "__enter__", observed_enter)

    def hold_first():
        with coordinator.acquire(dataset_key="geo:GSE1", source="ncbi-geo"):
            first_entered.set()
            release_first.wait(2)

    def wait_for_duplicate():
        duplicate_started.set()
        with coordinator.acquire(dataset_key="geo:GSE1", source="ncbi-geo"):
            duplicate_finished.set()

    first = threading.Thread(target=hold_first)
    duplicate = threading.Thread(target=wait_for_duplicate, name="duplicate-dataset")
    first.start()
    assert first_entered.wait(1)
    duplicate.start()
    assert duplicate_started.wait(1)
    assert duplicate_lock_attempted.wait(1)
    try:
        with coordinator.acquire(dataset_key="dryad:one", source="dryad-api"):
            assert not duplicate_finished.is_set()
    finally:
        release_first.set()
        first.join(2)
        duplicate.join(2)

    assert duplicate_finished.is_set()
    assert not first.is_alive()
    assert not duplicate.is_alive()


def test_coordination_audit_uses_chinese_stderr_and_keeps_stdout_clean(
    tmp_path, capsys
):
    reset_event_state("dataset-coordination-language")
    configure_observability(stderr=True, color=False, mode="development")
    coordinator = DownloadCoordinator(
        tmp_path,
        dataset_concurrency=1,
        lock_timeout_seconds=0.1,
    )

    with coordinator.acquire(dataset_key="geo:GSE1", source="ncbi-geo") as lease:
        assert lease["queued"] is False
        assert lease["waited_ms"] >= 0
        assert lease["contention"] == {
            "dataset": False,
            "source": False,
            "host_slot": False,
        }

    captured = capsys.readouterr()
    assert captured.out == ""
    assert "已获取数据集下载资源" in captured.err
    assert "已释放数据集下载资源" in captured.err
    events = events_snapshot(source="ncbi-geo")
    assert [event.event_code for event in events] == [
        "dataset.coordination.acquired",
        "dataset.coordination.released",
    ]
    assert all(event.message for event in events)


def test_host_rate_limiter_persists_pacing_without_secrets(tmp_path):
    current = [100.0]
    sleeps: list[float] = []

    def clock():
        return current[0]

    def sleeper(seconds: float):
        sleeps.append(seconds)
        current[0] += seconds

    limiter = HostRateLimiter(
        tmp_path,
        "ncbi-eutils",
        2.0,
        clock=clock,
        sleeper=sleeper,
    )
    second_process = HostRateLimiter(
        tmp_path,
        "ncbi-eutils",
        2.0,
        clock=clock,
        sleeper=sleeper,
    )
    limiter.wait()
    second_process.wait()

    assert sleeps == [0.5]
    states = list((tmp_path / "rate-limits").glob("*.json"))
    assert len(states) == 1
    payload = json.loads(states[0].read_text(encoding="utf-8"))
    assert payload["schema_version"] == "spc.host-rate-limit-state.v1"
    assert payload["last_request_started_epoch"] == 100.5


def test_acquisition_report_writes_immutable_history_and_latest_pointer(tmp_path):
    plan = build_acquisition_plan(
        dataset_ref="dataset:geo:GSE1@snapshot-1",
        source="ncbi-geo",
        host_id="host:test",
        files=[],
        route=resolve_http_route("direct", None),
        output_dir=str(tmp_path),
        size_gate={"blocked": False, "max_bytes": 1},
        dataset_concurrency=1,
        producer_actor="tester",
        spc_git_sha="a" * 40,
    )

    report = write_acquisition_report(
        tmp_path,
        plan=plan,
        status="complete",
        attempts=[{"route": "direct", "status": "complete"}],
        files=[],
        coordination={"slot": "slot-0"},
    )

    immutable = (
        tmp_path / "acquisition-reports" / f"{report['content_digest'][7:]}.json"
    )
    latest = tmp_path / "acquisition_report.json"
    assert immutable.is_file()
    assert latest.is_file()
    assert (
        json.loads(latest.read_text(encoding="utf-8"))["report_id"]
        == report["report_id"]
    )
