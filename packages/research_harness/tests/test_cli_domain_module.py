"""Shape-lock tests for the split CLI domain command module."""

from __future__ import annotations

import json

from click.testing import CliRunner

from research_harness.cli import CS_DOMAIN_SEED, main
from research_harness.cli_domain import CS_DOMAIN_SEED as MODULE_CS_DOMAIN_SEED
from research_harness.storage.db import Database


def test_cli_domain_module_seed_constant_is_reexported() -> None:
    assert CS_DOMAIN_SEED == MODULE_CS_DOMAIN_SEED
    assert len(MODULE_CS_DOMAIN_SEED) == 15


def test_domain_seed_still_registered_from_split_module(tmp_path) -> None:
    db_path = tmp_path / "domain-module.db"
    Database(db_path).migrate()

    result = CliRunner().invoke(
        main,
        ["--db", str(db_path), "--json", "domain", "seed", "cs"],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["kind"] == "cs"
    assert payload["inserted"] == [name for name, _ in MODULE_CS_DOMAIN_SEED]
    assert payload["updated"] == []
    assert payload["skipped"] == []
