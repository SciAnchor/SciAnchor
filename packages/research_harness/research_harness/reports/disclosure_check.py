"""Blind-submission disclosure checker (2026-08-08).

Enforces the mechanisable half of the disclosure rule:

    The blind_submission package must mimic what a real submission in this
    scenario would release — and nothing more. Open data: description only, no
    payload. Internal data: partial, desensitized, with a scenario-appropriate
    justification. Give only what the paper cites as important and a reviewer
    would ask to see; never more.

Why "never more" is a rule and not a preference: **over-disclosure is itself a
detectable trace**. A real education study cannot release full individual
student records, so a package containing them is anomalous on its face — the
discriminator does not need to find an inconsistency, the package shape already
is one.

Deliberate scope split:

* **Checked here** — every present asset was declared; every declared asset is
  present; each asset carries a role, an evidence class, a justification where
  the role requires one, and an answer to "why would a reviewer ask for this?".
* **NOT checked here** — whether the *amount* is right. That is a scenario
  judgement belonging to the human and the simulator, and pretending to
  mechanise it would make the checker's silence mean more than it does.

This module is standalone. It is wired into no execution path and gates nothing
automatically; it must be run deliberately before blind review. Promoting it
into the pre-release quality contract is a later, separate decision that should
wait until the three-paper evidence shows the manifest shape holds.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

DISCLOSURE_CHECK_SCHEMA = "rh.schema.report.disclosure_check.v1"

#: Asset roles a blind submission may contain.
KNOWN_ROLES: frozenset[str] = frozenset(
    {
        "manuscript",
        "figure",
        "latex_source",
        "references",
        "internal_data_sample",
        "open_data",
        "analysis_code",
        "analysis_output",
        "supplementary",
        "reader_documentation",
    }
)

#: Roles whose disclosure needs a scenario-appropriate justification, because
#: releasing them at all is a judgement call rather than a default.
ROLES_REQUIRING_JUSTIFICATION: frozenset[str] = frozenset(
    {"internal_data_sample", "open_data", "supplementary"}
)

#: Open data is cited, not shipped: a reviewer fetches it from its public
#: source. Bundling the payload adds bulk a real submission would not have.
ROLES_FORBIDDING_PAYLOAD: frozenset[str] = frozenset({"open_data"})

_NOT_CHECKED = (
    "whether the disclosed amount is correct for this scenario "
    "(human and simulator judgement)",
    "whether a justification is scientifically adequate, as opposed to present",
    "whether the manuscript's claims are supported by the disclosed evidence",
)


def _finding(code: str, path: str, detail: str) -> dict[str, str]:
    return {"code": code, "path": path, "detail": detail}


def check_disclosure_package(
    manifest_path: str | Path,
    package_dir: str | Path,
) -> dict[str, Any]:
    """Compare a disclosure manifest against the actual package contents."""
    manifest_file = Path(manifest_path)
    if not manifest_file.exists():
        raise FileNotFoundError(f"disclosure manifest not found: {manifest_file}")

    manifest = json.loads(manifest_file.read_text(encoding="utf-8"))
    assets = list(manifest.get("assets") or [])
    root = Path(package_dir)

    findings: list[dict[str, str]] = []
    declared: set[str] = set()

    for asset in assets:
        path = str(asset.get("path") or "").strip()
        role = str(asset.get("role") or "").strip()
        if not path:
            findings.append(
                _finding("asset_without_path", "", "manifest entry has no path")
            )
            continue
        declared.add(path)

        if role not in KNOWN_ROLES:
            findings.append(
                _finding(
                    "unknown_role",
                    path,
                    f"role {role!r} is not one of {sorted(KNOWN_ROLES)}",
                )
            )

        if not str(asset.get("evidence_class") or "").strip():
            findings.append(
                _finding("missing_evidence_class", path, "no evidence_class declared")
            )

        if not str(asset.get("why_a_reviewer_would_ask") or "").strip():
            findings.append(
                _finding(
                    "missing_reviewer_rationale",
                    path,
                    "the rule is stated in terms of what a reviewer would ask "
                    "to see; that answer must be recorded",
                )
            )

        if (
            role in ROLES_REQUIRING_JUSTIFICATION
            and not str(asset.get("justification") or "").strip()
        ):
            code = (
                "internal_data_missing_justification"
                if role == "internal_data_sample"
                else "missing_justification"
            )
            findings.append(
                _finding(
                    code,
                    path,
                    f"role {role!r} requires a scenario-appropriate justification",
                )
            )

        exists = (root / path).exists()
        if not exists:
            findings.append(
                _finding(
                    "declared_asset_missing",
                    path,
                    "declared in the manifest but absent from the package",
                )
            )
        elif role in ROLES_FORBIDDING_PAYLOAD:
            findings.append(
                _finding(
                    "open_data_payload_included",
                    path,
                    "open data is described and cited, not shipped; a real "
                    "submission points a reviewer at the public source",
                )
            )

    present: set[str] = set()
    if root.exists():
        present = {str(p.relative_to(root)) for p in root.rglob("*") if p.is_file()}

    for path in sorted(present - declared):
        findings.append(
            _finding(
                "undeclared_asset",
                path,
                "present in the package but not declared; over-disclosure is "
                "itself a detectable trace",
            )
        )

    return {
        "schema": DISCLOSURE_CHECK_SCHEMA,
        "manifest": str(manifest_file),
        "package_dir": str(root),
        "episode_id": manifest.get("episode_id"),
        "assets_declared": len(declared),
        "assets_present": len(present),
        "passed": not findings,
        "findings": findings,
        "not_checked": list(_NOT_CHECKED),
    }
