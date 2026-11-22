from paperfetch.core.public_result import to_public_result


def test_flat_candidates_preserve_bibliographic_data():
    for count in (1, 2):
        candidate = {
            "paper_id": "p1",
            "title": "A real title",
            "doi": "10.1234/test",
            "year": 2024,
        }
        payload = to_public_result(
            {
                "schema_version": "spc.command-result.v1",
                "command": "paper.search",
                "status": "completed",
                "items": [
                    {"entity": {"id": str(i)}, "status": "completed", "data": candidate}
                    for i in range(count)
                ],
            }
        )
        records = (
            [payload["data"]]
            if count == 1
            else [item["data"] for item in payload["results"]]
        )
        assert records == [candidate] * count


def test_lookup_preserves_citation_metadata():
    citation = {
        "title": "Paper",
        "authors": [{"name": "Author"}],
        "publication_date": "2024-01-01",
        "venue": {"name": "Journal"},
    }
    payload = to_public_result(
        {
            "schema_version": "spc.command-result.v1",
            "command": "paper.lookup",
            "status": "completed",
            "items": [
                {
                    "entity": {"id": "p1"},
                    "status": "completed",
                    "data": {
                        "paper_id": "p1",
                        "identifiers": {"doi": "10.1234/test"},
                        "citation": citation,
                    },
                }
            ],
        }
    )
    assert payload["data"]["citation"] == citation
