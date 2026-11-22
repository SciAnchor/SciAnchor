"""Paper annotation and note subcommands for the RH CLI."""

from __future__ import annotations

import dataclasses
import json
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any

import click

from .storage.models import TopicPaperNote


def register(
    paper: click.Group,
    *,
    get_db: Callable[[click.Context], Any],
    topic_id_or_exit: Callable[[Any, str], int],
    paper_artifact_or_exit: Callable[[Any, int, str], Any],
    decode_artifact_metadata: Callable[[object], object],
    load_json_artifact_or_exit: Callable[[str | Path, str], object],
    draft_topic_note_from_card: Callable[..., str],
    echo: Callable[[click.Context, object, str | None], None],
    note_types: Sequence[str],
) -> None:
    """Register paper annotation and topic-note commands."""

    @paper.command("annotate")
    @click.argument("paper_id", type=int)
    @click.option(
        "--pdf", "pdf_path", default=None, help="Override PDF path for this run"
    )
    @click.option("--section", "sections", multiple=True, help="Section(s) to extract")
    @click.pass_context
    def paper_annotate(
        ctx: click.Context,
        paper_id: int,
        pdf_path: str | None,
        sections: tuple[str, ...],
    ) -> None:
        from .core.paper_pool import PaperPool
        from .integrations.paperindex_adapter import PaperIndexAdapter

        db = get_db(ctx)
        conn = db.connect()
        try:
            pool = PaperPool(conn)
            paper_obj = pool.get(paper_id)
            if paper_obj is None:
                raise click.ClickException(f"paper {paper_id} not found")
            resolved_pdf = pdf_path or paper_obj.pdf_path
            if not resolved_pdf:
                raise click.ClickException(
                    "paper has no pdf_path; provide --pdf or ingest with --pdf-path"
                )
            adapter = PaperIndexAdapter(
                conn, artifacts_root=db.db_path.parent / "artifacts"
            )
            result = adapter.annotate_paper(
                paper_id, resolved_pdf, list(sections) or None
            )
        finally:
            conn.close()
        echo(
            ctx,
            result,
            f"Paper {paper_id} annotated with {result['annotation_count']} sections",
        )

    @paper.command("annotations")
    @click.argument("paper_id", type=int)
    @click.option("--section", "section_name", default=None)
    @click.pass_context
    def paper_annotations(
        ctx: click.Context, paper_id: int, section_name: str | None
    ) -> None:
        from .core.paper_pool import PaperPool

        db = get_db(ctx)
        conn = db.connect()
        try:
            pool = PaperPool(conn)
            paper_obj = pool.get(paper_id)
            if paper_obj is None:
                raise click.ClickException(f"paper {paper_id} not found")
            annotations = pool.get_annotations(paper_id)
        finally:
            conn.close()
        if section_name:
            annotations = [item for item in annotations if item.section == section_name]
        payload = [dataclasses.asdict(item) for item in annotations]
        if ctx.obj.get("json"):
            click.echo(json.dumps(payload, ensure_ascii=False, default=str))
            return
        for item in annotations:
            click.echo(f"## {item.section} [{item.source}] ({item.confidence})")
            click.echo(item.content)
            click.echo("")

    @paper.group("note")
    def paper_note() -> None:
        """Manage topic-specific paper notes."""

    @paper_note.command("set")
    @click.option("--paper-id", type=int, required=True)
    @click.option("--topic", "topic_name", required=True)
    @click.option("--type", "note_type", required=True, type=click.Choice(note_types))
    @click.option("--content", required=True)
    @click.option("--source", default="")
    @click.option("--dry-run", is_flag=True, default=False)
    @click.pass_context
    def paper_note_set(
        ctx: click.Context,
        paper_id: int,
        topic_name: str,
        note_type: str,
        content: str,
        source: str,
        dry_run: bool,
    ) -> None:
        payload = {
            "paper_id": paper_id,
            "topic": topic_name,
            "note_type": note_type,
            "content": content,
            "source": source,
        }
        if dry_run:
            echo(
                ctx,
                {"action": "paper.note.set", **payload},
                f"Dry run: note for paper {paper_id} under topic '{topic_name}'",
            )
            return

        from .core.paper_pool import PaperPool

        db = get_db(ctx)
        conn = db.connect()
        try:
            topic_id = topic_id_or_exit(conn, topic_name)
            pool = PaperPool(conn)
            paper_obj = pool.get(paper_id)
            if paper_obj is None:
                raise click.ClickException(f"paper {paper_id} not found")
            try:
                note_id = pool.upsert_topic_note(
                    TopicPaperNote(
                        paper_id=paper_id,
                        topic_id=topic_id,
                        note_type=note_type,
                        content=content,
                        source=source,
                    )
                )
            except ValueError as exc:
                raise click.ClickException(str(exc)) from exc
        finally:
            conn.close()
        echo(
            ctx,
            {"id": note_id, "topic_id": topic_id, **payload},
            f"Topic note saved: id={note_id}",
        )

    @paper_note.command("draft")
    @click.option("--paper-id", type=int, required=True)
    @click.option("--topic", "topic_name", required=True)
    @click.option("--type", "note_type", required=True, type=click.Choice(note_types))
    @click.option(
        "--save",
        is_flag=True,
        default=False,
        help="Save the drafted note into topic_paper_notes",
    )
    @click.option("--source", default="paperindex:card-draft")
    @click.pass_context
    def paper_note_draft(
        ctx: click.Context,
        paper_id: int,
        topic_name: str,
        note_type: str,
        save: bool,
        source: str,
    ) -> None:
        from .core.paper_pool import PaperPool

        db = get_db(ctx)
        conn = db.connect()
        try:
            topic_id = topic_id_or_exit(conn, topic_name)
            pool = PaperPool(conn)
            paper_obj = pool.get(paper_id)
            if paper_obj is None:
                raise click.ClickException(f"paper {paper_id} not found")
            topic_row = conn.execute(
                """
                SELECT relevance FROM paper_topics
                WHERE paper_id = ? AND topic_id = ?
                """,
                (paper_id, topic_id),
            ).fetchone()
            if topic_row is None:
                raise click.ClickException(
                    f"paper {paper_id} is not linked to topic {topic_id}"
                )
            artifact = paper_artifact_or_exit(conn, paper_id, "paperindex_card")
            metadata = decode_artifact_metadata(artifact["metadata"])
            card_obj = load_json_artifact_or_exit(artifact["path"], "paper card")
            if not isinstance(card_obj, dict):
                raise click.ClickException(
                    f"paper card artifact at {artifact['path']} must be a JSON object"
                )
            content = draft_topic_note_from_card(
                paper_obj=paper_obj,
                topic_name=topic_name,
                note_type=note_type,
                card=card_obj,
                topic_relevance=topic_row["relevance"] or "",
            )
            payload = {
                "paper_id": paper_id,
                "topic": topic_name,
                "note_type": note_type,
                "source": source,
                "saved": save,
                "content": content,
                "card_path": artifact["path"],
                "card_metadata": metadata,
            }
            if save:
                note_id = pool.upsert_topic_note(
                    TopicPaperNote(
                        paper_id=paper_id,
                        topic_id=topic_id,
                        note_type=note_type,
                        content=content,
                        source=source,
                    )
                )
                payload["id"] = note_id
                payload["topic_id"] = topic_id
        finally:
            conn.close()

        if ctx.obj.get("json"):
            click.echo(json.dumps(payload, ensure_ascii=False, default=str))
            return
        if save:
            click.echo(f"Topic note drafted and saved: id={payload['id']}")
            click.echo("")
        click.echo(content)

    @paper_note.command("list")
    @click.option("--paper-id", type=int, required=True)
    @click.option("--topic", "topic_name", default=None)
    @click.option("--type", "note_type", default=None, type=click.Choice(note_types))
    @click.pass_context
    def paper_note_list(
        ctx: click.Context,
        paper_id: int,
        topic_name: str | None,
        note_type: str | None,
    ) -> None:
        from .core.paper_pool import PaperPool

        db = get_db(ctx)
        conn = db.connect()
        try:
            pool = PaperPool(conn)
            paper_obj = pool.get(paper_id)
            if paper_obj is None:
                raise click.ClickException(f"paper {paper_id} not found")
            topic_id = topic_id_or_exit(conn, topic_name) if topic_name else None
            notes = pool.get_topic_notes(
                paper_id, topic_id=topic_id, note_type=note_type
            )
        finally:
            conn.close()
        payload = [dataclasses.asdict(item) for item in notes]
        if ctx.obj.get("json"):
            click.echo(json.dumps(payload, ensure_ascii=False, default=str))
            return
        for item in notes:
            click.echo(f"[{item.note_type}] topic={item.topic_id} source={item.source}")
            click.echo(item.content)
            click.echo("")
