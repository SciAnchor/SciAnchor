"""Paper read/artifact subcommands for the RH CLI."""

from __future__ import annotations

import dataclasses
import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

import click


def register_list_show(
    paper: click.Group,
    *,
    get_db: Callable[[click.Context], Any],
    invoke_service_or_exit: Callable[
        [click.Context, str, dict[str, object] | None], object
    ],
    paper_list_payload_for_cli: Callable[
        [click.Context, object, str | None, str | None], list[dict[str, object]]
    ],
) -> None:
    """Register paper list/show commands on the existing paper group."""

    @paper.command("list")
    @click.option("--topic", "topic_name", default=None)
    @click.option("--status", default=None)
    @click.pass_context
    def paper_list(
        ctx: click.Context, topic_name: str | None, status: str | None
    ) -> None:
        service_args: dict[str, object] = {}
        if topic_name:
            service_args["topic"] = topic_name
        service_output = invoke_service_or_exit(ctx, "paper_list", service_args)
        papers = paper_list_payload_for_cli(ctx, service_output, topic_name, status)
        if ctx.obj.get("json"):
            click.echo(json.dumps(papers, ensure_ascii=False, default=str))
            return
        for paper_obj in papers:
            click.echo(
                f"[{paper_obj['id']}] ({paper_obj.get('year') or '?'}) "
                f"[{paper_obj.get('status')}] {str(paper_obj.get('title', ''))[:70]}"
            )

    @paper.command("show")
    @click.argument("paper_id", type=int)
    @click.pass_context
    def paper_show(ctx: click.Context, paper_id: int) -> None:
        from .core.paper_pool import PaperPool

        db = get_db(ctx)
        conn = db.connect()
        try:
            pool = PaperPool(conn)
            paper_obj = pool.get(paper_id)
            if paper_obj is None:
                raise click.ClickException(f"paper {paper_id} not found")
            annotations = pool.get_annotations(paper_id)
            notes = conn.execute(
                """
                SELECT * FROM topic_paper_notes
                WHERE paper_id = ?
                ORDER BY created_at DESC
                """,
                (paper_id,),
            ).fetchall()
            artifacts = conn.execute(
                """
                SELECT artifact_type, path, metadata, created_at
                FROM paper_artifacts
                WHERE paper_id = ?
                ORDER BY created_at DESC, id DESC
                """,
                (paper_id,),
            ).fetchall()
        finally:
            conn.close()

        result = {
            "paper": dataclasses.asdict(paper_obj),
            "annotations": [dataclasses.asdict(item) for item in annotations],
            "topic_notes": [dict(row) for row in notes],
            "artifacts": [dict(row) for row in artifacts],
        }
        if ctx.obj.get("json"):
            click.echo(json.dumps(result, ensure_ascii=False, default=str))
            return
        click.echo(f"# {paper_obj.title}")
        click.echo(f"Authors: {', '.join(paper_obj.authors)}")
        click.echo(f"Year: {paper_obj.year}  Venue: {paper_obj.venue}")
        click.echo(f"Status: {paper_obj.status}")
        click.echo(f"Annotations: {len(annotations)}")
        click.echo(f"Artifacts: {len(artifacts)}")
        for item in annotations:
            preview = item.content[:120].replace("\n", " ")
            click.echo(f"- {item.section}: {preview}")


def register_artifacts_card(
    paper: click.Group,
    *,
    get_db: Callable[[click.Context], Any],
    paper_artifact_or_exit: Callable[[Any, int, str], Any],
    decode_artifact_metadata: Callable[[object], object],
    load_json_artifact_or_exit: Callable[[str | Path, str], object],
) -> None:
    """Register paper artifact/card commands on the existing paper group."""

    @paper.command("artifacts")
    @click.argument("paper_id", type=int)
    @click.pass_context
    def paper_artifacts(ctx: click.Context, paper_id: int) -> None:
        db = get_db(ctx)
        conn = db.connect()
        try:
            row = conn.execute(
                "SELECT id FROM papers WHERE id = ?", (paper_id,)
            ).fetchone()
            if row is None:
                raise click.ClickException(f"paper {paper_id} not found")
            artifacts = conn.execute(
                """
                SELECT artifact_type, path, metadata, created_at
                FROM paper_artifacts
                WHERE paper_id = ?
                ORDER BY created_at DESC, id DESC
                """,
                (paper_id,),
            ).fetchall()
        finally:
            conn.close()
        payload = [dict(item) for item in artifacts]
        if ctx.obj.get("json"):
            click.echo(json.dumps(payload, ensure_ascii=False, default=str))
            return
        for item in artifacts:
            click.echo(f"[{item['artifact_type']}] {item['path']}")

    @paper.command("card")
    @click.argument("paper_id", type=int)
    @click.option(
        "--output",
        "-o",
        type=click.Path(),
        default=None,
        help="Export the card JSON to a file",
    )
    @click.pass_context
    def paper_card(ctx: click.Context, paper_id: int, output: str | None) -> None:
        db = get_db(ctx)
        conn = db.connect()
        try:
            row = conn.execute(
                "SELECT id FROM papers WHERE id = ?", (paper_id,)
            ).fetchone()
            if row is None:
                raise click.ClickException(f"paper {paper_id} not found")
            artifact = paper_artifact_or_exit(conn, paper_id, "paperindex_card")
            metadata = decode_artifact_metadata(artifact["metadata"])
            card = load_json_artifact_or_exit(artifact["path"], "paper card")
        finally:
            conn.close()

        output_path: Path | None = None
        if output:
            output_path = Path(output)
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_text(
                json.dumps(card, ensure_ascii=False, indent=2), encoding="utf-8"
            )

        payload = {
            "paper_id": paper_id,
            "artifact_type": artifact["artifact_type"],
            "path": artifact["path"],
            "created_at": artifact["created_at"],
            "metadata": metadata,
            "card": card,
        }
        if output_path is not None:
            payload["exported_to"] = str(output_path)

        if ctx.obj.get("json"):
            click.echo(json.dumps(payload, ensure_ascii=False, default=str))
            return
        if output_path is not None:
            click.echo(f"Exported paper card for paper {paper_id} to {output_path}")
            return
        click.echo(json.dumps(card, ensure_ascii=False, indent=2))

    @paper.command("measure")
    @click.argument("bundle_dir", type=click.Path())
    @click.pass_context
    def paper_measure(ctx: click.Context, bundle_dir: str) -> None:
        """Measure a produced manuscript bundle (read-only, no LLM).

        Reports length, sections, citations, and — deliberately as two separate
        numbers — figure ASSETS versus figures the prose actually references.
        Collapsing those two is what let a manuscript with six figures and zero
        cross-references read as "six figures referenced".
        """
        from research_harness.reports.manuscript_measure import (
            measure_manuscript_bundle,
        )

        try:
            report = measure_manuscript_bundle(bundle_dir)
        except FileNotFoundError as exc:
            raise click.ClickException(str(exc)) from exc

        if ctx.obj.get("json"):
            click.echo(json.dumps(report, ensure_ascii=False, default=str))
            return

        m = report["measurements"]
        click.echo(f"Manuscript: {report['tex_file']}")
        click.echo(f"  words (prose)        {m['total_words']}")
        click.echo(f"  sections             {m['section_count']}  {m['sections']}")
        click.echo(
            f"  citations            {m['unique_citation_keys']} unique "
            f"/ {m['citation_instance_count']} instances"
        )
        click.echo(f"  bib entries          {report['bib_entry_count']}")
        click.echo(f"  figure assets        {m['figure_asset_count']}")
        click.echo(
            f"  figures referenced   {m['figure_narrative_reference_count']} "
            f"of {m['figure_label_count']} labelled"
        )
        if m["unreferenced_figure_labels"]:
            click.echo(
                f"    unreferenced:      {', '.join(m['unreferenced_figure_labels'])}"
            )
        click.echo(f"  tables               {m['table_count']}")
        if report["cited_keys_missing_from_bib"]:
            click.echo(
                f"  cited but not in bib {report['cited_keys_missing_from_bib']}"
            )
