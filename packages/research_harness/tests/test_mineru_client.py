from __future__ import annotations

import zipfile
from pathlib import Path

from research_harness.integrations.mineru import MinerUClient, MinerUParseItem


def test_mineru_client_batch_flow_uploads_polls_and_extracts(tmp_path):
    pdf = tmp_path / "paper.pdf"
    pdf.write_bytes(b"%PDF-1.4\nbody")
    result_zip = tmp_path / "result.zip"
    with zipfile.ZipFile(result_zip, "w") as archive:
        archive.writestr("full.md", "markdown")
        archive.writestr("layout.json", "{}")
        archive.writestr("paper_content_list.json", "[]")
        archive.writestr("paper_model.json", "{}")
    calls = []
    uploads = []

    def fetcher(url, headers, data, method):
        calls.append((url, headers, data, method))
        if url.endswith("/file-urls/batch"):
            return {
                "batch_id": "batch-1",
                "files": [{"data_id": "7", "upload_url": "https://upload.example/7"}],
            }
        if url.endswith("/extract-results/batch/batch-1"):
            return {
                "results": [
                    {
                        "data_id": "7",
                        "state": "done",
                        "full_zip_url": "https://download.example/7.zip",
                    }
                ]
            }
        raise AssertionError(url)

    def uploader(url, content):
        uploads.append((url, content))

    def binary_fetcher(url, headers):
        assert url == "https://download.example/7.zip"
        assert headers["Authorization"] == "Bearer mineru-token"
        return result_zip.read_bytes()

    client = MinerUClient(
        "mineru-token",
        base_url="https://mineru.example",
        fetcher=fetcher,
        uploader=uploader,
        binary_fetcher=binary_fetcher,
    )
    item = MinerUParseItem(7, "Paper", pdf, tmp_path / "parsed" / "7")

    upload_response = client.request_upload_urls([item])
    failed = client.upload_files([item], upload_response)
    poll_response = client.poll_batch_results("batch-1")
    results = client.download_and_extract([item], poll_response)

    assert failed == []
    assert uploads == [("https://upload.example/7", b"%PDF-1.4\nbody")]
    assert results[0].status == "parsed"
    assert Path(results[0].markdown_path).read_text() == "markdown"
    assert calls[0][0] == "https://mineru.example/api/v4/file-urls/batch"
    assert calls[0][3] == "POST"
