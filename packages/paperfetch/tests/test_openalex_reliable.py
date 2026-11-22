import httpx
import pytest

from paperfetch.sources.key_pool import PersistentApiKeyPool
from paperfetch.sources.openalex import (
    OpenAlexAuthenticationError,
    OpenAlexSource,
    _openalex_api_keys,
)


@pytest.mark.asyncio
async def test_openalex_401_disables_only_rejected_key(tmp_path, monkeypatch):
    monkeypatch.delenv("OPENALEX_API_KEYS", raising=False)
    monkeypatch.delenv("OPENALEX_API_KEY", raising=False)
    calls = []

    class Client:
        async def request(self, method, url, **kwargs):
            calls.append(kwargs["params"]["api_key"])
            request = httpx.Request(method, url)
            if len(calls) == 1:
                return httpx.Response(401, request=request)
            return httpx.Response(200, request=request, json={"id": "W1"})

    pool = PersistentApiKeyPool(
        "openalex",
        ["bad", "good"],
        db_path=tmp_path / "keys.db",
        min_interval_seconds=0,
    )
    response = await OpenAlexSource(Client(), key_pool=pool)._request_reliably(
        "GET", "https://api.openalex.org/works/W1"
    )

    assert response.status_code == 200
    assert len(calls) == 2
    assert calls[0] != calls[1]
    assert (await pool.snapshot())["disabled"] == 1


@pytest.mark.asyncio
async def test_openalex_429_is_internal_and_rotates(tmp_path, monkeypatch):
    monkeypatch.delenv("OPENALEX_API_KEYS", raising=False)
    monkeypatch.delenv("OPENALEX_API_KEY", raising=False)
    calls = []

    class Client:
        async def request(self, method, url, **kwargs):
            calls.append(kwargs["params"]["api_key"])
            request = httpx.Request(method, url)
            if len(calls) == 1:
                return httpx.Response(
                    429, request=request, headers={"Retry-After": "0.01"}
                )
            return httpx.Response(200, request=request, json={"id": "W1"})

    pool = PersistentApiKeyPool(
        "openalex",
        ["key-a", "key-b"],
        db_path=tmp_path / "keys.db",
        min_interval_seconds=0,
    )
    response = await OpenAlexSource(Client(), key_pool=pool)._request_reliably(
        "GET", "https://api.openalex.org/works/W1"
    )

    assert response.status_code == 200
    assert len(calls) == 2
    assert calls[0] != calls[1]


@pytest.mark.asyncio
async def test_openalex_all_rejected_is_permanent_error(tmp_path, monkeypatch):
    monkeypatch.delenv("OPENALEX_API_KEYS", raising=False)
    monkeypatch.delenv("OPENALEX_API_KEY", raising=False)

    class Client:
        async def request(self, method, url, **kwargs):
            return httpx.Response(403, request=httpx.Request(method, url))

    pool = PersistentApiKeyPool(
        "openalex",
        ["a", "b"],
        db_path=tmp_path / "keys.db",
        min_interval_seconds=0,
    )
    source = OpenAlexSource(Client(), key_pool=pool)
    with pytest.raises(OpenAlexAuthenticationError):
        await source._request_reliably("GET", "https://api.openalex.org/works/W1")


@pytest.mark.asyncio
async def test_openalex_source_details_preserves_authentication_error(
    tmp_path, monkeypatch
):
    monkeypatch.delenv("OPENALEX_API_KEYS", raising=False)
    monkeypatch.delenv("OPENALEX_API_KEY", raising=False)

    class Client:
        async def request(self, method, url, **kwargs):
            return httpx.Response(401, request=httpx.Request(method, url))

    pool = PersistentApiKeyPool(
        "openalex",
        ["rejected"],
        db_path=tmp_path / "keys.db",
        min_interval_seconds=0,
    )
    source = OpenAlexSource(Client(), key_pool=pool)

    with pytest.raises(OpenAlexAuthenticationError):
        await source.fetch_source_details("1234-5678", id_type="issn")


def test_openalex_multi_key_config_is_deduplicated(monkeypatch):
    monkeypatch.setenv("OPENALEX_API_KEYS", "a,b;a")
    monkeypatch.setenv("OPENALEX_API_KEY", "b")
    assert _openalex_api_keys() == ("a", "b")
