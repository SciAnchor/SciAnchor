from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import fitz


ANNOTATOR = (
    Path(__file__).resolve().parents[3]
    / "skills/paper-reading-annotation/scripts/phd_pdf_annotator.py"
)
RESETTER = (
    Path(__file__).resolve().parents[3]
    / "skills/paper-reading-annotation/scripts/reset_rh_pdf_annotations.py"
)


def test_reset_rh_pdf_annotations_script_removes_rh_notes(tmp_path: Path):
    pdf_path = tmp_path / "paper.pdf"
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((72, 72), "A paper with a theory anchor.")
    doc.save(pdf_path)
    doc.close()

    spec_path = tmp_path / "plan.json"
    spec_path.write_text(
        json.dumps(
            {
                "paper_id": 1,
                "title": "Reset Demo",
                "profile": "phd-quick-grasp-v1",
                "annotations": [
                    {
                        "anchor": "theory anchor",
                        "page": 1,
                        "category": "theoretical-innovation",
                        "subject": "理论创新",
                        "comment": "【理论创新】这里是关键抽象。",
                        "priority": 5,
                    }
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    annotated_path = tmp_path / "annotated.pdf"
    subprocess.run(
        [
            sys.executable,
            str(ANNOTATOR),
            "--pdf",
            str(pdf_path),
            "--spec",
            str(spec_path),
            "--out",
            str(annotated_path),
            "--json",
        ],
        check=True,
        text=True,
        capture_output=True,
    )

    cleaned_path = tmp_path / "cleaned.pdf"
    result = subprocess.run(
        [
            sys.executable,
            str(RESETTER),
            "--pdf",
            str(annotated_path),
            "--out",
            str(cleaned_path),
            "--json",
        ],
        check=True,
        text=True,
        capture_output=True,
    )
    receipt = json.loads(result.stdout)
    assert receipt["removed_count"] == 1

    cleaned = fitz.open(cleaned_path)
    annots = []
    for page in cleaned:
        annot = page.first_annot
        while annot:
            annots.append(annot.info)
            annot = annot.next
    cleaned.close()

    assert annots == []
