from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import fitz


SCRIPT = (
    Path(__file__).resolve().parents[3]
    / "skills/paper-reading-annotation/scripts/phd_pdf_annotator.py"
)


def test_phd_pdf_annotator_applies_highlights_from_spec(tmp_path: Path):
    pdf_path = tmp_path / "paper.pdf"
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((72, 72), "This paper defines a new research problem for agents.")
    page.insert_text((72, 110), "Theoretical innovation is a reusable taxonomy.")
    doc.save(pdf_path)
    doc.close()

    spec_path = tmp_path / "plan.json"
    spec_path.write_text(
        json.dumps(
            {
                "paper_id": 1,
                "title": "Demo Paper",
                "profile": "phd-quick-grasp-v1",
                "annotations": [
                    {
                        "anchor": "defines a new research problem",
                        "page": 1,
                        "category": "problem",
                        "subject": "问题定义",
                        "comment": "【问题定义】这里定义论文要解决的问题。",
                        "priority": 5,
                    },
                    {
                        "anchor": "reusable taxonomy",
                        "page": 1,
                        "category": "theoretical-innovation",
                        "subject": "理论创新",
                        "comment": "【理论创新】这里说明可复用 taxonomy。",
                        "priority": 5,
                    },
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    out_path = tmp_path / "annotated.pdf"
    result = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--pdf",
            str(pdf_path),
            "--spec",
            str(spec_path),
            "--out",
            str(out_path),
            "--json",
        ],
        check=True,
        text=True,
        capture_output=True,
    )
    receipt = json.loads(result.stdout)
    assert receipt["applied_count"] == 2
    assert receipt["missing_count"] == 0

    annotated = fitz.open(out_path)
    annotations = []
    for page in annotated:
        annot = page.first_annot
        while annot:
            annotations.append(annot.info)
            annot = annot.next
    annotated.close()

    assert len(annotations) == 2
    assert any("RH-PHD-v1" in (info.get("content") or "") for info in annotations)
    assert {info.get("subject") for info in annotations} == {
        "问题定义 · problem",
        "理论创新 · theoretical-innovation",
    }


def test_phd_pdf_annotator_uses_v2_marker_for_content_primitives_profile(
    tmp_path: Path,
):
    pdf_path = tmp_path / "paper-v2.pdf"
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((72, 72), "The method relies on a critical algorithm step.")
    doc.save(pdf_path)
    doc.close()

    spec_path = tmp_path / "plan-v2.json"
    spec_path.write_text(
        json.dumps(
            {
                "paper_id": 2,
                "title": "Demo Paper V2",
                "profile": "zotero-content-primitives-v2",
                "annotations": [
                    {
                        "anchor": "critical algorithm step",
                        "page": 1,
                        "category": "algorithm-step",
                        "subject": "算法步骤",
                        "comment": "【算法步骤】这一步决定方法能否真正工作。",
                        "priority": 5,
                        "primitive_focus": ["deep_read", "section_draft"],
                    }
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    out_path = tmp_path / "annotated-v2.pdf"
    result = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--pdf",
            str(pdf_path),
            "--spec",
            str(spec_path),
            "--out",
            str(out_path),
            "--json",
        ],
        check=True,
        text=True,
        capture_output=True,
    )
    receipt = json.loads(result.stdout)
    assert receipt["applied_count"] == 1
    assert receipt["marker"] == "RH-PHD-v2"

    annotated = fitz.open(out_path)
    page = annotated[0]
    annot = page.first_annot
    info = annot.info if annot else {}
    annotated.close()

    assert "RH-PHD-v2" in (info.get("content") or "")
