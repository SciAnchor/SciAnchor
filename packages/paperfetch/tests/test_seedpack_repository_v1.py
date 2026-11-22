"""SPC 1.0 Seed Pack 原子仓储与故障注入。"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from paperfetch.artifacts.models import ArtifactProducer
from paperfetch.artifacts.store import materialize_artifact
from paperfetch.papers.models import (
    BibliographicMetadata,
    FieldProvenance,
    FulltextState,
    IdentifierSet,
    IdentityVerification,
    MetadataProvenance,
    PaperRecord,
    PdfTerminal,
    SourceSnapshot,
    new_paper_id,
)
from paperfetch.seedpacks.repository import SeedPackError, SeedPackRepository


pytestmark = [pytest.mark.integration, pytest.mark.contract]


def _paper(doi: str, *, paper_id: str | None = None) -> PaperRecord:
    now = datetime.now(timezone.utc)
    return PaperRecord(
        paper_id=paper_id or new_paper_id(),
        identifiers=IdentifierSet(doi=doi),
        bibliographic=BibliographicMetadata(title=f"Paper {doi}"),
        provenance=MetadataProvenance(
            sources=[
                SourceSnapshot(source_id="src-1", source="crossref", record_id=doi)
            ],
            fields=[
                FieldProvenance(field="identifiers.doi", source_ids=["src-1"]),
                FieldProvenance(field="bibliographic.title", source_ids=["src-1"]),
            ],
        ),
        created_at=now,
        updated_at=now,
    )


def test_initialize_add_and_reload_use_one_fact_file(tmp_path: Path):
    repository = SeedPackRepository.initialize(tmp_path / "pack", name="Test Pack")
    first = _paper("10.1000/one")
    snapshot = repository.add([first])
    reloaded = repository.load()
    assert snapshot == reloaded
    assert len(reloaded.papers) == 1
    assert reloaded.papers[0].identifiers.doi == "10.1000/one"
    manifest = json.loads(repository.manifest_path.read_text(encoding="utf-8"))
    assert set(manifest) == {
        "schema_version",
        "seed_pack_id",
        "layout_version",
        "name",
        "created_at",
    }
    assert not (repository.root / "seed_papers.jsonl").exists()
    transaction = next((repository.internal_root / "transactions").glob("*.json"))
    assert json.loads(transaction.read_text(encoding="utf-8"))["status"] == "committed"


def test_legacy_seed_pack_is_rejected_without_mutation(tmp_path: Path):
    root = tmp_path / "legacy"
    root.mkdir()
    legacy = root / "seed_papers.jsonl"
    original = '{"paper_id":"spc:legacy"}\n'
    legacy.write_text(original, encoding="utf-8")
    with pytest.raises(SeedPackError) as caught:
        SeedPackRepository(root).load()
    assert caught.value.code == "unsupported_legacy_seed_pack"
    assert legacy.read_text(encoding="utf-8") == original
    assert not (root / "manifest.json").exists()


def test_mixed_legacy_and_v1_layout_is_always_rejected(tmp_path: Path):
    repository = SeedPackRepository.initialize(tmp_path / "pack")
    (repository.root / "seed_papers.jsonl").write_text("\n", encoding="utf-8")
    with pytest.raises(SeedPackError) as caught:
        repository.load()
    assert caught.value.code == "unsupported_legacy_seed_pack"


def test_duplicate_identifier_validation_happens_before_atomic_replace(tmp_path: Path):
    repository = SeedPackRepository.initialize(tmp_path / "pack")
    repository.add([_paper("10.1000/one")])
    before = repository.papers_path.read_bytes()
    with pytest.raises(SeedPackError) as caught:
        repository.add([_paper("10.1000/one")])
    assert caught.value.code == "duplicate_strong_identifier"
    assert repository.papers_path.read_bytes() == before
    assert len(repository.load().papers) == 1


def test_missing_artifact_blocks_replace_and_preserves_truth_source(
    tmp_path: Path, make_pdf_bytes
):
    repository = SeedPackRepository.initialize(tmp_path / "pack")
    first = _paper("10.1000/one")
    repository.add([first])
    before = repository.papers_path.read_bytes()
    missing = repository.root / "missing.pdf"
    pointer = {
        "artifact_id": f"art_{'a' * 32}",
        "kind": "paper_pdf",
        "manifest_path": f"artifacts/{first.paper_id}/pdf/art_{'a' * 32}/manifest.json",
    }
    updated = first.model_copy(
        update={
            "revision": 2,
            "updated_at": datetime.now(timezone.utc),
            "fulltext": FulltextState(
                pdf=PdfTerminal(
                    status="available",
                    artifact=pointer,
                    identity=IdentityVerification(
                        method="doi", target="10.1000/one", observed="10.1000/one"
                    ),
                )
            ),
        }
    )
    with pytest.raises(SeedPackError) as caught:
        repository.replace([PaperRecord.model_validate(updated.model_dump())])
    assert caught.value.code == "artifact_manifest_missing"
    assert repository.papers_path.read_bytes() == before
    assert repository.load().papers[0].fulltext.pdf.status == "not_attempted"


def test_verified_pdf_record_round_trips_with_physical_probe(
    tmp_path: Path, make_pdf_bytes
):
    repository = SeedPackRepository.initialize(tmp_path / "pack")
    first = _paper("10.1000/one")
    repository.add([first])
    source = tmp_path / "paper.pdf"
    source.write_bytes(
        make_pdf_bytes(title=first.bibliographic.title, doi=first.identifiers.doi)
    )
    pointer = materialize_artifact(
        repository.root,
        paper_id=first.paper_id,
        kind="paper_pdf",
        files={"article_pdf": source},
        producer=ArtifactProducer(name="identity-gated-download", version="1"),
    )
    updated = first.model_copy(
        update={
            "revision": 2,
            "updated_at": datetime.now(timezone.utc),
            "fulltext": FulltextState(
                pdf=PdfTerminal(
                    status="available",
                    artifact=pointer,
                    identity=IdentityVerification(
                        method="doi", target="10.1000/one", observed="10.1000/one"
                    ),
                )
            ),
        }
    )
    snapshot = repository.replace([PaperRecord.model_validate(updated.model_dump())])
    assert snapshot.artifact_count == 1
    assert snapshot.papers[0].fulltext.pdf.artifact == pointer


def test_replace_requires_exact_revision_increment(tmp_path: Path):
    repository = SeedPackRepository.initialize(tmp_path / "pack")
    first = _paper("10.1000/one")
    repository.add([first])
    skipped = first.model_copy(
        update={"revision": 3, "updated_at": datetime.now(timezone.utc)}
    )
    with pytest.raises(SeedPackError) as caught:
        repository.replace([PaperRecord.model_validate(skipped.model_dump())])
    assert caught.value.code == "paper_revision_conflict"


def test_reload_failure_rolls_back_papers_file(monkeypatch, tmp_path: Path):
    repository = SeedPackRepository.initialize(tmp_path / "pack")
    before = repository.papers_path.read_bytes()
    original_load = repository.load
    calls = 0

    def fail_first_post_replace_load(*, probe_artifacts=True):
        nonlocal calls
        calls += 1
        # transact performs one pre-transaction load; fail the post-replace reload only.
        if calls == 2:
            raise SeedPackError("paper_record_invalid", "故障注入", stage="load")
        return original_load(probe_artifacts=probe_artifacts)

    monkeypatch.setattr(repository, "load", fail_first_post_replace_load)
    with pytest.raises(SeedPackError, match="故障注入"):
        repository.add([_paper("10.1000/one")])
    assert repository.papers_path.read_bytes() == before
    assert original_load().papers == ()
