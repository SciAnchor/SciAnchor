from paperfetch.cli import doctor


class _Response:
    status_code = 200


class _Client:
    def __init__(self, *args, **kwargs):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def get(self, *args, **kwargs):
        return _Response()

    def post(self, *args, **kwargs):
        return _Response()


def test_normal_doctor_does_not_probe_semantic_scholar_keys(monkeypatch):
    monkeypatch.setenv("SEMANTIC_SCHOLAR_API_KEYS", "secret-a,secret-b")
    monkeypatch.delenv("SEMANTIC_SCHOLAR_API_KEY", raising=False)
    monkeypatch.delenv("LLM_API_KEY", raising=False)
    monkeypatch.delenv("LLM_BASE_URL", raising=False)
    monkeypatch.delenv("NCBI_API_KEY", raising=False)
    monkeypatch.delenv("OPENALEX_API_KEYS", raising=False)
    monkeypatch.delenv("OPENALEX_API_KEY", raising=False)
    monkeypatch.setattr("httpx.Client", _Client)
    monkeypatch.setattr(
        doctor,
        "_semantic_scholar_pool_snapshot",
        lambda: {"configured": 2, "ready": 2, "cooling": 0, "leased": 0, "disabled": 0},
    )
    monkeypatch.setattr(
        doctor,
        "_probe_semantic_scholar_scheduler",
        lambda: (_ for _ in ()).throw(AssertionError("must not probe")),
    )

    result = doctor._probe_live_api_endpoints(probe_semantic_scholar=False)

    s2 = result["semantic_scholar_live"]
    assert s2["attempted"] is False
    assert s2["configured_keys"] == 2
    assert "secret" not in str(s2)


def test_explicit_doctor_probe_uses_one_scheduler_operation(monkeypatch):
    monkeypatch.delenv("LLM_API_KEY", raising=False)
    monkeypatch.delenv("LLM_BASE_URL", raising=False)
    monkeypatch.delenv("NCBI_API_KEY", raising=False)
    monkeypatch.delenv("OPENALEX_API_KEYS", raising=False)
    monkeypatch.delenv("OPENALEX_API_KEY", raising=False)
    monkeypatch.setattr("httpx.Client", _Client)
    calls = 0

    def probe():
        nonlocal calls
        calls += 1
        return {
            "configured": True,
            "attempted": True,
            "available": True,
            "pool": {
                "configured": 12,
                "ready": 11,
                "cooling": 1,
                "leased": 0,
                "disabled": 0,
            },
            "status_summary": "调度请求成功",
        }

    monkeypatch.setattr(doctor, "_probe_semantic_scholar_scheduler", probe)
    result = doctor._probe_live_api_endpoints(probe_semantic_scholar=True)

    assert calls == 1
    assert result["semantic_scholar_live"]["available"] is True


def test_explicit_openalex_probe_uses_one_scheduler_operation(monkeypatch):
    monkeypatch.delenv("LLM_API_KEY", raising=False)
    monkeypatch.delenv("LLM_BASE_URL", raising=False)
    monkeypatch.delenv("NCBI_API_KEY", raising=False)
    monkeypatch.delenv("SEMANTIC_SCHOLAR_API_KEYS", raising=False)
    monkeypatch.delenv("SEMANTIC_SCHOLAR_API_KEY", raising=False)
    monkeypatch.setattr("httpx.Client", _Client)
    calls = 0

    def probe():
        nonlocal calls
        calls += 1
        return {
            "configured": True,
            "attempted": True,
            "available": True,
            "pool": {
                "configured": 18,
                "ready": 17,
                "cooling": 1,
                "leased": 0,
                "disabled": 0,
            },
            "status_summary": "调度请求成功",
        }

    monkeypatch.setattr(doctor, "_probe_openalex_scheduler", probe)
    result = doctor._probe_live_api_endpoints(probe_openalex=True)

    assert calls == 1
    assert result["openalex_live"]["available"] is True
