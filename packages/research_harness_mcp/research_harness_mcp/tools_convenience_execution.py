"""MCP convenience tool execution helpers."""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import asdict
from typing import Any

from research_harness.acquisition.spc_bridge import SPCAcquisitionError
from research_harness.provenance.recorder import ProvenanceRecorder


def _execute_convenience(
    name: str,
    arguments: dict[str, Any],
    *,
    db_resolver: Callable[[], Any],
    zotero_sync_executor: Callable[[Any, dict[str, Any]], dict[str, Any]],
) -> dict[str, Any]:
    """Execute a convenience query tool."""
    db = db_resolver()
    conn = db.connect()
    try:
        if name == "topic_list":
            rows = conn.execute(
                "SELECT id, name, description, status FROM topics ORDER BY id"
            ).fetchall()
            return {"topics": [dict(r) for r in rows]}

        elif name == "topic_show":
            row = conn.execute(
                "SELECT * FROM topics WHERE name = ?",
                (arguments["name"],),
            ).fetchone()
            if row is None:
                return {"error": f"Topic not found: {arguments['name']}"}
            result = dict(row)
            # Compute freshness info
            last_search = result.get("last_search_at") or ""
            if last_search:
                from datetime import datetime, timezone

                try:
                    last_dt = datetime.fromisoformat(last_search.replace("Z", "+00:00"))
                    now = datetime.now(timezone.utc)
                    delta = (now - last_dt).days
                    result["days_since_last_search"] = delta
                    warn = result.get("freshness_warn_days", 7)
                    stale = result.get("freshness_stale_days", 30)
                    if delta >= stale:
                        result["freshness_status"] = "stale"
                    elif delta >= warn:
                        result["freshness_status"] = "warn"
                    else:
                        result["freshness_status"] = "fresh"
                except (ValueError, TypeError):
                    result["days_since_last_search"] = None
                    result["freshness_status"] = "unknown"
            else:
                result["days_since_last_search"] = None
                result["freshness_status"] = "never_searched"
            return result

        elif name == "paper_list":
            topic = arguments.get("topic")
            if topic:
                rows = conn.execute(
                    """SELECT p.id, p.title, p.year, p.venue, p.url, p.affiliations, pt.relevance
                       FROM papers p
                       JOIN paper_topics pt ON p.id = pt.paper_id
                       JOIN topics t ON t.id = pt.topic_id
                       WHERE t.name = ?
                       ORDER BY p.id""",
                    (topic,),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT id, title, year, venue, url, affiliations FROM papers ORDER BY id"
                ).fetchall()
            papers = []
            for r in rows:
                d = dict(r)
                if "affiliations" in d and isinstance(d["affiliations"], str):
                    try:
                        d["affiliations"] = json.loads(d["affiliations"])
                    except (json.JSONDecodeError, TypeError):
                        d["affiliations"] = []
                papers.append(d)
            return {"papers": papers}

        elif name == "task_list":
            clauses = ["1=1"]
            params: list[Any] = []
            if arguments.get("topic"):
                clauses.append("t.name = ?")
                params.append(arguments["topic"])
            if arguments.get("status"):
                clauses.append("tk.status = ?")
                params.append(arguments["status"])
            where = " AND ".join(clauses)
            rows = conn.execute(
                f"""SELECT tk.id, tk.title, tk.status, tk.priority, t.name as topic
                    FROM tasks tk
                    JOIN topics t ON t.id = tk.topic_id
                    WHERE {where}
                    ORDER BY tk.priority DESC, tk.id""",
                params,
            ).fetchall()
            return {"tasks": [dict(r) for r in rows]}

        elif name == "provenance_summary":
            recorder = ProvenanceRecorder(db)
            topic_id = arguments.get("topic_id")
            summary = recorder.summarize(topic_id=topic_id)
            return asdict(summary)

        elif name == "provenance_export":
            recorder = ProvenanceRecorder(db)
            topic_id = arguments.get("topic_id")
            fmt = arguments.get("format", "json")
            if fmt != "json":
                return {"error": f"Unsupported format: {fmt}"}
            records = recorder.list_records(topic_id=topic_id, limit=10000)
            return {"format": fmt, "records": [asdict(record) for record in records]}

        elif name == "provenance_token_report":
            recorder = ProvenanceRecorder(db)
            topic_id = arguments.get("topic_id")
            rows = recorder.token_report_by_agent(topic_id=topic_id)
            totals = {
                "calls": sum(r["calls"] for r in rows),
                "prompt_tokens": sum(r["prompt_tokens"] for r in rows),
                "completion_tokens": sum(r["completion_tokens"] for r in rows),
                "total_tokens": sum(r["total_tokens"] for r in rows),
                "cost_usd": sum(r["cost_usd"] for r in rows),
            }
            return {"topic_id": topic_id, "agents": rows, "totals": totals}

        elif name == "zotero_sync":
            return zotero_sync_executor(db, arguments)

        elif name == "paper_dismiss":
            paper_id = int(arguments["paper_id"])
            topic_id = int(arguments["topic_id"])
            reason = str(arguments.get("reason", "")).strip()

            # Verify paper exists
            paper = conn.execute(
                "SELECT id, title FROM papers WHERE id = ?", (paper_id,)
            ).fetchone()
            if paper is None:
                return {"error": f"Paper not found: {paper_id}"}

            # Downgrade relevance to 'low' in paper_topics
            conn.execute(
                "UPDATE paper_topics SET relevance = 'low' WHERE paper_id = ? AND topic_id = ?",
                (paper_id, topic_id),
            )

            # Upsert dismissal note — replace if a previous dismissal exists
            existing = conn.execute(
                "SELECT id FROM topic_paper_notes WHERE paper_id = ? AND topic_id = ? AND note_type = 'user_dismissed'",
                (paper_id, topic_id),
            ).fetchone()
            if existing:
                conn.execute(
                    "UPDATE topic_paper_notes SET content = ?, source = 'user', created_at = datetime('now') WHERE id = ?",
                    (reason, existing["id"]),
                )
            else:
                conn.execute(
                    "INSERT INTO topic_paper_notes (paper_id, topic_id, note_type, content, source) VALUES (?, ?, 'user_dismissed', ?, 'user')",
                    (paper_id, topic_id, reason),
                )
            conn.commit()

            return {
                "dismissed": True,
                "paper_id": paper_id,
                "title": paper["title"],
                "reason_recorded": reason,
            }

        elif name == "decision_log_record":
            from research_harness.orchestrator.service import OrchestratorService

            svc = OrchestratorService(db)
            return svc.record_decision(
                topic_id=int(arguments["topic_id"]),
                stage=arguments["stage"],
                checkpoint=arguments["checkpoint"],
                choice=arguments["choice"],
                reasoning=arguments.get("reasoning", ""),
                params=arguments.get("params"),
            )

        elif name == "decision_log_list":
            from research_harness.orchestrator.service import OrchestratorService

            svc = OrchestratorService(db)
            return {
                "decisions": svc.list_decisions(
                    topic_id=int(arguments["topic_id"]),
                    stage=arguments.get("stage"),
                ),
            }

        elif name == "search_query_list":
            topic_id = int(arguments["topic_id"])
            rows = conn.execute(
                "SELECT * FROM search_query_registry WHERE topic_id = ? ORDER BY created_at",
                (topic_id,),
            ).fetchall()
            queries = []
            for r in rows:
                q = dict(r)
                last = q.get("last_searched_at") or ""
                if last:
                    from datetime import datetime, timezone

                    try:
                        dt = datetime.fromisoformat(last.replace("Z", "+00:00"))
                        q["days_since_search"] = (datetime.now(timezone.utc) - dt).days
                    except (ValueError, TypeError):
                        q["days_since_search"] = None
                else:
                    q["days_since_search"] = None
                    q["freshness_status"] = "never_searched"
                queries.append(q)
            return {"queries": queries}

        elif name == "search_query_add":
            topic_id = int(arguments["topic_id"])
            query_text = arguments["query"]
            source = arguments.get("source", "user")
            conn.execute(
                """INSERT INTO search_query_registry (topic_id, query, source)
                   VALUES (?, ?, ?)
                   ON CONFLICT(topic_id, query) DO UPDATE SET source = ?""",
                (topic_id, query_text, source, source),
            )
            conn.commit()
            return {
                "success": True,
                "topic_id": topic_id,
                "query": query_text,
                "source": source,
            }

        elif name == "advisory_check":
            from research_harness.advisory import AdvisoryEngine

            engine = AdvisoryEngine(db)
            advisories = engine.run(
                topic_id=int(arguments["topic_id"]),
            )
            return {
                "advisories": [asdict(item) for item in advisories],
                "count": len(advisories),
            }

        elif name == "advisory_list":
            from research_harness.advisory import AdvisoryEngine

            engine = AdvisoryEngine(db)
            advisories = engine.list(
                topic_id=int(arguments["topic_id"]),
                level=arguments.get("level"),
            )
            return {
                "advisories": [asdict(item) for item in advisories],
                "count": len(advisories),
            }

        elif name == "advisory_acknowledge":
            from research_harness.advisory import AdvisoryEngine

            engine = AdvisoryEngine(db)
            advisory = engine.acknowledge(int(arguments["advisory_id"]))
            if advisory is None:
                return {"error": f"Advisory not found: {arguments['advisory_id']}"}
            return {"advisory": asdict(advisory)}

        elif name == "paper_purge":
            paper_id = int(arguments["paper_id"])
            paper = conn.execute(
                "SELECT id, title FROM papers WHERE id = ?", (paper_id,)
            ).fetchone()
            if paper is None:
                return {"error": f"Paper not found: {paper_id}"}
            title = paper["title"] or f"Paper #{paper_id}"
            # Delete in dependency order (CASCADE should handle most, but be explicit)
            for table in (
                "topic_paper_notes",
                "paper_annotations",
                "paper_artifacts",
                "bib_entries",
                "paper_topics",
            ):
                conn.execute(f"DELETE FROM {table} WHERE paper_id = ?", (paper_id,))
            conn.execute("DELETE FROM papers WHERE id = ?", (paper_id,))
            conn.commit()
            return {"purged": True, "paper_id": paper_id, "title": title}

        elif name == "venue_refresh":
            import time as _time

            topic_id = int(arguments["topic_id"])
            # Find papers with stale venues
            stale_venues = ("", "arxiv", "arxiv.org", "arxiv preprint")
            rows = conn.execute(
                """SELECT p.id, p.arxiv_id, p.doi, p.s2_id, p.venue
                   FROM papers p
                   JOIN paper_topics pt ON p.id = pt.paper_id
                   WHERE pt.topic_id = ?
                     AND (p.venue IS NULL OR LOWER(TRIM(p.venue)) IN (?, ?, ?, ?))
                   ORDER BY p.id""",
                (topic_id, *stale_venues),
            ).fetchall()

            updated = []
            skipped = 0
            for row in rows:
                # Build S2 lookup ID
                lookup_id = None
                if row["arxiv_id"]:
                    clean = (
                        (row["arxiv_id"] or "")
                        .strip()
                        .removeprefix("arxiv:")
                        .removeprefix("arXiv:")
                    )
                    lookup_id = f"ARXIV:{clean}"
                elif row["doi"]:
                    clean = (
                        (row["doi"] or "")
                        .strip()
                        .removeprefix("doi:")
                        .removeprefix("DOI:")
                    )
                    lookup_id = f"DOI:{clean}"
                elif row["s2_id"]:
                    lookup_id = (row["s2_id"] or "").strip()
                if not lookup_id:
                    skipped += 1
                    continue

                try:
                    from research_harness.paper_source_clients import (
                        build_provider_suite,
                    )
                    from research_harness.paper_sources import (
                        SearchAggregator,
                        SearchQuery,
                        normalize_arxiv_id,
                    )

                    outcome = SearchAggregator(build_provider_suite()).search(
                        SearchQuery(query=lookup_id, limit=5)
                    )
                    matching = [
                        r
                        for r in outcome.results
                        if (row["doi"] and r.doi.casefold() == row["doi"].casefold())
                        or (
                            row["arxiv_id"]
                            and normalize_arxiv_id(r.arxiv_id)
                            == normalize_arxiv_id(row["arxiv_id"])
                        )
                    ]
                    new_venue = matching[0].venue.strip() if matching else ""
                    if new_venue and new_venue.lower() not in stale_venues:
                        conn.execute(
                            "UPDATE papers SET venue = ? WHERE id = ?",
                            (new_venue, row["id"]),
                        )
                        updated.append({"paper_id": row["id"], "new_venue": new_venue})
                except SPCAcquisitionError:
                    raise
                except Exception:
                    pass  # Skip non-acquisition errors
                _time.sleep(1.05)  # S2 rate limit

            conn.commit()
            return {
                "topic_id": topic_id,
                "stale_count": len(rows),
                "updated_count": len(updated),
                "skipped_no_id": skipped,
                "updated": updated,
            }

        elif name == "domain_list":
            rows = conn.execute(
                """SELECT d.id, d.name, d.description, d.status, d.created_at,
                          COUNT(t.id) AS topic_count
                   FROM domains d
                   LEFT JOIN topics t ON t.domain_id = d.id
                   GROUP BY d.id
                   ORDER BY d.id"""
            ).fetchall()
            return {"domains": [dict(r) for r in rows]}

        elif name == "domain_init":
            domain_name = arguments["name"]
            description = arguments.get("description", "")
            try:
                cur = conn.execute(
                    "INSERT INTO domains (name, description) VALUES (?, ?)",
                    (domain_name, description),
                )
                conn.commit()
                return {
                    "success": True,
                    "domain_id": cur.lastrowid,
                    "name": domain_name,
                }
            except Exception as exc:
                return {"error": f"Failed to create domain: {exc}"}

        elif name == "domain_show":
            domain_name = arguments["name"]
            row = conn.execute(
                "SELECT * FROM domains WHERE name = ?",
                (domain_name,),
            ).fetchone()
            if row is None:
                return {"error": f"Domain not found: {domain_name}"}
            result = dict(row)
            topics = conn.execute(
                """SELECT id, name, description, status
                   FROM topics WHERE domain_id = ?
                   ORDER BY id""",
                (row["id"],),
            ).fetchall()
            result["topics"] = [dict(t) for t in topics]
            return result

        elif name == "deposit_zenodo":
            from research_harness.deposit.zenodo import (
                deposit_code_and_data,
                lookup_topic,
            )

            topic_id = arguments.get("topic_id")
            topic_name = arguments.get("topic_name")
            if topic_id is not None or topic_name:
                try:
                    tid, tname = lookup_topic(
                        db.path,
                        topic_id=int(topic_id) if topic_id is not None else None,
                        topic_name=topic_name,
                    )
                except Exception as exc:
                    return {"error": f"topic lookup failed: {exc}"}
                if tid is None and topic_id is not None:
                    return {"error": f"Topic not found: id={topic_id}"}
                if tid is None and topic_name:
                    return {"error": f"Topic not found: name={topic_name}"}
                topic_id, topic_name = tid, tname

            publish = arguments.get("publish", True)
            if isinstance(publish, str):
                publish = publish.lower() not in {"0", "false", "no"}

            result = deposit_code_and_data(
                topic_id=topic_id,
                topic_name=topic_name or arguments.get("title"),
                title=arguments.get("title") or topic_name,
                creator=arguments.get("creator"),
                email=arguments.get("email"),
                password=arguments.get("password"),
                token=arguments.get("token"),
                code_path=arguments.get("code_path"),
                data_path=arguments.get("data_path"),
                deposit_root=arguments.get("deposit_root"),
                sandbox=bool(arguments.get("sandbox", False)),
                publish=bool(publish),
            )
            payload = result.to_dict()
            # never return secrets
            for key in ("password", "token", "email"):
                payload.pop(key, None)
            if result.status == "error":
                return {"error": result.error or "deposit failed", "result": payload}
            return {
                "code_doi": result.code_doi,
                "data_doi": result.data_doi,
                "code_url": result.code_url,
                "data_url": result.data_url,
                "published": result.published,
                "sandbox": result.sandbox,
                "topic_id": result.topic_id,
                "topic_name": result.topic_name,
                "code_path": result.code_path,
                "data_path": result.data_path,
                "status": result.status,
            }

        return {"error": f"Unknown convenience tool: {name}"}
    finally:
        conn.close()
