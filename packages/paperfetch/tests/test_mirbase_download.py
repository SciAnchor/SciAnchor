from __future__ import annotations

import json

import pytest

from paperfetch.datasets.mirbase import (
    MirbaseDownloadError,
    decode_mirbase_fasta,
    download_mirbase_current,
)


class FakeResponse:
    def __init__(self, text: str, *, content_type: str = "text/html; charset=utf-8"):
        self.text = text
        self.content = text.encode("utf-8")
        self.headers = {"content-type": content_type}

    def raise_for_status(self) -> None:
        return None


class FakeSession:
    def __init__(self, responses: dict[str, FakeResponse]):
        self.responses = responses
        self.calls: list[tuple[str, object]] = []

    def get(self, url: str, *, timeout: object) -> FakeResponse:
        self.calls.append((url, timeout))
        return self.responses[url.rsplit("/", 1)[-1]]


def test_decode_html_wrapped_mature_fasta():
    payload, records, first_header = decode_mirbase_fasta(
        "<p>&gt;hsa-miR-1<br>ACGU<br>&gt;hsa-miR-2<br>UGCA<br></p>",
        filename="mature.fa",
    )

    assert payload == b">hsa-miR-1\nACGU\n>hsa-miR-2\nUGCA\n"
    assert records == 2
    assert first_header == ">hsa-miR-1"


def test_decode_multiline_hairpin_fasta():
    payload, records, _ = decode_mirbase_fasta(
        "<p>&gt;hairpin-1<br>ACGU<br>UGCA<br></p>", filename="hairpin.fa"
    )

    assert payload == b">hairpin-1\nACGU\nUGCA\n"
    assert records == 1


def test_decode_rejects_challenge_page():
    with pytest.raises(MirbaseDownloadError, match="neither raw FASTA"):
        decode_mirbase_fasta("<html>challenge</html>", filename="mature.fa")


def test_download_writes_atomic_files_and_report(tmp_path):
    session = FakeSession(
        {
            "mature.fa": FakeResponse("<p>&gt;mature<br>ACGU<br></p>"),
            "hairpin.fa": FakeResponse("<p>&gt;hairpin<br>ACGU<br>UGCA<br></p>"),
        }
    )

    report = download_mirbase_current(
        tmp_path, proxy="http://proxy:7897", session=session
    )

    assert (tmp_path / "mature.fa").read_text(encoding="utf-8") == ">mature\nACGU\n"
    assert (tmp_path / "hairpin.fa").read_text(
        encoding="utf-8"
    ) == ">hairpin\nACGU\nUGCA\n"
    saved_report = json.loads(
        (tmp_path / "validation-report.json").read_text(encoding="utf-8")
    )
    assert report == saved_report
    assert report["proxy_mode"] == "explicit"
    assert [item["records"] for item in report["files"]] == [1, 1]
    assert len(session.calls) == 2
