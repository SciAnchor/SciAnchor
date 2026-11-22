from __future__ import annotations

import hashlib
import json

import pytest
import requests

from paperfetch.datasets.ncbi import NcbiEutilsClient, NcbiEutilsError


class FakeResponse:
    def __init__(
        self,
        *,
        payload=None,
        content: bytes | None = None,
        status: int = 200,
        headers=None,
    ):
        self._payload = payload
        self.content = (
            content if content is not None else json.dumps(payload).encode("utf-8")
        )
        self.status_code = status
        self.headers = {
            "Content-Type": "application/json; charset=UTF-8",
            "X-RateLimit-Limit": "10",
            "X-RateLimit-Remaining": "9",
            **(headers or {}),
        }
        self.closed = False

    def json(self):
        if self._payload is None:
            return json.loads(self.content)
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            response = requests.Response()
            response.status_code = self.status_code
            raise requests.HTTPError(response=response)

    def close(self):
        self.closed = True


class RoutingSession:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def request(self, method, url, **kwargs):
        self.calls.append((method, url, kwargs))
        return self.responses.pop(0)

    def close(self):
        return None


def validation_responses():
    return [
        FakeResponse(payload={"einforesult": {"dbinfo": [{"dbname": "nuccore"}]}}),
        FakeResponse(payload={"esearchresult": {"idlist": ["123"]}}),
        FakeResponse(payload={"result": {"123": {"accessionversion": "NM_007294.4"}}}),
        FakeResponse(
            content=b">NM_007294.4 test\nACGT\n",
            headers={"Content-Type": "text/plain"},
        ),
    ]


def test_validate_accession_adds_credentials_without_reporting_secret(monkeypatch):
    session = RoutingSession(validation_responses())
    monkeypatch.setattr("paperfetch.datasets.ncbi.time.sleep", lambda _seconds: None)
    client = NcbiEutilsClient(
        api_key="secret-key",
        tool="spc-test",
        email="test@example.org",
        requests_per_second=10,
        session=session,
    )

    report = client.validate_accession()

    assert report["status"] == "validated"
    assert report["authenticated"] is True
    assert report["advertised_limit"] == 10
    assert report["fasta_records"] == 1
    assert report["fasta_bases"] == 4
    assert report["sha256"] == hashlib.sha256(b">NM_007294.4 test\nACGT\n").hexdigest()
    assert "secret-key" not in json.dumps(report)
    for _, _, kwargs in session.calls:
        assert kwargs["params"]["api_key"] == "secret-key"
        assert kwargs["params"]["tool"] == "spc-test"
        assert kwargs["params"]["email"] == "test@example.org"


def test_anonymous_client_enforces_public_rate_ceiling():
    with pytest.raises(NcbiEutilsError) as raised:
        NcbiEutilsClient(
            api_key="", requests_per_second=3.1, session=RoutingSession([])
        )
    assert raised.value.error_code == "invalid_ncbi_request_rate"


def test_keyed_client_enforces_keyed_rate_ceiling():
    with pytest.raises(NcbiEutilsError) as raised:
        NcbiEutilsClient(
            api_key="secret", requests_per_second=10.1, session=RoutingSession([])
        )
    assert raised.value.error_code == "invalid_ncbi_request_rate"


def test_validate_accession_rejects_identity_mismatch(monkeypatch):
    responses = validation_responses()
    responses[2] = FakeResponse(
        payload={"result": {"123": {"accessionversion": "OTHER.1"}}}
    )
    monkeypatch.setattr("paperfetch.datasets.ncbi.time.sleep", lambda _seconds: None)
    client = NcbiEutilsClient(requests_per_second=3, session=RoutingSession(responses))
    with pytest.raises(NcbiEutilsError) as raised:
        client.validate_accession()
    assert raised.value.error_code == "ncbi_accession_identity_mismatch"
    assert raised.value.error_class == "identity_mismatch"


def test_download_record_writes_payload_and_redacted_report(tmp_path, monkeypatch):
    payload = b">NM_007294.4 test\nACGT\n"
    session = RoutingSession(
        [FakeResponse(content=payload, headers={"Content-Type": "text/plain"})]
    )
    monkeypatch.setattr("paperfetch.datasets.ncbi.time.sleep", lambda _seconds: None)
    target = tmp_path / "NM_007294.4.fa"
    client = NcbiEutilsClient(
        api_key="secret-key",
        requests_per_second=10,
        session=session,
    )

    report = client.download_record(
        db="nuccore",
        identifier="NM_007294.4",
        rettype="fasta",
        retmode="text",
        output_path=target,
    )

    assert target.read_bytes() == payload
    saved = json.loads((tmp_path / "NM_007294.4.fa.validation.json").read_text())
    assert saved == report
    assert report["sha256"] == hashlib.sha256(payload).hexdigest()
    assert "secret-key" not in json.dumps(report)


def test_download_record_rejects_html(tmp_path, monkeypatch):
    session = RoutingSession(
        [
            FakeResponse(
                content=b"<html>challenge</html>", headers={"Content-Type": "text/html"}
            )
        ]
    )
    monkeypatch.setattr("paperfetch.datasets.ncbi.time.sleep", lambda _seconds: None)
    client = NcbiEutilsClient(requests_per_second=3, session=session)
    with pytest.raises(NcbiEutilsError, match="HTML"):
        client.download_record(
            db="nuccore",
            identifier="NM_007294.4",
            rettype="fasta",
            retmode="text",
            output_path=tmp_path / "record.fa",
        )
    assert not (tmp_path / "record.fa").exists()
