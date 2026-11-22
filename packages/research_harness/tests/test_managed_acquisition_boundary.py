"""Keep scholarly sources behind the one shared suite.

Entry points build providers only through ``build_provider_suite``, so the
suite stays the single place that decides which sources run and that no
source is ever given an API key.
"""

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "research_harness"


def test_workflow_entry_points_do_not_construct_direct_scholarly_providers():
    paths = [
        "primitives/impls.py",
        "_workflow/execution/llm_primitives.py",
        "discover/evidence.py",
        "cli_search.py",
        "cli_paper_acquisition.py",
    ]
    forbidden = {
        "OpenAlexProvider",
        "SemanticScholarProvider",
        "ArxivProvider",
        "PubMedProvider",
        "SciverseClient",
    }
    violations = []
    for name in paths:
        tree = ast.parse((ROOT / name).read_text())
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                target = (
                    node.func.id
                    if isinstance(node.func, ast.Name)
                    else getattr(node.func, "attr", "")
                )
                if target in forbidden:
                    violations.append((name, node.lineno, target))
    assert not violations, violations


def test_shared_suite_constructs_only_keyless_sources_and_spc():
    tree = ast.parse((ROOT / "paper_source_clients.py").read_text())
    builders = [
        n
        for n in tree.body
        if isinstance(n, ast.FunctionDef)
        and n.name in {"build_provider_suite", "_keyless_provider"}
    ]
    assert len(builders) == 2
    calls = [
        n
        for builder in builders
        for n in ast.walk(builder)
        if isinstance(n, ast.Call)
        and isinstance(n.func, ast.Name)
        and n.func.id.endswith("Provider")
    ]
    assert {call.func.id for call in calls} == {
        "PaperVaultProvider",
        "SPCProvider",
        "SemanticScholarProvider",
        "OpenAlexProvider",
        "CrossrefProvider",
        "ArxivProvider",
        "PubMedProvider",
        "OpenReviewProvider",
    }
    keyed = [
        (call.func.id, kw.arg)
        for call in calls
        for kw in call.keywords
        if kw.arg in {"api_key", "access_token", "token"}
    ]
    assert not keyed, keyed


def test_legacy_acquisition_helpers_have_no_production_callers():
    forbidden = {
        "_legacy_download_single",
        "_enrich_from_openalex",
        "_enrich_from_s2",
        "_enrich_from_pubmed",
    }
    violations = []
    for path in ROOT.rglob("*.py"):
        for node in ast.walk(ast.parse(path.read_text())):
            if not isinstance(node, ast.Call):
                continue
            target = (
                node.func.id
                if isinstance(node.func, ast.Name)
                else getattr(node.func, "attr", "")
            )
            if target in forbidden:
                violations.append((str(path.relative_to(ROOT)), node.lineno, target))
    assert not violations, violations
