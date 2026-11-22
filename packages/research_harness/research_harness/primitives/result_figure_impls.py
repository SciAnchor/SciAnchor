"""Deterministic execution layer for exemplar-planned result-figure suites.

The EAG design layer (``exemplar_curate/retrieve/plan`` with
``unit_type="figure_suite"``) produces a FORM-only suite spec by analogy
to published exemplars; this primitive renders that spec from the caller's
recorded experiment records via ``research_harness.visualization``. No LLM is
involved in rendering — form-not-content is guaranteed by construction because
every number comes from the records, and panels without matching records are
skipped and reported, never invented.
"""

from __future__ import annotations

import json
import sqlite3
from typing import Any

from .registry import (
    FIGURE_PACKAGE_SPEC,
    FIGURE_SUITE_PLAN_SPEC,
    FIGURE_SUITE_RENDER_SPEC,
    register_primitive,
)
from .types import (
    FigurePackageOutput,
    FigurePlanItem,
    FigureSuitePlanOutput,
    FigureSuiteRenderedFigure,
    FigureSuiteRenderOutput,
)


@register_primitive(FIGURE_SUITE_RENDER_SPEC)
def figure_suite_render(
    *,
    db=None,
    topic_id=None,
    spec: dict[str, Any] | None = None,
    records: list[dict[str, Any]] | None = None,
    output_dir: str = "",
    suite_id: str = "experiment",
    formats: list[str] | tuple[str, ...] = ("png",),
    claim_boundary: str = "observed_or_reported_results",
    style_profile: str | None = None,
    critique: bool = False,
    **_: Any,
) -> FigureSuiteRenderOutput:
    """Render composed multi-panel result figures from a suite spec + records."""
    if not str(output_dir or "").strip():
        raise ValueError("figure_suite_render requires output_dir")
    from research_harness.visualization.experiment_figures import (
        render_figure_suite_spec,
    )

    suite = render_figure_suite_spec(
        spec=spec or {},
        records=records or [],
        output_dir=output_dir,
        suite_id=suite_id,
        formats=tuple(formats or ("png",)),
        claim_boundary=claim_boundary,
        style_profile=style_profile,
    )

    reports: list[dict[str, Any]] = []
    if critique and suite.figures:
        from research_harness.visualization.result_figure_refs import (
            critique_rendered_figures,
        )

        paths = [
            figure.paths.get("png") or next(iter(figure.paths.values()), "")
            for figure in suite.figures
        ]
        reports = critique_rendered_figures(
            [path for path in paths if path],
            style_profile=str(suite.provenance.get("style_profile", "")),
        )

    return FigureSuiteRenderOutput(
        status=suite.status,
        output_dir=str(output_dir),
        style_profile=str(suite.provenance.get("style_profile", "")),
        figures=[
            FigureSuiteRenderedFigure(
                figure_id=figure.figure_id,
                title=figure.title,
                figure_type=figure.figure_type,
                paths=dict(figure.paths),
                provenance=dict(figure.provenance),
            )
            for figure in suite.figures
        ],
        critique=reports,
        provenance=dict(suite.provenance),
    )


# --------------------------------------------------------------------------- #
# figure_suite_plan — the two-phase design brain                              #
# --------------------------------------------------------------------------- #


def _spec_figures(spec: dict[str, Any]) -> list[dict[str, Any]]:
    inner = spec
    for wrapper in ("plan", "suite", "figure_suite"):
        nested = inner.get(wrapper) if isinstance(inner, dict) else None
        if isinstance(nested, dict) and "figures" in nested:
            inner = nested
            break
    figs = inner.get("figures") if isinstance(inner, dict) else None
    return [f for f in figs if isinstance(f, dict)] if isinstance(figs, list) else []


_PIPELINE_TO_ROUTE = {
    "generative": "illustration",
    "deterministic": "figure_suite_render",
    "external_asset": "external_asset",
    "latex": "tikz_local",
}


def _figure_modules_for_spec(spec: dict[str, Any]) -> dict[str, str]:
    """Role → approved drawing route from ROLE_PIPELINE (nail 2)."""
    from .exemplar_impls import ROLE_PIPELINE

    modules: dict[str, str] = {}
    for fig in _spec_figures(spec):
        role = str(fig.get("role") or "").strip()
        if not role:
            continue
        pipeline = str(fig.get("pipeline") or ROLE_PIPELINE.get(role) or "").strip()
        route = _PIPELINE_TO_ROUTE.get(pipeline, "")
        if route:
            modules[role] = route
    return modules


def _missing_draw_fields(spec: dict[str, Any]) -> list[str]:
    """The three pre-draw fields: venue, grammar, modules. Missing any → cannot draw."""
    inner = spec if isinstance(spec, dict) else {}
    for wrapper in ("plan", "suite", "figure_suite", "spec"):
        nested = inner.get(wrapper) if isinstance(inner, dict) else None
        if isinstance(nested, dict) and (
            nested.get("figures")
            or nested.get("target_venue")
            or nested.get("figure_modules")
        ):
            inner = {**inner, **nested}
            break
    missing: list[str] = []
    if not str(inner.get("target_venue") or "").strip():
        missing.append("target_venue")
    grammar = inner.get("venue_figure_grammar") or inner.get("result_plot_policy")
    if not (isinstance(grammar, dict) and grammar):
        missing.append("venue_figure_grammar")
    modules = inner.get("figure_modules")
    if not (isinstance(modules, dict) and modules):
        missing.append("figure_modules")
    return missing


def _stamp_draw_fields(spec: dict[str, Any]) -> dict[str, Any]:
    """Ensure the three pre-draw fields are present on a suite spec."""
    modules = _figure_modules_for_spec(spec)
    if modules:
        spec["figure_modules"] = modules
    grammar = spec.get("venue_figure_grammar") or spec.get("result_plot_policy")
    if isinstance(grammar, dict) and grammar:
        spec["venue_figure_grammar"] = dict(grammar)
        spec.setdefault("result_plot_policy", dict(grammar))
    return spec


def _export_generative_figures(spec: dict[str, Any]) -> list[FigurePlanItem]:
    """Map generative-pipeline spec figures onto FigurePlanItem for figure_generate.

    For finish_rulebook case_exhibit / failure_gallery roles, fill missing
    purpose/caption from the domain exhibit blueprint so the illustration route receives
    a concrete walkthrough brief instead of an empty generative stub.
    """
    from .exemplar_impls import ROLE_PIPELINE

    try:
        from research_harness._workflow.execution.finish_form_contract import (
            build_exhibit_blueprint,
            infer_domain_family,
        )
    except Exception:  # pragma: no cover - optional wiring
        build_exhibit_blueprint = None  # type: ignore[assignment]
        infer_domain_family = None  # type: ignore[assignment]

    hint_bits = [
        str(spec.get("discipline") or ""),
        str(spec.get("target_venue") or ""),
        str(spec.get("article_type") or ""),
        str(spec.get("notes") or ""),
    ]
    for fig0 in _spec_figures(spec):
        hint_bits.append(str(fig0.get("title") or ""))
        hint_bits.append(str(fig0.get("purpose") or ""))
    hint = " ".join(hint_bits)
    bp = None
    if build_exhibit_blueprint is not None:
        family = "cs"
        if infer_domain_family is not None:
            family = infer_domain_family(hint)
        bp = build_exhibit_blueprint(domain_family=family, manuscript_hint=hint)

    out: list[FigurePlanItem] = []
    for fig in _spec_figures(spec):
        role = str(fig.get("role", "") or "")
        pipeline = str(fig.get("pipeline", "") or ROLE_PIPELINE.get(role, ""))
        if pipeline != "generative":
            continue
        title = str(fig.get("title", "") or "")
        caption = str(fig.get("caption_skeleton", "") or "")
        purpose = str(fig.get("purpose", "") or "")
        layout = str(fig.get("composition", "") or "")
        if bp is not None and role in {"case_exhibit", "failure_gallery"}:
            if not title.strip():
                title = bp.section_title
            if not caption.strip():
                caption = bp.figure_caption_skeleton
            if not purpose.strip():
                purpose = bp.drafting_prompt
            if not layout.strip():
                layout = "1x4" if bp.domain_family == "medicine" else "1x3"
            # Keep role visible for downstream PB / render logs.
            if f"role={role}" not in purpose:
                purpose = f"[role={role}; genre={bp.genre}] {purpose}"
        out.append(
            FigurePlanItem(
                figure_id=str(fig.get("figure_id", "") or ""),
                kind="figure",
                title=title,
                caption=caption,
                section=str(fig.get("section", "") or ""),
                purpose=purpose,
                suggested_layout=layout,
                placement_hint=str(fig.get("placement", "") or ""),
            )
        )
    return out


def _prune_spec(spec: dict[str, Any], prune_ids: set[str]) -> dict[str, Any]:
    """Return a copy of the suite spec with pruned figure_ids removed."""
    inner = spec
    for wrapper in ("plan", "suite", "figure_suite"):
        nested = inner.get(wrapper) if isinstance(inner, dict) else None
        if isinstance(nested, dict) and "figures" in nested:
            inner = nested
            break
    figures = [
        f for f in _spec_figures(spec) if str(f.get("figure_id", "")) not in prune_ids
    ]
    order_source = inner.get("narrative_order") or spec.get("narrative_order") or []
    order = [fid for fid in order_source if str(fid) not in prune_ids]
    pruned = {
        "paper_type": inner.get("paper_type") or spec.get("paper_type") or "empirical",
        "style_profile": inner.get("style_profile") or spec.get("style_profile") or "",
        "figures": figures,
        "narrative_order": order,
        "notes": inner.get("notes") or spec.get("notes") or "",
    }
    for key in ("target_venue", "discipline", "article_type"):
        value = inner.get(key) or spec.get(key)
        if value:
            pruned[key] = value
    policy = inner.get("result_plot_policy") or spec.get("result_plot_policy")
    if isinstance(policy, dict):
        pruned["result_plot_policy"] = dict(policy)
    grammar = inner.get("venue_figure_grammar") or spec.get("venue_figure_grammar")
    if isinstance(grammar, dict):
        pruned["venue_figure_grammar"] = dict(grammar)
    elif isinstance(policy, dict):
        pruned["venue_figure_grammar"] = dict(policy)
    return _stamp_draw_fields(pruned)


def _topic_plot_context(db: Any, topic_id: Any) -> dict[str, str]:
    """Read optional venue/domain signals without making planning DB-dependent."""
    if db is None or topic_id is None:
        return {"target_venue": "", "discipline": ""}
    conn = None
    try:
        conn = db.connect()
        row = conn.execute(
            """SELECT t.target_venue, d.name AS domain_name
               FROM topics t
               LEFT JOIN domains d ON d.id = t.domain_id
               WHERE t.id = ?""",
            (int(topic_id),),
        ).fetchone()
        if row is None:
            return {"target_venue": "", "discipline": ""}
        return {
            "target_venue": str(row["target_venue"] or "").strip(),
            "discipline": str(row["domain_name"] or "").strip(),
        }
    except (sqlite3.Error, KeyError, TypeError, ValueError, AttributeError) as exc:
        return {
            "target_venue": "",
            "discipline": "",
            "metadata_warning": f"topic_metadata_unavailable:{type(exc).__name__}",
        }
    finally:
        if conn is not None:
            conn.close()


@register_primitive(FIGURE_SUITE_PLAN_SPEC)
def figure_suite_plan(
    *,
    db=None,
    topic_id=None,
    target_content: str = "",
    source: str = "matrix",
    records: list[dict[str, Any]] | None = None,
    matrix_json: dict[str, Any] | None = None,
    prior_plan: dict[str, Any] | None = None,
    paper_type: str = "empirical",
    style_profile: str | None = None,
    top_k: int = 3,
    min_quality: float = 7.0,
    max_papers: int = 6,
    _model: str | None = None,
    **_: Any,
) -> FigureSuitePlanOutput:
    """Design (v1) or reconcile (v2) a whole-paper figure contract."""
    from research_harness.visualization.figure_suite_planning import (
        derive_logging_requirements,
        reconcile,
        synthesize_planned_records,
    )

    if str(source) == "records":
        # ----- v2: reconcile a prior design spec against actual records -----
        if not isinstance(prior_plan, dict) or not _spec_figures(prior_plan):
            raise ValueError(
                "figure_suite_plan source=records requires a prior_plan with figures"
            )
        actual = records or []
        result = reconcile(prior_plan, actual)
        prune_ids = set(result.get("prune", []))
        from research_harness.visualization.figure_knowledge import (
            stamp_suite_knowledge,
        )

        v2 = stamp_suite_knowledge(
            _stamp_draw_fields(_prune_spec(prior_plan, prune_ids))
        )
        return FigureSuitePlanOutput(
            version_phase="v2_reconciled",
            paper_type=str(v2.get("paper_type", "empirical")),
            style_profile=str(v2.get("style_profile", "")),
            spec=v2,
            reconciliation={
                "pruned": sorted(prune_ids),
                "unsatisfied": result.get("unsatisfied", []),
                "unfed_figure_types": result.get("unfed_figure_types", []),
                "verdict": result.get("verdict", ""),
            },
            logging_requirements=derive_logging_requirements(v2),
            generative_figures=_export_generative_figures(v2),
            inventory_source="explicit_records",
            inventory_mode="observed",
        )

    # ----- v1: design from a planned (or observed) inventory -----
    from research_harness.visualization.experiment_figures import (
        summarize_records_for_plan,
    )

    from .exemplar_impls import (
        exemplar_curate,
        exemplar_plan,
        exemplar_retrieve,
    )

    synth_records, inv_source, inv_mode = synthesize_planned_records(
        db=db, topic_id=topic_id, records=records, matrix_json=matrix_json
    )
    inventory = summarize_records_for_plan(synth_records)
    topic_context = _topic_plot_context(db, topic_id)
    topic_target_venue = topic_context["target_venue"]
    topic_discipline = topic_context["discipline"]

    from research_harness.visualization.result_plot_policy import (
        resolve_result_plot_policy,
    )

    planning_policy = resolve_result_plot_policy(
        explicit_style_profile=style_profile,
        target_venue=topic_target_venue,
        discipline=topic_discipline,
        article_type=paper_type,
        records=synth_records,
    )

    # Keep retrieval content-first, then prepend the deterministic grammar only
    # for planning so prompt truncation cannot discard venue/evidence policy.
    target = (
        f"{str(target_content).strip()}\n\nPAPER TYPE: {paper_type}"
        f"\nRECORD INVENTORY (the only data available to plot):\n"
        f"{json.dumps(inventory, ensure_ascii=False)}"
    )
    # The planner truncates what it is handed, and the two things it may not plan
    # without — the policy it must follow and the records it may plot — go first for
    # the same reason. The inventory was last, so the sentence calling it "the only
    # data available to plot" had never been true: csmopen12's figure target renders
    # 7,953 characters against a 3,500 bound, and the planner saw 36% of the paper
    # and none of the inventory. It planned four result figures filtering on fields
    # no record carries, which is what planning blind looks like.
    planning_target = (
        "DETERMINISTIC RESULT-PLOT POLICY (follow for recorded-data panels):\n"
        f"{json.dumps(planning_policy.as_provenance(), ensure_ascii=False, sort_keys=True)}"
        f"\n\nRECORD INVENTORY (the only data available to plot):\n"
        f"{json.dumps(inventory, ensure_ascii=False)}"
        f"\n\nPAPER TYPE: {paper_type}\n{str(target_content).strip()}"
    )

    units = []
    exemplar_ids: list[int] = []
    model_used = ""
    if db is not None and topic_id is not None:
        cur = exemplar_curate(
            db=db,
            topic_id=topic_id,
            unit_type="figure_suite",
            min_quality=min_quality,
            max_papers=max_papers,
            _model=_model,
        )
        units = cur.units
        model_used = cur.model_used
    ret_units = units
    if units:
        ret = exemplar_retrieve(
            unit_type="figure_suite",
            target_content=target,
            units=units,
            top_k=top_k,
            _model=_model,
        )
        ret_units = ret.ranked
    pl = exemplar_plan(
        unit_type="figure_suite",
        target_content=planning_target,
        retrieved_units=ret_units,
        _model=_model,
    )
    spec = dict(pl.plan) if isinstance(pl.plan, dict) else {}
    if not _spec_figures(spec):
        raise ValueError(
            "figure_suite_plan planner returned no figures"
            + (f" ({pl.plan_error})" if pl.plan_error else "")
            + f"; {len(ret_units)} exemplars ranked"
            + (f"; reply began {pl.plan_reply[:300]!r}" if pl.plan_reply else "")
        )
    exemplar_ids = list(pl.exemplar_ids)
    model_used = pl.model_used or model_used

    # Apply caller overrides, then deterministic venue/evidence policy.  Topic
    # signals outrank planner-selected style, while a real caller override wins.
    resolved_paper_type = str(spec.get("paper_type") or paper_type)
    target_venue = topic_target_venue or str(spec.get("target_venue") or "").strip()
    discipline = topic_discipline or str(spec.get("discipline") or "").strip()

    policy = resolve_result_plot_policy(
        explicit_style_profile=style_profile,
        spec_style_profile=spec.get("style_profile"),
        target_venue=target_venue,
        discipline=discipline,
        article_type=str(spec.get("article_type") or resolved_paper_type),
        records=synth_records,
    )
    policy_provenance = policy.as_provenance()
    metadata_warning = topic_context.get("metadata_warning", "")
    if metadata_warning:
        policy_provenance = {
            **policy_provenance,
            "warnings": [*policy_provenance["warnings"], metadata_warning],
        }
    from research_harness.visualization.figure_knowledge import stamp_suite_knowledge

    spec = stamp_suite_knowledge(
        _stamp_draw_fields(
            {
                **spec,
                "paper_type": resolved_paper_type,
                "target_venue": target_venue,
                "discipline": discipline,
                "style_profile": policy.policy.style_profile,
                "result_plot_policy": policy_provenance,
                "venue_figure_grammar": policy_provenance,
            }
        )
    )

    coverage = reconcile(spec, synth_records)
    return FigureSuitePlanOutput(
        version_phase="v1_design",
        paper_type=resolved_paper_type,
        style_profile=str(spec.get("style_profile", "")),
        spec=spec,
        matrix_coverage={
            "verdict": coverage.get("verdict", ""),
            "unfeedable_panels": coverage.get("unsatisfied", []),
            "unfed_experiments": coverage.get("unfed_figure_types", []),
        },
        logging_requirements=derive_logging_requirements(spec),
        generative_figures=_export_generative_figures(spec),
        inventory_source=inv_source,
        inventory_mode=inv_mode,
        exemplar_ids=exemplar_ids,
        model_used=model_used,
    )


@register_primitive(FIGURE_PACKAGE_SPEC)
def figure_package(
    *,
    db=None,
    topic_id=None,
    task: dict[str, Any] | None = None,
    output_dir: str = "",
    units: list[dict[str, Any]] | None = None,
    figure_id: str | None = None,
    **_: Any,
) -> FigurePackageOutput:
    """Build one top-one Figure Package. Public path keeps the fake provider."""
    if not str(output_dir or "").strip():
        raise ValueError("figure_package requires output_dir")
    if not isinstance(task, dict):
        raise ValueError("figure_package requires task")
    from research_harness.visualization.figure_package_workflow import (
        build_figure_package,
    )

    result = build_figure_package(
        task=task,
        output_dir=output_dir,
        units=units,
        figure_id=figure_id,
    )
    return FigurePackageOutput(
        status=str(result.get("status") or "fail"),
        output_dir=str(output_dir),
        package=result.get("package"),
        trace=list(result.get("trace") or []),
    )
