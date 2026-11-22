from paperfetch.core.public_result import PUBLIC_SCHEMA
from paperfetch.core.information import (
    compact_route_attempts,
    normalize_audit_ref,
    public_download_fact,
    public_parse_fact,
    unescape_public_text,
)


def test_internal_download_fact_keeps_diagnostic_attempts_outside_v2_projection():
    fact = public_download_fact(
        status="available",
        route="public_http",
        identity_verified=True,
        identity_method="doi",
        attempted=compact_route_attempts(
            [
                {
                    "route": "elsevier_api",
                    "error_class": "subscription_required",
                    "error": "no entitlement",
                },
                {"route": "public_http"},
            ]
        ),
    )
    assert fact["route"] == "public_http"
    assert fact["attempted"][0] == {
        "route": "elsevier_api",
        "outcome": "failed",
        "error_class": "subscription_required",
    }
    assert fact["attempted"][-1]["route"] == "public_http"
    assert fact["attempted"][-1]["outcome"] == "succeeded"
    assert "url" not in fact


def test_audit_ref_prefers_path_relative_to_seed_pack(tmp_path):
    root = tmp_path / "pack"
    audit = root / ".spc" / "audit" / "paper.json"
    audit.parent.mkdir(parents=True)
    audit.write_text("{}", encoding="utf-8")
    assert normalize_audit_ref(audit, root) == ".spc/audit/paper.json"


def test_unescape_public_text_clears_html_entities():
    assert unescape_public_text("The Lancet Diabetes &amp; Endocrinology") == (
        "The Lancet Diabetes & Endocrinology"
    )


def test_public_parse_fact_is_unbound_and_not_a_paper_record():
    fact = public_parse_fact(
        status="available",
        input_path="/tmp/a.pdf",
        input_sha256="a" * 64,
        input_size_bytes=2048,
    )
    assert fact["identity_bound"] is False
    assert fact["paper_record_written"] is False
    assert fact["producer"] == "mineru"
    assert "download" not in fact
    assert "route" not in fact


def test_public_contract_has_one_v2_schema():
    assert PUBLIC_SCHEMA == "spc.result.v2"
