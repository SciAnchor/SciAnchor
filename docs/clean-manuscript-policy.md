# Clean-Manuscript Policy (deliverable hygiene, long-term rule)

Set by the user on 2026-08-17 after a deliverable was found to contain a
"复现流程图" section that mentioned `reproduce.sh`, `REDRAW_FIGURES=1`, and
the sentence "该流程既不会导入 Research Harness，也不要求使用 Research
Harness". **Stating that RH is not used is itself a leak.**

## Rules (apply to every outward deliverable: PDF, tex, submission zip,
## advisor/client material, annotator check packages)

1. No internal-toolchain vocabulary anywhere: Research Harness / RH /
   rh-workspace / topic N / internal workflow or draft tags /
   codex / claude / image-provider or generation-layer terms. Not in prose,
   not in comments, not in file names, not in figure assets, not in
   PDF-extractable text, not as a disclaimer.
2. No "reproduction walkthrough" chapters. Reproduction material takes the
   standard academic form only: README + the scripts themselves
   (reproduce.py / make_figures.py / verify_facts.py), describing
   data → results, never the generating toolchain.
3. Enforcement is mechanical, not by memory: every bundle assembly must run
   a FORBIDDEN scan over (a) file contents, (b) file names, (c) pdftotext
   output of every compiled PDF. The FORBIDDEN list in
   eus-3d-clay's assemble_submission.py is the reference baseline —
   extend it whenever a new leaking term is discovered, with a dated
   comment (its "generation_report" addendum is the model).
4. Internal process artifacts (replay bundles, layout drafts, evidence
   maps) MAY contain these terms — the red line is the boundary of the
   deliverable package. Nothing from 06-writing internal scratch dirs
   ships without passing the scan.

## Audit log

- 2026-08-17: last 5 papers checked (sepsis-bspc, eus-3d-clay,
  eus-teacher-ict, scf-xai-credit-risk, leukemia-crosscohort). All
  delivered PDFs and tex: clean (0 hits). Only hit = the FORBIDDEN list
  definition inside assemble_submission.py itself (tooling, not shipped).
  The offending screenshot traced to an older auto-academic
  science-discovery-aaai replay-bundle internal document.


## PDF reader compatibility (added 2026-08-17)

tectonic/xdvipdfmx emits PDF 1.5 **object streams**. Preview and poppler
parse them without complaint, but WPS — and some journal submission portals —
fail to resolve the page tree and display the document as a 1%-zoom sliver.
The file is not corrupt; only its storage format is unfriendly.

**Rule: every deliverable PDF is normalized after compile.**

    python scripts/normalize-deliverable-pdf.py deliverables/*/main.pdf

`--check` reports without writing and exits 1 if any bundle still carries
object streams, so it can gate a packaging step. Normalization rewrites the
xref without object streams and re-opens the result as a sanity gate; page
content is untouched.
