from paperfetch.cli.doctor import (
    _credential_configured,
    _diagnose_proxy_path,
    _download_proxy_status,
    _traffic_class_status,
)


class _Connection:
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        return None


def test_download_proxy_status_is_reachable_and_redacts_credentials(monkeypatch):
    captured = {}

    def connect(address, timeout):
        captured["address"] = address
        captured["timeout"] = timeout
        return _Connection()

    monkeypatch.setenv("DOWNLOAD_PROXY", "http://user:secret@127.0.0.1:7897")
    monkeypatch.setattr("paperfetch.cli.doctor.socket.create_connection", connect)

    status = _download_proxy_status(timeout_seconds=0.25)

    assert status == {
        "configured": True,
        "scheme": "http",
        "tcp_reachable": True,
    }
    assert captured == {"address": ("127.0.0.1", 7897), "timeout": 0.25}
    assert "user" not in str(status)
    assert "secret" not in str(status)


def test_download_proxy_status_reports_unreachable_endpoint(monkeypatch):
    def connect(_address, timeout=None):
        raise OSError("connection refused")

    monkeypatch.setenv("DOWNLOAD_PROXY", "127.0.0.1:7897")
    monkeypatch.setattr("paperfetch.cli.doctor.socket.create_connection", connect)

    status = _download_proxy_status()

    assert status["configured"] is True
    assert status["tcp_reachable"] is False


def test_download_proxy_status_handles_missing_configuration(monkeypatch):
    monkeypatch.delenv("DOWNLOAD_PROXY", raising=False)

    assert _download_proxy_status() == {
        "configured": False,
        "scheme": None,
        "tcp_reachable": None,
    }


def test_download_proxy_status_treats_boolean_false_as_disabled(monkeypatch):
    monkeypatch.setenv("DOWNLOAD_PROXY", "false")

    assert _download_proxy_status() == {
        "configured": False,
        "scheme": None,
        "tcp_reachable": None,
    }


def test_proxy_path_diagnosis_does_not_claim_subscription_expired():
    diagnosis = _diagnose_proxy_path(
        {"configured": True, "scheme": "http", "tcp_reachable": True},
        {
            "classes": [
                {
                    "class_id": "paper_download",
                    "outcome": "unreachable",
                    "http_status": None,
                }
            ]
        },
        proxy_required=True,
    )

    assert diagnosis["code"] == "proxy_path_degraded"
    assert diagnosis["cause_confirmed"] is False
    assert "subscription_expired" in diagnosis["possible_causes"]


def test_proxy_path_diagnosis_confirms_endpoint_and_auth_failures():
    unreachable = _diagnose_proxy_path(
        {"configured": True, "scheme": "http", "tcp_reachable": False},
        None,
        proxy_required=True,
    )
    auth_failed = _diagnose_proxy_path(
        {"configured": True, "scheme": "http", "tcp_reachable": True},
        {
            "classes": [
                {
                    "class_id": "paper_download",
                    "outcome": "proxy_auth_required",
                    "http_status": 407,
                }
            ]
        },
        proxy_required=True,
    )

    assert unreachable == {
        "state": "unavailable",
        "code": "proxy_endpoint_unreachable",
        "cause_confirmed": True,
    }
    assert auth_failed == {
        "state": "unavailable",
        "code": "proxy_auth_failed",
        "cause_confirmed": True,
    }


def test_doctor_traffic_probe_removes_proxy_endpoint_and_exit_ip(monkeypatch):
    monkeypatch.setattr(
        "paperfetch.network.probe_traffic_classes",
        lambda *_args, **_kwargs: {
            "schema_version": "spc.traffic-classes.v1",
            "transport": "proxy",
            "proxy": "http://127.0.0.1:7897",
            "distinct_exit_ips": ["203.0.113.7"],
            "classes": [
                {
                    "class_id": "paper_download",
                    "outcome": "ok",
                    "proxy": "http://127.0.0.1:7897",
                    "exit_ip": "203.0.113.7",
                }
            ],
            "degraded": [],
        },
    )

    result = _traffic_class_status("http://user:secret@127.0.0.1:7897")

    assert "proxy" not in result
    assert "distinct_exit_ips" not in result
    assert "proxy" not in result["classes"][0]
    assert "exit_ip" not in result["classes"][0]
    assert "secret" not in str(result)


def test_doctor_credentials_treat_boolean_false_proxy_as_disabled(monkeypatch):
    monkeypatch.setenv("DOWNLOAD_PROXY", "false")
    assert _credential_configured("DOWNLOAD_PROXY") is False
