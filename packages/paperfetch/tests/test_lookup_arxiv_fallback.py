import json
from types import SimpleNamespace

from paperfetch.cli.lookup import run_lookup


class _EmptySource:
    source_name = "empty"

    def __init__(self, *args, **kwargs):
        pass

    async def lookup(self, identifier, id_type):
        return None


class _Client:
    async def aclose(self):
        return None


def test_lookup_arxiv_uses_strong_identifier_when_metadata_sources_miss(
    monkeypatch, capsys
):
    monkeypatch.setattr("paperfetch.cli.lookup.create_async_client", lambda: _Client())
    monkeypatch.setattr("paperfetch.cli.lookup.OpenAlexSource", _EmptySource)
    monkeypatch.setattr("paperfetch.cli.lookup.SemanticScholarSource", _EmptySource)
    args = SimpleNamespace(
        doi=None,
        pmid=None,
        arxiv="1706.03762v5",
        output_format="json",
    )

    exit_code = run_lookup(args)
    payload = json.loads(capsys.readouterr().out)

    assert exit_code == 0
    assert payload["arxiv_id"] == "1706.03762"
    assert payload["doi"] == "10.48550/arxiv.1706.03762"
    assert payload["fulltext_status"]["pdf_source"] == "arxiv"
    assert payload["_execution_summary"]["metadata_status"] == "success"
