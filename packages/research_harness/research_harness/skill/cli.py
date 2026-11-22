"""Click subcommands for ``rh skill ...``.

Wired into the main CLI in :mod:`research_harness.cli` via ``register(main)``.
Kept in its own module so the 4k-line top-level cli.py doesn't grow further.
"""

from __future__ import annotations

import json
from pathlib import Path

import click

from . import (
    AgentConfig,
    CONFIG_FILENAME,
    build_manifest,
    find_agent_config,
    find_repo_root,
    install as install_skills,
    iter_skill_package_capabilities,
    load_agent_config,
    load_manifest,
    make_explicit_config,
    verify as verify_skills,
    which as which_skill,
    write_manifest,
)


PUBLIC_SUITE_ORDER = ("research", "paper", "review", "zotero", "benchmark")
CRITICAL_AGENT_SKILLS = (
    "research-harness",
    "rh-paper-production",
    "rh-paper-figure-generator",
    "figure-quality",
    "rh-self-evolution",
    "publication-pack",
    "final-bundle-quality",
)
DEFAULT_BOOTSTRAP_AGENTS = ("claude-code", "codex")


# ----------------------------- shared helpers --------------------------------


def _resolve_skills_root(skills_root: str | None) -> Path:
    if skills_root:
        return Path(skills_root).expanduser().resolve()
    return find_repo_root()


def _resolve_config(
    target: str | None,
    agent_profile: str | None,
    repo_root: Path,
) -> AgentConfig:
    """Pick the right :class:`AgentConfig` for an install/verify call."""

    if target:
        return make_explicit_config(Path(target).expanduser().resolve())

    if agent_profile:
        # Allow either a bare name (resolved to skills/agent-profiles/<name>.toml)
        # or a path to a TOML file.
        as_path = Path(agent_profile).expanduser()
        if as_path.suffix == ".toml" and as_path.is_file():
            return load_agent_config(as_path)
        candidate = repo_root / "skills" / "agent-profiles" / f"{agent_profile}.toml"
        if candidate.is_file():
            return load_agent_config(candidate)
        raise click.ClickException(
            f"agent profile '{agent_profile}' not found "
            f"(looked in {candidate} and as a direct path)"
        )

    cfg_path = find_agent_config()
    if cfg_path is None:
        raise click.ClickException(
            f"no {CONFIG_FILENAME} found. Pass --target PATH or --agent NAME, "
            "or drop a .rh-agent.toml in this directory. See "
            "skills/agent-profiles/ for examples."
        )
    return load_agent_config(cfg_path)


def _emit(ctx: click.Context, payload: object, text_fn) -> None:
    if ctx.obj and ctx.obj.get("json"):
        click.echo(json.dumps(payload, ensure_ascii=False, default=str))
        return
    text_fn()


def _public_suite(skill) -> str:
    return str(skill.extras.get("public_suite") or "unclassified")


def _format_skill_line(skill) -> str:
    line = f"  {skill.name:24s}"
    if skill.tracks:
        line += f"  ({len(skill.tracks)} tracks)"
    return line


def _report_payload(report) -> dict[str, object]:
    return {
        "config_source": str(report.config_source),
        "agent_name": report.agent_name,
        "strategy": report.strategy,
        "install_path": str(report.install_path),
        "summary": report.by_action(),
        "results": [
            {
                "name": r.name,
                "target": str(r.target),
                "action": r.action,
                "reason": r.reason,
            }
            for r in report.results
        ],
    }


def _critical_skill_status(report) -> dict[str, object]:
    by_name = {r.name: r for r in report.results}
    missing = []
    stale = []
    errors = []
    for name in CRITICAL_AGENT_SKILLS:
        result = by_name.get(name)
        if result is None or result.action == "missing":
            missing.append(name)
        elif result.action == "stale":
            stale.append(name)
        elif result.action == "error":
            errors.append(name)
    return {
        "required": list(CRITICAL_AGENT_SKILLS),
        "missing": missing,
        "stale": stale,
        "errors": errors,
        "ready": not (missing or stale or errors),
    }


def _load_or_build_manifest(root: Path):
    try:
        return load_manifest(root)
    except FileNotFoundError:
        manifest = build_manifest(root)
        write_manifest(manifest, root)
        return manifest


def _agent_config_for_profile(agent_profile: str, root: Path) -> AgentConfig:
    return _resolve_config(None, agent_profile, root)


# ----------------------------- subcommands -----------------------------------


@click.group("skill")
def skill_group() -> None:
    """Manage Research Harness skills (index, install, verify)."""


@skill_group.command("index")
@click.option(
    "--skills-root",
    default=None,
    help="Repo root that contains the skills/ directory. Auto-detected if omitted.",
)
@click.option(
    "--write/--no-write",
    default=True,
    help="Write skills/manifest.json (default) or just print.",
)
@click.pass_context
def skill_index(
    ctx: click.Context,
    skills_root: str | None,
    write: bool,
) -> None:
    """Rebuild skills/manifest.json from SKILL.md front-matter."""

    root = _resolve_skills_root(skills_root)
    manifest = build_manifest(root)
    if write:
        path = write_manifest(manifest, root)
        click.echo(f"Indexed {len(manifest.skills)} skills -> {path}")
    else:
        click.echo(json.dumps(manifest.to_dict(), indent=2, ensure_ascii=False))


@skill_group.command("list")
@click.option("--skills-root", default=None)
@click.option(
    "--triggers", is_flag=True, help="Show full description (incl. triggers)."
)
@click.option(
    "--suite",
    type=click.Choice(PUBLIC_SUITE_ORDER),
    default=None,
    help="Only show skills in one public suite.",
)
@click.option(
    "--group-by-suite",
    is_flag=True,
    help="Group text output by public_suite metadata.",
)
@click.pass_context
def skill_list(
    ctx: click.Context,
    skills_root: str | None,
    triggers: bool,
    suite: str | None,
    group_by_suite: bool,
) -> None:
    """List every shipped skill."""

    root = _resolve_skills_root(skills_root)
    try:
        manifest = load_manifest(root)
    except FileNotFoundError:
        manifest = build_manifest(root)

    skills = [
        skill
        for skill in manifest.skills
        if suite is None or _public_suite(skill) == suite
    ]
    payload = manifest.to_dict()
    payload["skills"] = [skill.to_dict() for skill in skills]
    if suite:
        payload["suite"] = suite
    if ctx.obj and ctx.obj.get("json"):
        click.echo(json.dumps(payload, ensure_ascii=False, default=str))
        return

    if group_by_suite:
        for group in (*PUBLIC_SUITE_ORDER, "unclassified"):
            grouped = [skill for skill in skills if _public_suite(skill) == group]
            if not grouped:
                continue
            click.echo(f"{group}:")
            for skill in grouped:
                click.echo(_format_skill_line(skill))
                if triggers and skill.description:
                    click.echo(f"      {skill.description}")
        click.echo(f"\nTotal: {len(skills)} skills under {manifest.skills_dir}/")
        return

    for skill in skills:
        click.echo(_format_skill_line(skill))
        if triggers and skill.description:
            click.echo(f"      {skill.description}")
    click.echo(f"\nTotal: {len(skills)} skills under {manifest.skills_dir}/")


@skill_group.command("capabilities")
@click.option("--skills-root", default=None)
@click.pass_context
def skill_capabilities(ctx: click.Context, skills_root: str | None) -> None:
    """List v2 skill packages as runtime capability manifests."""

    root = _resolve_skills_root(skills_root)
    capabilities = [cap.to_dict() for cap in iter_skill_package_capabilities(root)]
    payload = {
        "schema_version": "rh.skill_capabilities.v0",
        "capabilities": capabilities,
    }
    if ctx.obj and ctx.obj.get("json"):
        click.echo(json.dumps(payload, ensure_ascii=False, default=str))
        return

    for capability in capabilities:
        click.echo(
            f"  {capability['name']:24s}  {capability['capability_type']}  "
            f"{capability['version']}"
        )
    click.echo(f"\nTotal: {len(capabilities)} v2 skill capabilities")


@skill_group.command("install")
@click.argument("names", nargs=-1)
@click.option("--skills-root", default=None, help="Repo root with skills/ directory.")
@click.option("--target", default=None, help="Force install path; bypass agent config.")
@click.option(
    "--agent",
    "agent_profile",
    default=None,
    help="Use a profile from skills/agent-profiles/<NAME>.toml or a path to a .toml.",
)
@click.option("--dry-run", is_flag=True, help="Show what would happen, no writes.")
@click.pass_context
def skill_install(
    ctx: click.Context,
    names: tuple[str, ...],
    skills_root: str | None,
    target: str | None,
    agent_profile: str | None,
    dry_run: bool,
) -> None:
    """Install skills into the agent's expected location.

    Without --target/--agent, looks up .rh-agent.toml from CWD upward.
    """

    root = _resolve_skills_root(skills_root)
    try:
        manifest = load_manifest(root)
    except FileNotFoundError:
        manifest = build_manifest(root)
        write_manifest(manifest, root)

    config = _resolve_config(target, agent_profile, root)
    report = install_skills(
        manifest,
        config,
        root,
        dry_run=dry_run,
        only=list(names) or None,
    )

    if ctx.obj and ctx.obj.get("json"):
        click.echo(
            json.dumps(
                {
                    **_report_payload(report),
                },
                ensure_ascii=False,
            )
        )
        return

    click.echo(
        f"agent={report.agent_name} strategy={report.strategy} "
        f"target={report.install_path}"
    )
    click.echo(f"config: {report.config_source}")
    for r in report.results:
        marker = {
            "created": "+",
            "updated": "~",
            "skipped": "=",
            "error": "!",
            "runtime-only": "@",
        }.get(r.action, "?")
        suffix = f"  ({r.reason})" if r.reason else ""
        click.echo(f"  {marker} {r.name:24s} -> {r.target}{suffix}")
    counts = report.by_action()
    click.echo("summary: " + ", ".join(f"{k}={v}" for k, v in sorted(counts.items())))


@skill_group.command("verify")
@click.option("--skills-root", default=None)
@click.option("--target", default=None)
@click.option("--agent", "agent_profile", default=None)
@click.option(
    "--strict-extra",
    is_flag=True,
    help="Treat non-RH skills found in the install directory as failures.",
)
@click.pass_context
def skill_verify(
    ctx: click.Context,
    skills_root: str | None,
    target: str | None,
    agent_profile: str | None,
    strict_extra: bool,
) -> None:
    """Compare installed skills against the manifest."""

    root = _resolve_skills_root(skills_root)
    manifest = load_manifest(root)
    config = _resolve_config(target, agent_profile, root)
    report = verify_skills(manifest, config, root)

    if ctx.obj and ctx.obj.get("json"):
        click.echo(
            json.dumps(
                _report_payload(report),
                ensure_ascii=False,
            )
        )
        return

    for r in report.results:
        click.echo(f"  [{r.action:8s}] {r.name:24s}  {r.reason}")
    counts = report.by_action()
    click.echo("summary: " + ", ".join(f"{k}={v}" for k, v in sorted(counts.items())))
    bad_actions = ["missing", "stale", "error"]
    if strict_extra:
        bad_actions.append("extra")
    bad = sum(counts.get(k, 0) for k in bad_actions)
    if bad:
        ctx.exit(1)


@skill_group.command("bootstrap")
@click.option("--skills-root", default=None)
@click.option(
    "--agent",
    "agent_profiles",
    multiple=True,
    help="Agent profile to install/verify. May be repeated. Defaults to Claude Code and Codex.",
)
@click.option("--dry-run", is_flag=True, help="Show what would happen, no writes.")
@click.pass_context
def skill_bootstrap(
    ctx: click.Context,
    skills_root: str | None,
    agent_profiles: tuple[str, ...],
    dry_run: bool,
) -> None:
    """Install and verify the critical RH skill set for agent runtimes."""

    root = _resolve_skills_root(skills_root)
    manifest = _load_or_build_manifest(root)
    agents = agent_profiles or DEFAULT_BOOTSTRAP_AGENTS
    agent_reports = []
    overall_ready = True
    for agent_name in agents:
        config = _agent_config_for_profile(agent_name, root)
        install_report = install_skills(
            manifest,
            config,
            root,
            dry_run=dry_run,
        )
        verify_report = (
            verify_skills(manifest, config, root) if not dry_run else install_report
        )
        critical = _critical_skill_status(verify_report)
        overall_ready = overall_ready and bool(critical["ready"])
        agent_reports.append(
            {
                "agent": agent_name,
                "install": _report_payload(install_report),
                "verify": _report_payload(verify_report),
                "critical_skills": critical,
                "ready": bool(critical["ready"]),
            }
        )

    payload = {
        "schema_version": "rh.skill_bootstrap.v1",
        "dry_run": dry_run,
        "ready": overall_ready,
        "agents": agent_reports,
    }
    if ctx.obj and ctx.obj.get("json"):
        click.echo(json.dumps(payload, ensure_ascii=False, default=str))
        return

    click.echo(
        "RH skill bootstrap " + ("ready" if overall_ready else "needs attention")
    )
    for report in agent_reports:
        click.echo(f"agent={report['agent']} ready={report['ready']}")
        critical = report["critical_skills"]
        for key in ("missing", "stale", "errors"):
            values = critical[key]
            if values:
                click.echo(f"  {key}: {', '.join(values)}")
    if not overall_ready and not dry_run:
        ctx.exit(1)


@skill_group.command("doctor")
@click.option("--skills-root", default=None)
@click.option(
    "--agent",
    "agent_profiles",
    multiple=True,
    help="Agent profile to verify. May be repeated. Defaults to Claude Code and Codex.",
)
@click.pass_context
def skill_doctor(
    ctx: click.Context,
    skills_root: str | None,
    agent_profiles: tuple[str, ...],
) -> None:
    """Verify that critical RH skills are installed for agent runtimes."""

    root = _resolve_skills_root(skills_root)
    manifest = _load_or_build_manifest(root)
    agents = agent_profiles or DEFAULT_BOOTSTRAP_AGENTS
    agent_reports = []
    overall_ready = True
    for agent_name in agents:
        config = _agent_config_for_profile(agent_name, root)
        verify_report = verify_skills(manifest, config, root)
        critical = _critical_skill_status(verify_report)
        overall_ready = overall_ready and bool(critical["ready"])
        agent_reports.append(
            {
                "agent": agent_name,
                "verify": _report_payload(verify_report),
                "critical_skills": critical,
                "ready": bool(critical["ready"]),
            }
        )

    payload = {
        "schema_version": "rh.skill_doctor.v1",
        "ready": overall_ready,
        "agents": agent_reports,
    }
    if ctx.obj and ctx.obj.get("json"):
        click.echo(json.dumps(payload, ensure_ascii=False, default=str))
        return

    click.echo("RH skill doctor " + ("ready" if overall_ready else "needs attention"))
    for report in agent_reports:
        click.echo(f"agent={report['agent']} ready={report['ready']}")
        critical = report["critical_skills"]
        for key in ("missing", "stale", "errors"):
            values = critical[key]
            if values:
                click.echo(f"  {key}: {', '.join(values)}")
    if not overall_ready:
        ctx.exit(1)


@skill_group.command("which")
@click.argument("name")
@click.option("--skills-root", default=None)
@click.option("--target", default=None)
@click.option("--agent", "agent_profile", default=None)
@click.pass_context
def skill_which(
    ctx: click.Context,
    name: str,
    skills_root: str | None,
    target: str | None,
    agent_profile: str | None,
) -> None:
    """Show where a skill would be / is installed."""

    root = _resolve_skills_root(skills_root)
    manifest = load_manifest(root)
    config = _resolve_config(target, agent_profile, root)
    path = which_skill(manifest, config, name)
    if path is None:
        raise click.ClickException(f"skill '{name}' not found in manifest")
    click.echo(str(path))


# ----------------------------- registration ----------------------------------


def register(main_group: click.Group) -> None:
    """Attach this skill subcommand tree to the main ``rh`` CLI."""

    main_group.add_command(skill_group)
