#!/usr/bin/env python3
"""Backfill:  canonicalize papers.arxiv_id and merge the duplicate rows
that non-canonical ids created.

Usage:
    python scripts/backfill_canonical_arxiv_ids.py            # dry run
    python scripts/backfill_canonical_arxiv_ids.py --apply    # write

Back up the pool first — this merges and deletes paper rows.
Safe to re-run: a canonical pool reports 0 merges and 0 renames.

Background: `_find_existing` matched arxiv_id exactly, so "2608.14036",
"2608.14036v1" and "arxiv:2608.14036" each became their own paper row. The code
fix canonicalizes on write and on lookup; this cleans up what the old behavior
already stored.
"""

from __future__ import annotations

import argparse
import collections
import os
import sqlite3
import sys

sys.path.insert(
    0, os.path.join(os.path.dirname(__file__), "..", "packages", "research_harness")
)
from research_harness.paper_sources import normalize_arxiv_id  # noqa: E402

# Every table carrying a paper_id, so a merged-away row leaves nothing behind.
PAPER_ID_TABLES = [
    "paper_topics",
    "paper_annotations",
    "topic_paper_notes",
    "bib_entries",
    "tasks",
    "paper_artifacts",
    "pipeline_events",
    "taxonomy_assignments",
    "normalized_claims",
    "extracted_tables",
    "extracted_figures",
    "aggregated_metrics",
    "writing_observations",
    "experience_records",
    "claim_citations",
    "paper_research_areas",
    "paper_domains",
    "zotero_item_links",
    "zotero_import_links",
    "semantic_atoms",
]

# Fields worth rescuing from a row that is about to be deleted.
MERGE_FIELDS = [
    "title",
    "authors",
    "affiliations",
    "year",
    "venue",
    "abstract",
    "doi",
    "s2_id",
    "pmid",
    "pmcid",
    "url",
    "pdf_path",
    "pdf_hash",
]

# Subset of MERGE_FIELDS protected by a UNIQUE index on papers.
IDENTITY_UNIQUE = {"doi", "s2_id", "pmid", "pmcid"}


def _richness(row: sqlite3.Row) -> tuple[int, int]:
    """Prefer the row with a PDF, then the one with more populated fields."""
    has_pdf = 1 if (row["pdf_path"] or "").strip() else 0
    filled = sum(1 for f in MERGE_FIELDS if (str(row[f] or "").strip()))
    return (has_pdf, filled)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default=".research-harness/pool.db")
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()

    con = sqlite3.connect(args.db)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys=OFF")

    rows = con.execute(
        "SELECT * FROM papers WHERE arxiv_id IS NOT NULL AND TRIM(arxiv_id) <> ''"
    ).fetchall()
    # A row whose arxiv_id holds a whitespace-separated LIST of ids is corrupt
    # input, not a shape variant. normalize_arxiv_id would return its first id
    # and collide it with a legitimate paper, so quarantine instead of merging.
    corrupt = [r for r in rows if " " in (r["arxiv_id"] or "").strip()]
    rows = [r for r in rows if r not in corrupt]
    if corrupt:
        print(
            f"QUARANTINED (arxiv_id holds an id list, left untouched): {len(corrupt)}"
        )
        for r in corrupt:
            print(
                f"  id={r['id']} title={(r['title'] or '<empty>')[:40]!r} "
                f"arxiv_id[:50]={r['arxiv_id'][:50]!r}"
            )

    groups: dict[str, list[sqlite3.Row]] = collections.defaultdict(list)
    for r in rows:
        groups[normalize_arxiv_id(r["arxiv_id"])].append(r)

    dup_groups = {k: v for k, v in groups.items() if len(v) > 1}
    rename_only = [
        r for k, v in groups.items() if len(v) == 1 for r in v if r["arxiv_id"] != k
    ]

    print(f"rows with arxiv_id       : {len(rows)}")
    print(f"duplicate groups to merge: {len(dup_groups)}")
    print(f"rows needing rename only : {len(rename_only)}")

    merged = renamed = repointed = 0
    for canonical, members in sorted(dup_groups.items()):
        survivor = max(members, key=_richness)
        losers = [m for m in members if m["id"] != survivor["id"]]
        print(
            f"  {canonical}: keep id={survivor['id']} ({survivor['arxiv_id']}), "
            f"merge {[(m['id'], m['arxiv_id']) for m in losers]}"
        )
        if not args.apply:
            merged += len(losers)
            continue
        for loser in losers:
            for table in PAPER_ID_TABLES:
                try:
                    cur = con.execute(
                        f"UPDATE OR IGNORE {table} SET paper_id=? WHERE paper_id=?",
                        (survivor["id"], loser["id"]),
                    )
                    repointed += cur.rowcount if cur.rowcount > 0 else 0
                    # Rows that collided with an existing (survivor, ...) key
                    # were skipped by OR IGNORE; they are redundant copies.
                    con.execute(f"DELETE FROM {table} WHERE paper_id=?", (loser["id"],))
                except sqlite3.OperationalError:
                    pass  # table absent in this schema version
            for f in MERGE_FIELDS:
                if str(survivor[f] or "").strip() or not str(loser[f] or "").strip():
                    continue
                # doi/s2_id/pmid/pmcid carry UNIQUE indexes: a third row may
                # already hold the loser's value, in which case it is not ours
                # to take. OR IGNORE leaves the survivor's field empty rather
                # than aborting the whole merge.
                verb = "UPDATE OR IGNORE" if f in IDENTITY_UNIQUE else "UPDATE"
                con.execute(
                    f"{verb} papers SET {f}=? WHERE id=?", (loser[f], survivor["id"])
                )
            con.execute("DELETE FROM papers WHERE id=?", (loser["id"],))
            merged += 1
        con.execute(
            "UPDATE papers SET arxiv_id=? WHERE id=?", (canonical, survivor["id"])
        )

    for r in rename_only:
        if args.apply:
            con.execute(
                "UPDATE papers SET arxiv_id=? WHERE id=?",
                (normalize_arxiv_id(r["arxiv_id"]), r["id"]),
            )
        renamed += 1

    if args.apply:
        con.commit()
        print(
            f"\nAPPLIED: merged {merged} rows, renamed {renamed}, repointed ~{repointed} refs"
        )
        left = con.execute(
            "SELECT COUNT(*) FROM papers WHERE arxiv_id IS NOT NULL "
            "AND TRIM(arxiv_id) <> '' AND (arxiv_id LIKE '%v_' OR arxiv_id LIKE '%v__' "
            "OR LOWER(arxiv_id) LIKE 'arxiv:%')"
        ).fetchone()[0]
        print(f"non-canonical rows remaining: {left}")
    else:
        print(f"\nDRY RUN: would merge {merged} rows, rename {renamed}")
    con.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
