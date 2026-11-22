from __future__ import annotations

import importlib.util
from pathlib import Path


REPO_ROOT = next(
    path
    for path in Path(__file__).resolve().parents
    if (path / "AGENTS.md").exists() and (path / "scripts").exists()
)


def load_guard_module():
    script_path = REPO_ROOT / "scripts" / "check-compatibility-inventory.py"
    spec = importlib.util.spec_from_file_location(
        "compatibility_inventory_guard", script_path
    )
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_compatibility_inventory_guard_accepts_current_inventory():
    module = load_guard_module()

    errors = module.validate_compatibility_inventory(
        audit_text=module.AUDIT_PATH.read_text(encoding="utf-8"),
        inventory_text=module.INVENTORY_PATH.read_text(encoding="utf-8"),
    )

    assert errors == []


def test_compatibility_inventory_guard_detects_missing_tier_b_name():
    module = load_guard_module()
    inventory_text = module.INVENTORY_PATH.read_text(encoding="utf-8").replace(
        "| `query_refine` | wrapper | retrieval expansion workflow | Fold into search/retrieval loop. |\n",
        "",
    )

    errors = module.validate_compatibility_inventory(
        audit_text=module.AUDIT_PATH.read_text(encoding="utf-8"),
        inventory_text=inventory_text,
    )

    assert any("missing Tier B inventory names" in error for error in errors)


def test_compatibility_inventory_guard_detects_invalid_policy():
    module = load_guard_module()
    inventory_text = module.INVENTORY_PATH.read_text(encoding="utf-8").replace(
        "| `query_refine` | wrapper | retrieval expansion workflow | Fold into search/retrieval loop. |",
        "| `query_refine` | maybe | retrieval expansion workflow | Fold into search/retrieval loop. |",
    )

    errors = module.validate_compatibility_inventory(
        audit_text=module.AUDIT_PATH.read_text(encoding="utf-8"),
        inventory_text=inventory_text,
    )

    assert any("invalid policy" in error for error in errors)


def test_compatibility_inventory_guard_rejects_public_tool_names():
    module = load_guard_module()
    inventory_text = module.INVENTORY_PATH.read_text(encoding="utf-8").replace(
        "| `query_refine` | wrapper | retrieval expansion workflow | Fold into search/retrieval loop. |\n",
        "| `query_refine` | wrapper | retrieval expansion workflow | Fold into search/retrieval loop. |\n"
        "| `topic_list` | keep | public surface | Public tools must not be lifecycle-classified as Tier B. |\n",
    )

    errors = module.validate_compatibility_inventory(
        audit_text=module.AUDIT_PATH.read_text(encoding="utf-8"),
        inventory_text=inventory_text,
    )

    assert any("public names in Tier B inventory" in error for error in errors)
