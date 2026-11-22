"""CLI for the Exemplar-Anchored Generation (EAG) engine.

"Stand on the shoulders of giants": curate a quality-gated exemplar library from a
topic's papers, then plan/generate research artifacts by transferring FORM
(structure/style) — never CONTENT — with a deterministic anti-plagiarism gate.

Commands: ``rh exemplar curate|plan|generate|figures|doctor``.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Callable

import click


def _venue_profile_option(ctx, param, value):
    if value is None:
        return None
    try:
        profile = json.loads(value)
    except (ValueError, TypeError) as exc:
        raise click.BadParameter("must be a JSON object", param=param) from exc
    if not isinstance(profile, dict):
        raise click.BadParameter("must be a JSON object", param=param)
    return profile


def _read_target(target: str | None, target_file: str | None) -> str:
    if target_file:
        with open(target_file, "r", encoding="utf-8") as f:
            return f.read()
    return target or ""


def _parse_paper_ids(raw: str | None) -> list[int] | None:
    """Comma/space-separated paper ids; None means auto-select from the topic pool."""
    if not raw or not str(raw).strip():
        return None
    ids: list[int] = []
    for part in str(raw).replace(",", " ").split():
        try:
            ids.append(int(part))
        except ValueError as exc:
            raise click.UsageError(f"invalid --paper-ids value {part!r}") from exc
    return ids or None


def _prep_llm(llm: str) -> None:
    # "direct" pins EAG to the OpenAI-compatible endpoint (OPENAI_BASE_URL),
    # skipping RH's tier router when it is unauthenticated.
    if llm == "direct":
        os.environ["RH_EAG_LLM"] = "openai_direct"


def _source_texts(db, exemplar_ids: list[int]) -> list[str]:
    """Fetch source abstracts for the overlap gate (guard against verbatim reuse)."""
    ids = [i for i in exemplar_ids if i]
    if not ids:
        return []
    conn = db.connect()
    try:
        ph = ",".join("?" * len(ids))
        rows = conn.execute(
            f"SELECT abstract FROM papers WHERE id IN ({ph})", ids
        ).fetchall()
        return [(r["abstract"] or "") for r in rows if r["abstract"]]
    except Exception:
        return []
    finally:
        conn.close()


def _quality_targets_for_topic(db, topic_id: int) -> dict[str, Any]:
    """Venue polish contract for the topic; empty dict if unresolved."""
    try:
        conn = db.connect()
        try:
            row = conn.execute(
                "SELECT target_venue FROM topics WHERE id=?", (int(topic_id),)
            ).fetchone()
        finally:
            conn.close()
        venue = (row["target_venue"] if row else "") or ""
        if not venue:
            return {}
        from research_harness.primitives.venue_prescription import (
            resolve_venue_prescription,
        )

        return resolve_venue_prescription(target_venue=str(venue)).to_dict()
    except Exception:
        return {}


_EAG_STAGE = "write"


def _svc(db):
    from research_harness.orchestrator import OrchestratorService

    return OrchestratorService(db)


def _record_pack(db, topic_id: int, out):
    from research_harness.primitives.types import _to_jsonable

    art = _svc(db).record_artifact(
        topic_id=topic_id,
        stage=_EAG_STAGE,
        artifact_type=f"exemplar_pack_{out.unit_type}",
        title=f"exemplar pack: {out.unit_type} ({out.kept} kept)",
        payload=_to_jsonable(out),
        metadata={
            "unit_type": out.unit_type,
            "kept": out.kept,
            "model": out.model_used,
        },
    )
    # IDX03: also materialize first-class exemplar_units rows for retrieve.
    try:
        from research_harness.retrieval import upsert_exemplar_units

        units = getattr(out, "units", None) or (
            out.get("units") if isinstance(out, dict) else None
        )
        if units:
            upsert_exemplar_units(db, topic_id=int(topic_id), units=list(units))
    except Exception:
        pass
    return art


def _load_pack(db, topic_id: int, unit_type: str):
    from research_harness.primitives.exemplar_impls import _coerce_units

    a = _svc(db).get_latest_artifact(topic_id, _EAG_STAGE, f"exemplar_pack_{unit_type}")
    if a and isinstance(a.payload, dict) and a.payload.get("units"):
        return _coerce_units(a.payload["units"]), a.id
    # Fall back to first-class exemplar_units table (IDX03).
    try:
        from research_harness.retrieval import load_exemplar_unit_rows

        rows = load_exemplar_unit_rows(
            db, topic_id=int(topic_id), unit_type=str(unit_type)
        )
        if rows:
            return _coerce_units(rows), None
    except Exception:
        pass
    return [], None


def _load_lexicon(db, topic_id: int):
    """Latest Track-A domain register lexicon for the topic (recorded artifact, else
    aggregated on the fly from the latest domain_register pack)."""
    a = _svc(db).get_latest_artifact(topic_id, _EAG_STAGE, "exemplar_register_lexicon")
    if a and isinstance(a.payload, dict) and a.payload.get("fields"):
        return a.payload
    units, _pid = _load_pack(db, topic_id, "domain_register")
    if units:
        from research_harness.primitives.exemplar_impls import build_register_lexicon

        return build_register_lexicon(units)
    return None


def _record_plan(db, topic_id: int, pl, pack_id):
    from research_harness.primitives.types import _to_jsonable

    return _svc(db).record_artifact(
        topic_id=topic_id,
        stage=_EAG_STAGE,
        artifact_type=f"exemplar_plan_{pl.unit_type}",
        title=f"exemplar plan: {pl.unit_type}",
        payload=_to_jsonable(pl),
        dependency_artifact_ids=[pack_id] if pack_id else None,
    )


def register(
    main: click.Group,
    get_db: Callable[[click.Context], Any],
    echo: Callable[..., None] | None = None,
) -> None:
    @main.group("exemplar")
    @click.pass_context
    def exemplar(ctx: click.Context) -> None:
        """Exemplar-anchored generation (retrieve giants → transfer FORM not CONTENT)."""

        def report_usage() -> None:
            # On stderr, so --json stdout stays one document; printed on close, even after a failure,
            # because the calls made before it were paid for.
            from research_harness.primitives.exemplar_impls import usage_report

            report = usage_report()
            if report["calls"]:
                click.echo("rh-usage: " + json.dumps(report, sort_keys=True), err=True)

        from research_harness.primitives.exemplar_impls import _CALLS

        _CALLS.clear()  # this command's calls only
        ctx.call_on_close(report_usage)

    @exemplar.command("doctor")
    def doctor() -> None:
        """Report EAG LLM readiness and registered primitives."""
        base = os.environ.get("OPENAI_BASE_URL", "")
        click.echo(f"OPENAI_BASE_URL : {base or '(unset)'}")
        click.echo(
            f"OPENAI_API_KEY  : {'set' if os.environ.get('OPENAI_API_KEY') else 'unset'}"
        )
        click.echo(f"RH_EAG_MODEL    : {os.environ.get('RH_EAG_MODEL', 'gpt-5.5')}")
        from research_harness.primitives import registry as R

        names = [n for n in R.PRIMITIVE_REGISTRY if n.startswith("exemplar_")]
        click.echo("primitives      : " + ", ".join(sorted(names)))

    @exemplar.command("curate")
    @click.option(
        "--venue-profile",
        default=None,
        callback=_venue_profile_option,
        help="Target discipline/profile as a JSON object.",
    )
    @click.option("--topic", type=int, required=True)
    @click.option(
        "--unit-type",
        "unit_type",
        type=click.Choice(
            [
                "skeleton",
                "intro_arc",
                "abstract",
                "style",
                "figure_suite",
                "related_work_arc",
                "method_arc",
                "experiment_arc",
                "discussion_arc",
                "paragraph_moves",
                "abstract_moves",
                "intro_moves",
                "discussion_moves",
                "domain_register",
            ]
        ),
        required=True,
    )
    @click.option("--min-quality", type=float, default=7.0)
    @click.option("--max-papers", type=int, default=6)
    @click.option(
        "--min-tier-score",
        type=int,
        default=85,
        show_default=True,
        help="Min venue_tier_score for auto-selected sources "
        "(85 = CCF-A or CAS-Q1). 0 disables. Ignored when --paper-ids is set.",
    )
    @click.option(
        "--paper-ids",
        default=None,
        help="Comma-separated paper ids; skips the venue-tier filter.",
    )
    @click.option("--model", default=None)
    @click.option("--llm", type=click.Choice(["auto", "direct"]), default="auto")
    @click.option("--json", "as_json", is_flag=True, default=False)
    @click.option(
        "--record/--no-record",
        default=True,
        help="Record the curated pack as an artifact.",
    )
    @click.pass_context
    def curate(
        ctx,
        venue_profile,
        topic,
        unit_type,
        min_quality,
        max_papers,
        min_tier_score,
        paper_ids,
        model,
        llm,
        as_json,
        record,
    ) -> None:
        """Build a quality-gated exemplar library slice from the topic's papers."""
        _prep_llm(llm)
        from research_harness.primitives.exemplar_impls import exemplar_curate
        from research_harness.primitives.types import _to_jsonable

        db = get_db(ctx)
        out = exemplar_curate(
            venue_profile=venue_profile,
            db=db,
            topic_id=topic,
            unit_type=unit_type,
            paper_ids=_parse_paper_ids(paper_ids),
            min_quality=min_quality,
            max_papers=max_papers,
            min_tier_score=min_tier_score,
            _model=model,
        )
        if as_json:
            click.echo(json.dumps(_to_jsonable(out), ensure_ascii=False, indent=2))
        else:
            click.echo(
                f"[{unit_type}] seen={out.candidates_seen} kept={out.kept} "
                f"rejected={out.rejected} model={out.model_used}"
            )
            for u in out.units:
                click.echo(
                    f"  ✓ q{u.quality:g} [{u.venue_tier}] {u.source_title[:52]} — {u.summary[:64]}"
                )
        if record and out.units:
            art = _record_pack(db, topic, out)
            click.echo(f"recorded exemplar_pack_{unit_type} #{art.id} v{art.version}")

    @exemplar.command("plan")
    @click.option(
        "--venue-profile",
        default=None,
        callback=_venue_profile_option,
        help="Target discipline/profile as a JSON object.",
    )
    @click.option("--topic", type=int, required=True)
    @click.option(
        "--unit-type",
        "unit_type",
        type=click.Choice(
            [
                "skeleton",
                "intro_arc",
                "abstract",
                "style",
                "figure_suite",
                "related_work_arc",
                "method_arc",
                "experiment_arc",
                "discussion_arc",
                "paragraph_moves",
                "abstract_moves",
                "intro_moves",
                "discussion_moves",
            ]
        ),
        required=True,
    )
    @click.option(
        "--target", default=None, help="This paper's content/contributions (inline)."
    )
    @click.option(
        "--target-file", "target_file", default=None, help="...or a file with it."
    )
    @click.option("--top-k", type=int, default=3)
    @click.option("--min-quality", type=float, default=7.0)
    @click.option("--max-papers", type=int, default=6)
    @click.option("--model", default=None)
    @click.option("--llm", type=click.Choice(["auto", "direct"]), default="auto")
    @click.option(
        "--reuse-pack",
        is_flag=True,
        default=False,
        help="Reuse the latest recorded exemplar_pack instead of curating fresh.",
    )
    @click.option(
        "--record/--no-record", default=True, help="Record pack/plan as artifacts."
    )
    @click.pass_context
    @click.option(
        "--register/--no-register",
        "use_register",
        default=True,
        help="Bind the plan to the topic's Track-A domain register if one is recorded "
        "(run 'rh exemplar register' first).",
    )
    def plan(
        ctx,
        use_register,
        venue_profile,
        topic,
        unit_type,
        target,
        target_file,
        top_k,
        min_quality,
        max_papers,
        model,
        llm,
        reuse_pack,
        record,
    ) -> None:
        """Curate → retrieve (structure>topic) → plan THIS paper's artifact (FORM only)."""
        _prep_llm(llm)
        tgt = _read_target(target, target_file)
        if not tgt.strip():
            raise click.UsageError("provide --target or --target-file")
        from research_harness.primitives.exemplar_impls import (
            exemplar_curate,
            exemplar_plan,
            exemplar_retrieve,
        )

        db = get_db(ctx)
        pack_id = None
        if reuse_pack:
            units, pack_id = _load_pack(db, topic, unit_type)
            if not units:
                raise click.UsageError(
                    f"no recorded exemplar_pack_{unit_type}; run 'rh exemplar curate' first"
                )
            click.echo(f"reusing exemplar_pack #{pack_id} ({len(units)} exemplars)")
        else:
            cur = exemplar_curate(
                venue_profile=venue_profile,
                db=db,
                topic_id=topic,
                unit_type=unit_type,
                min_quality=min_quality,
                max_papers=max_papers,
                _model=model,
            )
            units = cur.units
            click.echo(f"curated {cur.kept}/{cur.candidates_seen} exemplars")
            if record and units:
                pack_id = _record_pack(db, topic, cur).id
        ret = exemplar_retrieve(
            venue_profile=venue_profile,
            unit_type=unit_type,
            target_content=tgt,
            units=units,
            top_k=top_k,
            _model=model,
        )
        click.echo(
            f"retrieved top-{len(ret.ranked)}: {[u.source_title[:36] for u in ret.ranked]}"
        )
        click.echo(f"  ranking rationale: {ret.rationale}")
        lexicon = _load_lexicon(db, topic) if use_register else None
        if use_register:
            click.echo(
                "domain register: "
                + (
                    f"{lexicon.get('n_papers')} papers"
                    if lexicon
                    else "none recorded (form-only)"
                )
            )
        pl = exemplar_plan(
            venue_profile=venue_profile,
            unit_type=unit_type,
            target_content=tgt,
            retrieved_units=ret.ranked,
            register_lexicon=lexicon,
            _model=model,
        )
        click.echo("\nplan (form-only):")
        click.echo(json.dumps(pl.plan, ensure_ascii=False, indent=2))
        if record:
            art = _record_plan(db, topic, pl, pack_id)
            click.echo(f"\nrecorded exemplar_plan_{unit_type} #{art.id} v{art.version}")

    @exemplar.command("register")
    @click.option("--topic", type=int, required=True)
    @click.option("--max-papers", type=int, default=12)
    @click.option("--min-quality", type=float, default=6.0)
    @click.option(
        "--min-support",
        type=int,
        default=2,
        help="A term enters the lexicon when at least this many papers use it.",
    )
    @click.option(
        "--min-tier",
        "min_tier_score",
        type=int,
        default=85,
        help="Venue grade floor for register sources (85 = CCF-A or CAS-Q1).",
    )
    @click.option(
        "--paper-ids", default=None, help="Comma-separated paper ids (same field)."
    )
    @click.option("--model", default=None)
    @click.option("--llm", type=click.Choice(["auto", "direct"]), default="auto")
    @click.option("--json", "as_json", is_flag=True, default=False)
    @click.option("--record/--no-record", default=True)
    @click.pass_context
    def register_cmd(
        ctx,
        topic,
        max_papers,
        min_quality,
        min_support,
        min_tier_score,
        paper_ids,
        model,
        llm,
        as_json,
        record,
    ) -> None:
        """Track A: curate the DOMAIN REGISTER (canonical field terminology) from same-field
        published papers and aggregate it into a lexicon for plan/generate/critique."""
        _prep_llm(llm)
        from research_harness.primitives.exemplar_impls import (
            build_register_lexicon,
            exemplar_curate,
        )
        from research_harness.primitives.types import _to_jsonable

        db = get_db(ctx)
        cur = exemplar_curate(
            db=db,
            topic_id=topic,
            unit_type="domain_register",
            paper_ids=_parse_paper_ids(paper_ids),
            min_quality=min_quality,
            max_papers=max_papers,
            min_tier_score=min_tier_score,
            _model=model,
        )
        lex = build_register_lexicon(cur.units, min_support=min_support)
        lex_id = None
        if record and cur.units:
            pack = _record_pack(db, topic, cur)
            art = _svc(db).record_artifact(
                topic_id=topic,
                stage=_EAG_STAGE,
                artifact_type="exemplar_register_lexicon",
                title=f"domain register lexicon ({lex['n_papers']} papers)",
                payload=_to_jsonable(lex),
                dependency_artifact_ids=[pack.id],
            )
            lex_id = art.id
        if as_json:
            click.echo(
                json.dumps(
                    {
                        "lexicon": lex,
                        "artifact_id": lex_id,
                        "kept": cur.kept,
                        "seen": cur.candidates_seen,
                    },
                    ensure_ascii=False,
                    indent=2,
                )
            )
            return
        click.echo(
            f"register sources kept {cur.kept}/{cur.candidates_seen}; "
            f"lexicon from {lex['n_papers']} papers (min support {lex['min_support']})"
        )
        for f, items in lex["fields"].items():
            if items:
                click.echo(
                    f"  {f}: "
                    + ", ".join(f"{d['term']}({d['support']})" for d in items[:12])
                )
        if lex["synonyms"]:
            click.echo(
                "  synonyms: "
                + "; ".join(
                    f"{b} -> {g}" for b, g in list(lex["synonyms"].items())[:12]
                )
            )
        if lex_id:
            click.echo(f"recorded exemplar_register_lexicon #{lex_id}")

    @exemplar.command("generate")
    @click.option("--topic", type=int, required=True)
    @click.option(
        "--unit-type",
        "unit_type",
        type=click.Choice(["skeleton", "intro_arc", "abstract", "style"]),
        required=True,
    )
    @click.option("--target", default=None)
    @click.option("--target-file", "target_file", default=None)
    @click.option("--top-k", type=int, default=3)
    @click.option("--max-rounds", type=int, default=2)
    @click.option("--min-quality", type=float, default=7.0)
    @click.option("--max-papers", type=int, default=6)
    @click.option("--model", default=None)
    @click.option("--llm", type=click.Choice(["auto", "direct"]), default="auto")
    @click.option(
        "--section",
        default=None,
        help="Prose section for the section_draft backend (default: mapped from unit-type).",
    )
    @click.option(
        "--backend",
        type=click.Choice(["auto", "self", "section_draft"]),
        default="auto",
    )
    @click.option("--reuse-pack", is_flag=True, default=False)
    @click.option(
        "--register/--no-register",
        "use_register",
        default=True,
        help="Use the topic's Track-A domain register (canonical terms; gate whitelist + "
        "synonym check). Run 'rh exemplar register' first.",
    )
    @click.pass_context
    def generate(
        ctx,
        topic,
        unit_type,
        target,
        target_file,
        top_k,
        max_rounds,
        min_quality,
        max_papers,
        model,
        llm,
        section,
        backend,
        reuse_pack,
        use_register,
    ) -> None:
        """Full loop: (curate|reuse) → retrieve → plan → draft (section_draft or self) → critique → revise."""
        _prep_llm(llm)
        tgt = _read_target(target, target_file)
        if not tgt.strip():
            raise click.UsageError("provide --target or --target-file")
        from research_harness.primitives.exemplar_impls import (
            exemplar_curate,
            exemplar_generate,
            exemplar_retrieve,
        )

        db = get_db(ctx)
        if reuse_pack:
            units, _pid = _load_pack(db, topic, unit_type)
            if not units:
                raise click.UsageError(
                    f"no recorded exemplar_pack_{unit_type}; run 'rh exemplar curate' first"
                )
            click.echo(f"reusing exemplar_pack ({len(units)} exemplars)")
        else:
            cur = exemplar_curate(
                db=db,
                topic_id=topic,
                unit_type=unit_type,
                min_quality=min_quality,
                max_papers=max_papers,
                _model=model,
            )
            units = cur.units
        ret = exemplar_retrieve(
            unit_type=unit_type,
            target_content=tgt,
            units=units,
            top_k=top_k,
            _model=model,
        )
        ex_texts = _source_texts(db, [u.source_paper_id for u in ret.ranked])
        gen = exemplar_generate(
            db=db,
            topic_id=topic,
            unit_type=unit_type,
            target_content=tgt,
            retrieved_units=ret.ranked,
            exemplar_texts=ex_texts,
            section=section,
            backend=backend,
            max_rounds=max_rounds,
            quality_targets=_quality_targets_for_topic(db, topic),
            register_lexicon=(_load_lexicon(db, topic) if use_register else None),
            _model=model,
        )
        reg = (gen.critique or {}).get("conformance", {}).get("register")
        if reg is not None:
            click.echo(
                f"register: {len(reg.get('canonical_terms_used') or [])} canonical terms used, "
                f"{len(reg.get('violations') or [])} non-canonical"
            )
        click.echo(
            f"backend={gen.backend} rounds={gen.rounds} gate_passed={gen.passed} "
            f"overlap={gen.critique.get('overlap_score')} model={gen.model_used}\n"
        )
        click.echo(gen.draft)

    @exemplar.command("figures")
    @click.option("--topic", type=int, required=True)
    @click.option(
        "--records",
        "records_file",
        required=True,
        help='JSON file with experiment records (list, or {"records": [...]}).',
    )
    @click.option(
        "--output-dir",
        "output_dir",
        default=None,
        help="Where rendered figures go (required unless --plan-only).",
    )
    @click.option(
        "--target", default=None, help="This paper's content/contributions (inline)."
    )
    @click.option(
        "--target-file", "target_file", default=None, help="...or a file with it."
    )
    @click.option(
        "--spec",
        "spec_file",
        default=None,
        help="Skip exemplar design and render this suite-spec JSON (offline path).",
    )
    @click.option(
        "--plan-only",
        is_flag=True,
        default=False,
        help="Design the suite spec without rendering.",
    )
    @click.option(
        "--style-profile",
        "style_profile",
        type=click.Choice(
            ["stem_conference", "nature_family", "social_humanities", "biomed_omics"]
        ),
        default=None,
        help="Override the planned discipline style profile.",
    )
    @click.option("--formats", default="png", help="Comma-separated: png,pdf,svg.")
    @click.option("--suite-id", "suite_id", default="experiment")
    @click.option(
        "--claim-boundary",
        "claim_boundary",
        default="observed_or_reported_results",
        help="Recorded evidence boundary for provenance.",
    )
    @click.option(
        "--critique/--no-critique",
        default=True,
        help="Deterministic (and, when configured, VLM) review of rendered figures.",
    )
    @click.option(
        "--vision",
        is_flag=True,
        default=False,
        help="Enable VLM figure analysis of exemplar PDFs during curation.",
    )
    @click.option("--top-k", type=int, default=3)
    @click.option("--min-quality", type=float, default=7.0)
    @click.option("--max-papers", type=int, default=6)
    @click.option("--model", default=None)
    @click.option("--llm", type=click.Choice(["auto", "direct"]), default="auto")
    @click.option("--reuse-pack", is_flag=True, default=False)
    @click.option(
        "--record/--no-record", default=True, help="Record pack/plan/suite artifacts."
    )
    @click.pass_context
    def figures(
        ctx,
        topic,
        records_file,
        output_dir,
        target,
        target_file,
        spec_file,
        plan_only,
        style_profile,
        formats,
        suite_id,
        claim_boundary,
        critique,
        vision,
        top_k,
        min_quality,
        max_papers,
        model,
        llm,
        reuse_pack,
        record,
    ) -> None:
        """Result-figure suite: exemplar design (curate→retrieve→plan) + deterministic render.

        FORM (chart choices, panel composition, style) comes from published
        exemplars; every rendered number comes from --records. With --spec the
        design phase is skipped entirely (no LLM needed).
        """
        _prep_llm(llm)
        if vision:
            os.environ["RH_EAG_FIGURE_VISION"] = "1"
        if not plan_only and not output_dir:
            raise click.UsageError("provide --output-dir (or use --plan-only)")

        with open(records_file, "r", encoding="utf-8") as f:
            payload = json.load(f)
        records = payload.get("records") if isinstance(payload, dict) else payload
        if not isinstance(records, list) or not records:
            raise click.UsageError(f"no records found in {records_file}")

        from research_harness.primitives.types import _to_jsonable
        from research_harness.visualization.experiment_figures import (
            summarize_records_for_plan,
        )

        db = get_db(ctx)
        unit_type = "figure_suite"
        spec: dict | None = None
        pack_id = None
        plan_id = None

        if spec_file:
            with open(spec_file, "r", encoding="utf-8") as f:
                spec = json.load(f)
            click.echo(f"using suite spec from {spec_file} (exemplar design skipped)")
        else:
            tgt = _read_target(target, target_file)
            if not tgt.strip():
                raise click.UsageError("provide --target/--target-file (or --spec)")
            inventory = summarize_records_for_plan(records)
            tgt = (
                tgt.strip()
                + "\n\nRECORD INVENTORY (the only data available to plot):\n"
                + json.dumps(inventory, ensure_ascii=False)
            )
            from research_harness.primitives.exemplar_impls import (
                exemplar_curate,
                exemplar_plan,
                exemplar_retrieve,
            )

            if reuse_pack:
                units, pack_id = _load_pack(db, topic, unit_type)
                if not units:
                    raise click.UsageError(
                        f"no recorded exemplar_pack_{unit_type}; run 'rh exemplar curate' first"
                    )
                click.echo(f"reusing exemplar_pack #{pack_id} ({len(units)} exemplars)")
            else:
                cur = exemplar_curate(
                    db=db,
                    topic_id=topic,
                    unit_type=unit_type,
                    min_quality=min_quality,
                    max_papers=max_papers,
                    _model=model,
                )
                units = cur.units
                click.echo(
                    f"curated {cur.kept}/{cur.candidates_seen} figure-suite exemplars"
                )
                if record and units:
                    pack_id = _record_pack(db, topic, cur).id
            if not units:
                raise click.UsageError(
                    "no figure-suite exemplars survived the quality gate; ingest PDFs for "
                    "the topic's target-venue papers (captions are the curation evidence) "
                    "or lower --min-quality"
                )
            ret = exemplar_retrieve(
                unit_type=unit_type,
                target_content=tgt,
                units=units,
                top_k=top_k,
                _model=model,
            )
            click.echo(
                f"retrieved top-{len(ret.ranked)}: "
                f"{[u.source_title[:36] for u in ret.ranked]}"
            )
            pl = exemplar_plan(
                unit_type=unit_type,
                target_content=tgt,
                retrieved_units=ret.ranked,
                _model=model,
            )
            spec = pl.plan
            click.echo("\nsuite spec (form-only):")
            click.echo(json.dumps(spec, ensure_ascii=False, indent=2))
            if record:
                plan_id = _record_plan(db, topic, pl, pack_id).id
                click.echo(f"recorded exemplar_plan_{unit_type} #{plan_id}")

        if plan_only:
            return

        from research_harness.primitives.result_figure_impls import figure_suite_render

        out = figure_suite_render(
            db=db,
            topic_id=topic,
            spec=spec or {},
            records=records,
            output_dir=output_dir,
            suite_id=suite_id,
            formats=[fmt.strip() for fmt in formats.split(",") if fmt.strip()],
            claim_boundary=claim_boundary,
            style_profile=style_profile,
            critique=critique,
        )
        click.echo(
            f"\nstatus={out.status} style_profile={out.style_profile} "
            f"figures={len(out.figures)}"
        )
        for figure in out.figures:
            click.echo(
                f"  ✓ {figure.figure_id} [{figure.figure_type}] "
                f"{figure.paths.get('png') or next(iter(figure.paths.values()), '')}"
            )
        for note in out.provenance.get("limitations", []):
            click.echo(f"  ! {note}")
        for report in out.critique:
            verdict = report.get("verdict", "")
            marker = "✓" if verdict.startswith("pass") else "✗"
            click.echo(
                f"  {marker} critique[{verdict}] {Path(report['path']).name}"
                + (
                    f" — {'; '.join(report['findings'])}"
                    if report.get("findings")
                    else ""
                )
            )
        if record and out.figures:
            art = _svc(db).record_artifact(
                topic_id=topic,
                stage=_EAG_STAGE,
                artifact_type="figure_suite",
                title=f"figure suite: {len(out.figures)} figures ({out.style_profile})",
                payload=_to_jsonable(out),
                metadata={
                    "style_profile": out.style_profile,
                    "claim_boundary": claim_boundary,
                    "figure_count": len(out.figures),
                },
                dependency_artifact_ids=[i for i in (plan_id,) if i],
            )
            click.echo(f"recorded figure_suite #{art.id} v{art.version}")

    def _load_records(records_file):
        with open(records_file, "r", encoding="utf-8") as f:
            payload = json.load(f)
        recs = payload.get("records") if isinstance(payload, dict) else payload
        if not isinstance(recs, list):
            raise click.UsageError(f"no records found in {records_file}")
        return recs

    @exemplar.command("figure-plan")
    @click.option("--topic", type=int, required=True)
    @click.option(
        "--target", default=None, help="This paper's content/contributions (inline)."
    )
    @click.option(
        "--target-file", "target_file", default=None, help="...or a file with it."
    )
    @click.option(
        "--from-matrix",
        "matrix_file",
        default=None,
        help="Planned matrix JSON {datasets,methods,metric} or {cells:[...]} "
        "for design-phase (v1) grounding.",
    )
    @click.option(
        "--records",
        "records_file",
        default=None,
        help="Observed records JSON: v1 grounding, or v2 reconcile input.",
    )
    @click.option(
        "--reuse-plan",
        is_flag=True,
        default=False,
        help="Reconcile (v2): load the latest recorded figure-suite plan and diff "
        "it against --records.",
    )
    @click.option(
        "--paper-type",
        "paper_type",
        type=click.Choice(["empirical", "survey"]),
        default="empirical",
    )
    @click.option(
        "--style-profile",
        "style_profile",
        type=click.Choice(
            ["stem_conference", "nature_family", "social_humanities", "biomed_omics"]
        ),
        default=None,
    )
    @click.option(
        "--vision",
        is_flag=True,
        default=False,
        help="Enable VLM figure analysis of exemplar PDFs during curation.",
    )
    @click.option("--top-k", type=int, default=3)
    @click.option("--min-quality", type=float, default=7.0)
    @click.option("--max-papers", type=int, default=6)
    @click.option("--model", default=None)
    @click.option("--llm", type=click.Choice(["auto", "direct"]), default="auto")
    @click.option(
        "--record/--no-record",
        default=True,
        help="Record the figure_suite_plan artifact.",
    )
    @click.pass_context
    def figure_plan(
        ctx,
        topic,
        target,
        target_file,
        matrix_file,
        records_file,
        reuse_plan,
        paper_type,
        style_profile,
        vision,
        top_k,
        min_quality,
        max_papers,
        model,
        llm,
        record,
    ) -> None:
        """Two-phase figure contract: design (v1) at experiment-design time, or
        reconcile (v2) against real results at write time.

        v1 (default): grounds on a planned inventory (--from-matrix, --records, or
        the topic's goal_pool/experiment_result), curates figure-suite exemplars,
        and plans the whole-paper figure suite — printing the spec, a bidirectional
        matrix-coverage check, and the per-panel LOGGING REQUIREMENTS to record
        during experiments. v2 (--reuse-plan): diffs the recorded plan against
        --records, pruning unfeedable figures.
        """
        _prep_llm(llm)
        if vision:
            os.environ["RH_EAG_FIGURE_VISION"] = "1"
        from research_harness.primitives.result_figure_impls import figure_suite_plan
        from research_harness.primitives.types import _to_jsonable

        db = get_db(ctx)
        records = _load_records(records_file) if records_file else None
        matrix_json = None
        if matrix_file:
            with open(matrix_file, "r", encoding="utf-8") as f:
                matrix_json = json.load(f)

        if reuse_plan:
            prior = _svc(db).get_latest_artifact(topic, _EAG_STAGE, "figure_suite_plan")
            if not prior or not isinstance(prior.payload, dict):
                raise click.UsageError(
                    "no recorded figure_suite_plan to reconcile; run "
                    "'rh exemplar figure-plan' (v1) first"
                )
            if not records:
                raise click.UsageError("--reuse-plan (v2) requires --records")
            out = figure_suite_plan(
                db=db,
                topic_id=topic,
                target_content=(target or "reconcile"),
                source="records",
                prior_plan=prior.payload.get("spec", prior.payload),
                records=records,
            )
        else:
            tgt = _read_target(target, target_file)
            if not tgt.strip():
                raise click.UsageError("provide --target or --target-file (v1 design)")
            out = figure_suite_plan(
                db=db,
                topic_id=topic,
                target_content=tgt,
                source="matrix",
                records=records,
                matrix_json=matrix_json,
                paper_type=paper_type,
                style_profile=style_profile,
                top_k=top_k,
                min_quality=min_quality,
                max_papers=max_papers,
                _model=model,
            )

        click.echo(
            f"phase={out.version_phase} paper_type={out.paper_type} "
            f"style={out.style_profile} inventory={out.inventory_source}"
            f"({out.inventory_mode})"
        )
        click.echo("\nsuite spec (form-only):")
        click.echo(json.dumps(out.spec, ensure_ascii=False, indent=2))
        if out.generative_figures:
            click.echo(
                "\ngenerative figures (route to figure_generate / rh-paper-figure-generator):"
            )
            for fig in out.generative_figures:
                click.echo(f"  - {fig.figure_id}: {fig.title} — {fig.purpose}")
        cov = out.matrix_coverage or out.reconciliation
        if cov:
            click.echo(f"\ncoverage verdict: {cov.get('verdict')}")
            for u in cov.get("unfeedable_panels") or cov.get("unsatisfied") or []:
                click.echo(
                    f"  ! unfed panel: {u.get('panel')} ({u.get('reason', 'no data')})"
                )
            for t in (
                cov.get("unfed_experiments") or cov.get("unfed_figure_types") or []
            ):
                click.echo(f"  ! experiment with no panel: {t}")
            for fid in out.reconciliation.get("pruned") or []:
                click.echo(f"  - pruned figure: {fid}")
        if out.logging_requirements:
            click.echo("\nLOGGING REQUIREMENTS (record these during experiments):")
            for r in out.logging_requirements:
                click.echo(
                    f"  - {r['panel']} [{r['chart']}]: fields={r['required_fields']} "
                    f"granularity={r['granularity']}"
                )
        if record:
            art = _svc(db).record_artifact(
                topic_id=topic,
                stage=_EAG_STAGE,
                artifact_type="figure_suite_plan",
                title=f"figure suite plan ({out.version_phase}, {out.paper_type})",
                payload=_to_jsonable(out),
                metadata={
                    "version_phase": out.version_phase,
                    "paper_type": out.paper_type,
                    "style_profile": out.style_profile,
                    "inventory_mode": out.inventory_mode,
                },
            )
            click.echo(f"\nrecorded figure_suite_plan #{art.id} v{art.version}")

    @exemplar.command("figure-search")
    @click.option("--query", required=True, help="Caption/interpretation query.")
    @click.option("--topic", type=int, default=None)
    @click.option("--paper-id", type=int, default=None)
    @click.option("--figure-type", default="", help="Optional type substring filter.")
    @click.option("--top-k", type=int, default=10)
    @click.option("--json", "as_json", is_flag=True, default=False)
    @click.pass_context
    def figure_search_cmd(
        ctx, query, topic, paper_id, figure_type, top_k, as_json
    ) -> None:
        """Search extracted_figures by caption/interpretation (W5 local path)."""
        from research_harness.retrieval import search_extracted_figures

        db = get_db(ctx)
        hits = search_extracted_figures(
            db,
            query=query,
            topic_id=topic,
            paper_id=paper_id,
            figure_type=figure_type or "",
            top_k=top_k,
        )
        if as_json:
            click.echo(
                json.dumps(
                    [
                        {
                            "figure_id": h.figure_id,
                            "paper_id": h.paper_id,
                            "figure_number": h.figure_number,
                            "caption": h.caption,
                            "interpretation": h.interpretation,
                            "figure_type": h.figure_type,
                            "quality_score": h.quality_score,
                            "score": h.score,
                            "paper_title": h.paper_title,
                        }
                        for h in hits
                    ],
                    ensure_ascii=False,
                    indent=2,
                )
            )
            return
        if not hits:
            click.echo("no figures matched")
            return
        for h in hits:
            click.echo(
                f"#{h.figure_id} p{h.paper_id} fig{h.figure_number} "
                f"score={h.score:.3f} type={h.figure_type or '?'} "
                f"{(h.caption or h.interpretation)[:80]}"
            )
