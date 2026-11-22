# Versioning

Research Harness uses SemVer `MAJOR.MINOR.PATCH`. The product version is
independent of skills, paperindex, and llm-router.

## Source of truth

`packages/research_harness/pyproject.toml` `[project].version`.

Keep these equal to it:

- `packages/research_harness/research_harness/__init__.py` `__version__`
- `packages/research_harness_mcp/pyproject.toml` `[project].version`
- `packages/research_harness_mcp/research_harness_mcp/__init__.py` `__version__`

The HTTP API reads `research_harness_mcp.__version__`. Do not hard-code a
second number there.

## Tags

Annotated git tag `vX.Y.Z` on the commit that sets the source of truth to
that number. Tags are immutable. Do not retag.

## When to bump

- **MAJOR** — breaking change to the public CLI, MCP tools, or installable
  package API.
- **MINOR** — compatible addition.
- **PATCH** — bug fix, docs, or gate wording.

Change the source of truth before tagging. Do not tag a number the tree
does not declare.

Schema ids (`wiki_context_pack.v1`, …), skill frontmatter, and the 研枢
copyright display name are not this product version.

GitHub Releases stay on `.github/workflows/release.yml` (`workflow_dispatch`
on an existing tag). Publishing a GitHub Release is a separate, explicit
action from tagging.
