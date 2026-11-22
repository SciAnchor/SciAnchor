"""Result-figure exemplar evidence and rendered-suite critique.

PDF side (curation evidence for ``exemplar_curate(unit_type="figure_suite")``):

- ``extract_figure_captions`` — deterministic caption harvesting from a pool
  PDF (PyMuPDF text). Captions usually spell out the panel composition
  ("(a) ... (b) ...") and chart archetypes, which is exactly the FORM the
  exemplar curator abstracts.
- ``describe_result_figures`` — optional vision pass: extract candidate figure
  images and let an OpenAI-compatible VLM keep/describe only quantitative
  RESULT plots. The pattern is extract → quality-gate → describe, with the
  gate tuned to keep quantitative result plots and reject schematics.

Render side:

- ``critique_rendered_figures`` — deterministic sanity checks (exists, loads,
  size, not near-blank) plus an optional VLM readability/composition/aesthetics
  review of rendered suite figures. Never raises; degrades to
  deterministic-only when no vision backend is configured.

Everything in this module is defensive: missing PDFs, missing PyMuPDF/PIL,
unset vision credentials, or malformed VLM output produce empty results or
deterministic-only reports, never exceptions.
"""

from __future__ import annotations

import base64
import io
import json
import os
import re
import urllib.request
from pathlib import Path
from typing import Any, Sequence


# Caption openers across publisher families: "Figure 3:" / "Fig. 3." / "Fig 3 |"
# (Nature journals), "Fig. 1 The ..." / "Table 1 Basic ..." (Springer Nature /
# HSSC: number + space + capitalized caption, no punctuation), "图1：".
# Body references ("Figure 3 shows", "Table 2, the ...", "Tables 3 and 4")
# are excluded by the punctuation/capital requirement and singular anchor.
_CAPTION_RE = re.compile(
    r"^\s*(?:"
    r"(?:Figure|Fig\.?|FIGURE|Table|TABLE)\s*\.?\s*\d+\s*[.:|]"
    r"|(?:Figure|Fig\.|Table)\s+\d+\s+[A-Z]"
    r"|[图表]\s*\d+\s*[.:：]"
    r")",
)

_VISION_TIMEOUT = 150


# --------------------------------------------------------------------------- #
# Caption extraction (deterministic, text only)                                #
# --------------------------------------------------------------------------- #


def extract_figure_captions(
    pdf_path: str | Path,
    *,
    max_pages: int = 40,
    max_captions: int = 16,
    max_chars: int = 360,
) -> list[str]:
    """Harvest figure/table caption lines from a PDF. Empty list on any failure."""
    path = Path(str(pdf_path or ""))
    if not path.is_file():
        return []
    try:
        import fitz
    except Exception:
        return []
    captions: list[str] = []
    seen: set[str] = set()
    try:
        doc = fitz.open(path)
    except Exception:
        return []
    try:
        for page_number in range(min(max_pages, doc.page_count)):
            try:
                lines = doc[page_number].get_text("text").splitlines()
            except Exception:
                continue
            i = 0
            while i < len(lines):
                line = lines[i].strip()
                match = _CAPTION_RE.match(line)
                if not match:
                    i += 1
                    continue
                caption = [line]
                j = i + 1
                # captions wrap across lines; stop at a blank line or a new caption
                while (
                    j < len(lines)
                    and lines[j].strip()
                    and not _CAPTION_RE.match(lines[j].strip())
                    and sum(len(part) for part in caption) < max_chars
                ):
                    caption.append(lines[j].strip())
                    j += 1
                text = " ".join(caption)[:max_chars].strip()
                key = text[:60].lower()
                if len(text) >= 20 and key not in seen:
                    seen.add(key)
                    captions.append(text)
                    if len(captions) >= max_captions:
                        return captions
                i = j
    finally:
        doc.close()
    return captions


# --------------------------------------------------------------------------- #
# Vision backend (OpenAI-compatible; mirrors EAG's direct-endpoint fallback)   #
# --------------------------------------------------------------------------- #


def vision_available() -> bool:
    return bool(os.environ.get("OPENAI_BASE_URL")) and bool(
        os.environ.get("OPENAI_API_KEY")
    )


def _vision_enabled(use_vision: bool | None) -> bool:
    if use_vision is None:
        use_vision = str(
            os.environ.get("RH_EAG_FIGURE_VISION", "")
        ).strip().lower() in (
            "1",
            "true",
            "yes",
            "on",
        )
    return bool(use_vision) and vision_available()


def _vision_model(model: str | None) -> str:
    return (
        model
        or os.environ.get("RH_EAG_VISION_MODEL")
        or os.environ.get("MAIN_MODEL_NAME")
        or os.environ.get("RH_EAG_MODEL")
        or "gpt-6-astra"
    )


def _vision_chat(prompt: str, png_bytes: bytes, *, model: str | None = None) -> str:
    base = os.environ.get("OPENAI_BASE_URL", "").rstrip("/")
    key = os.environ.get("OPENAI_API_KEY", "")
    if not base or not key:
        raise RuntimeError(
            "vision backend unavailable: OPENAI_BASE_URL/OPENAI_API_KEY unset"
        )
    b64 = base64.b64encode(png_bytes).decode()
    payload = {
        "model": _vision_model(model),
        "temperature": 0.2,
        "max_tokens": 500,
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {
                        "type": "image_url",
                        "image_url": {"url": f"data:image/png;base64,{b64}"},
                    },
                ],
            }
        ],
    }
    req = urllib.request.Request(
        base + "/chat/completions",
        data=json.dumps(payload).encode(),
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=_VISION_TIMEOUT) as response:
        return json.load(response)["choices"][0]["message"]["content"]


def _loose_json(raw: str) -> dict[str, Any]:
    text = (raw or "").strip()
    if "```" in text:
        text = re.sub(r"^.*?```(?:json)?\s*", "", text, flags=re.S)
        text = re.sub(r"```.*$", "", text, flags=re.S)
    start, end = text.find("{"), text.rfind("}")
    if start >= 0 and end > start:
        text = text[start : end + 1]
    try:
        parsed = json.loads(text)
    except Exception:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _png_bytes_stats(png_bytes: bytes) -> tuple[int, int, float] | None:
    """(width, height, grayscale std) or None if the image cannot be read."""
    try:
        import numpy as np
        from PIL import Image

        image = Image.open(io.BytesIO(png_bytes))
        gray = np.asarray(image.convert("L"))
        return image.size[0], image.size[1], float(gray.std())
    except Exception:
        return None


def _shrink_png(png_bytes: bytes, max_side: int = 1024) -> bytes:
    try:
        from PIL import Image

        image = Image.open(io.BytesIO(png_bytes))
        image.thumbnail((max_side, max_side))
        buffer = io.BytesIO()
        image.convert("RGB").save(buffer, format="PNG")
        return buffer.getvalue()
    except Exception:
        return png_bytes


# --------------------------------------------------------------------------- #
# Candidate figure images from a pool PDF                                      #
# --------------------------------------------------------------------------- #


def extract_result_figure_images(
    pdf_path: str | Path,
    *,
    max_pages: int = 14,
    min_long: int = 420,
    max_candidates: int = 6,
) -> list[bytes]:
    """Candidate figure images: embedded rasters plus renders of caption pages.

    Page renders catch vector charts (most result plots are vector), which
    embedded-image extraction misses; the VLM gate downstream sorts real result
    plots from page noise. Empty list on any failure.
    """
    path = Path(str(pdf_path or ""))
    if not path.is_file():
        return []
    try:
        import fitz
    except Exception:
        return []
    candidates: list[bytes] = []
    try:
        doc = fitz.open(path)
    except Exception:
        return []
    try:
        seen_xrefs: set[int] = set()
        caption_pages: list[int] = []
        for page_number in range(min(max_pages, doc.page_count)):
            page = doc[page_number]
            try:
                text = page.get_text("text")
            except Exception:
                text = ""
            if any(_CAPTION_RE.match(line.strip()) for line in text.splitlines()):
                caption_pages.append(page_number)
            for image_info in page.get_images(full=True):
                xref = image_info[0]
                if xref in seen_xrefs:
                    continue
                seen_xrefs.add(xref)
                try:
                    extracted = doc.extract_image(xref)
                    png = extracted.get("image", b"")
                except Exception:
                    continue
                stats = _png_bytes_stats(png)
                if stats is None:
                    continue
                width, height, std = stats
                if max(width, height) < min_long:
                    continue
                aspect = width / max(height, 1)
                if not (0.2 <= aspect <= 5.0) or std < 12:
                    continue
                candidates.append(_shrink_png(png))
                if len(candidates) >= max_candidates:
                    return candidates
        for page_number in caption_pages:
            if len(candidates) >= max_candidates:
                break
            try:
                pixmap = doc[page_number].get_pixmap(matrix=fitz.Matrix(2, 2))
                candidates.append(_shrink_png(pixmap.tobytes("png")))
            except Exception:
                continue
    finally:
        doc.close()
    return candidates


_DESCRIBE_PROMPT = (
    "You are curating visual exemplars of QUANTITATIVE RESULT figures from a published "
    "paper (bar/line/scatter/box/violin charts, heatmaps, radar, pareto, forest/"
    "coefficient plots — possibly multi-panel). Judge this image.\n"
    'Return ONLY JSON: {"is_quant_result_plot": true|false, "quality": 0-10, '
    '"form": {"charts": ["grouped_bar|heatmap|radar|pareto_scatter|sensitivity_line|'
    'line|scatter|box|violin|bar|forest"], "n_panels": 0, "composition": "RxC", '
    '"panel_labels": "a|(a)|A|none", "style_traits": {"palette": "...", '
    '"annotation_density": "low|medium|high"}}, "summary": "one sentence on the '
    'visual argument, NOT the data values"}.\n'
    "is_quant_result_plot=false for architecture/pipeline schematics, photos, tables, "
    "equations, or full pages without a dominant result chart. quality is visual/design "
    "quality as a form exemplar. Never transcribe numbers."
)


def describe_result_figures(
    pdf_path: str | Path,
    *,
    model: str | None = None,
    max_figures: int = 4,
    min_quality: float = 6.0,
) -> list[dict[str, Any]]:
    """VLM-gated form descriptions of a PDF's result figures. Empty on failure."""
    if not vision_available():
        return []
    descriptions: list[dict[str, Any]] = []
    for png in extract_result_figure_images(pdf_path):
        if len(descriptions) >= max_figures:
            break
        try:
            parsed = _loose_json(_vision_chat(_DESCRIBE_PROMPT, png, model=model))
        except Exception:
            continue
        if not parsed.get("is_quant_result_plot"):
            continue
        try:
            quality = float(parsed.get("quality", 0))
        except (TypeError, ValueError):
            quality = 0.0
        form = parsed.get("form")
        if quality < float(min_quality) or not isinstance(form, dict):
            continue
        descriptions.append(
            {
                "quality": quality,
                "form": form,
                "summary": str(parsed.get("summary", ""))[:300],
            }
        )
    return descriptions


# --------------------------------------------------------------------------- #
# Curation evidence text for EAG                                               #
# --------------------------------------------------------------------------- #


def figure_evidence_text(
    db: Any,
    paper_id: int,
    *,
    use_vision: bool | None = None,
    model: str | None = None,
) -> str:
    """Figure-form evidence for one pool paper: captions (+ optional VLM analyses).

    Returns "" when the paper has no readable PDF so the caller can fall back to
    abstract/notes.
    """
    pdf_path = ""
    try:
        conn = db.connect()
        try:
            row = conn.execute(
                "SELECT pdf_path FROM papers WHERE id = ?", (int(paper_id),)
            ).fetchone()
            pdf_path = (row["pdf_path"] or "") if row else ""
        finally:
            conn.close()
    except Exception:
        return ""
    if not pdf_path:
        return ""
    blocks: list[str] = []
    captions = extract_figure_captions(pdf_path)
    if captions:
        blocks.append(
            "FIGURE/TABLE CAPTIONS:\n" + "\n".join(f"- {c}" for c in captions)
        )
    if _vision_enabled(use_vision):
        analyses = describe_result_figures(pdf_path, model=model)
        if analyses:
            blocks.append(
                "RESULT-FIGURE VISUAL ANALYSES (VLM):\n"
                + "\n".join(
                    f"- quality={a['quality']:g} form={json.dumps(a['form'], ensure_ascii=False)}"
                    f" — {a['summary']}"
                    for a in analyses
                )
            )
    return "\n\n".join(blocks)


# --------------------------------------------------------------------------- #
# Architecture-figure reference evidence (inverse gate: keep schematics)       #
# --------------------------------------------------------------------------- #

# Captions of architecture/method figures name their role; used as the
# deterministic fallback when no vision backend is available.
_ARCH_CAPTION_RE = re.compile(
    r"architect|overview|framework|pipeline|schematic|system|workflow|"
    r"the (proposed|overall)|our (method|model|approach|framework)|"
    r"illustration of|block diagram|network structure",
    re.IGNORECASE,
)

_ARCH_DESCRIBE_PROMPT = (
    "You are curating visual STYLE exemplars of ARCHITECTURE / METHOD / PIPELINE "
    "schematic figures from a published paper (system overviews, module diagrams, "
    "data-flow pipelines, mechanism schematics). Judge this image and describe its "
    "VISUAL FORM only — never its specific method, components, or labels.\n"
    'Return ONLY JSON: {"is_architecture_schematic": true|false, "quality": 0-10, '
    '"form": {"layout_archetype": "left-to-right pipeline|layered stack|radial hub|'
    'cyclic loop|swimlane|matrix grid|hourglass|control-plane overlay|split comparison", '
    '"palette_strategy": "restrained monochrome + accent|cool technical|warm editorial|'
    'grayscale + highlights|domain palette", "geometry_language": "rounded modules|'
    'sharp blocks|thin-line blueprint|layered slabs|node-link graph|annotated cards", '
    '"depth_model": "flat|paper cutout|isometric|blueprint", "composition": "one '
    'sentence on zones/flow, NOT the method", "label_density": "low|medium|high"}, '
    '"summary": "one sentence on the visual style, NOT the content"}.\n'
    "is_architecture_schematic=false for result plots (bar/line/scatter/heatmap), photos, "
    "tables, equations, or pages without a dominant schematic. quality is visual/design "
    "quality as a STYLE exemplar. Never transcribe the method's component names."
)


def describe_architecture_figures(
    pdf_path: str | Path,
    *,
    model: str | None = None,
    max_figures: int = 3,
    min_quality: float = 6.0,
) -> list[dict[str, Any]]:
    """VLM-gated VISUAL-FORM descriptions of a PDF's architecture/method figures.

    Inverse of ``describe_result_figures``: keeps schematic/architecture/pipeline
    diagrams and rejects result plots. Empty on any failure. Transfers FORM
    (layout/palette/geometry) only, never the paper's method components.
    """
    if not vision_available():
        return []
    descriptions: list[dict[str, Any]] = []
    for png in extract_result_figure_images(pdf_path):
        if len(descriptions) >= max_figures:
            break
        try:
            parsed = _loose_json(_vision_chat(_ARCH_DESCRIBE_PROMPT, png, model=model))
        except Exception:
            continue
        if not parsed.get("is_architecture_schematic"):
            continue
        try:
            quality = float(parsed.get("quality", 0))
        except (TypeError, ValueError):
            quality = 0.0
        form = parsed.get("form")
        if quality < float(min_quality) or not isinstance(form, dict):
            continue
        descriptions.append(
            {
                "quality": quality,
                "form": form,
                "summary": str(parsed.get("summary", ""))[:300],
            }
        )
    return descriptions


def keep_architecture_images(
    pdf_path: str | Path,
    *,
    model: str | None = None,
    max_images: int = 2,
    min_quality: float = 6.0,
) -> list[bytes]:
    """Return the PNG bytes of a PDF's best architecture/schematic figures.

    Same inverse VLM gate as ``describe_architecture_figures`` but keeps the
    image BYTES (for multimodal image-conditioning) rather than descriptions.
    Requires a vision backend — result plots must not be fed as architecture
    style references, so without the gate this returns []."""
    if not vision_available():
        return []
    kept: list[bytes] = []
    for png in extract_result_figure_images(pdf_path):
        if len(kept) >= max_images:
            break
        try:
            parsed = _loose_json(_vision_chat(_ARCH_DESCRIBE_PROMPT, png, model=model))
        except Exception:
            continue
        if not parsed.get("is_architecture_schematic"):
            continue
        try:
            quality = float(parsed.get("quality", 0))
        except (TypeError, ValueError):
            quality = 0.0
        if quality >= float(min_quality):
            kept.append(png)
    return kept


def architecture_reference_images(
    db: Any,
    paper_ids: Sequence[int],
    *,
    model: str | None = None,
    max_images: int = 3,
    per_paper: int = 1,
) -> list[bytes]:
    """Collect architecture-figure PNG bytes from the given reference papers.

    Feeds true image-conditioning: the retrieved exemplar papers' schematic
    figures, VLM-gated. Empty when no vision backend or no readable PDFs (the
    caller then falls back to the text-only style anchor).
    """
    if not paper_ids or not vision_available():
        return []
    out: list[bytes] = []
    for paper_id in paper_ids:
        if len(out) >= max_images:
            break
        pdf_path = ""
        try:
            conn = db.connect()
            try:
                row = conn.execute(
                    "SELECT pdf_path FROM papers WHERE id = ?", (int(paper_id),)
                ).fetchone()
                pdf_path = (row["pdf_path"] or "") if row else ""
            finally:
                conn.close()
        except Exception:
            continue
        if not pdf_path:
            continue
        for png in keep_architecture_images(
            pdf_path, model=model, max_images=per_paper
        ):
            out.append(png)
            if len(out) >= max_images:
                break
    return out


def architecture_evidence_text(
    db: Any,
    paper_id: int,
    *,
    use_vision: bool | None = None,
    model: str | None = None,
) -> str:
    """Architecture-figure STYLE evidence for one pool paper: architecture-oriented
    captions (+ optional VLM visual-form analyses). Returns "" when the paper has
    no readable PDF so the caller can fall back to abstract/notes."""
    pdf_path = ""
    try:
        conn = db.connect()
        try:
            row = conn.execute(
                "SELECT pdf_path FROM papers WHERE id = ?", (int(paper_id),)
            ).fetchone()
            pdf_path = (row["pdf_path"] or "") if row else ""
        finally:
            conn.close()
    except Exception:
        return ""
    if not pdf_path:
        return ""
    blocks: list[str] = []
    captions = [
        c for c in extract_figure_captions(pdf_path) if _ARCH_CAPTION_RE.search(c)
    ]
    if captions:
        blocks.append(
            "ARCHITECTURE/METHOD FIGURE CAPTIONS:\n"
            + "\n".join(f"- {c}" for c in captions)
        )
    if _vision_enabled(use_vision):
        analyses = describe_architecture_figures(pdf_path, model=model)
        if analyses:
            blocks.append(
                "ARCHITECTURE-FIGURE VISUAL-FORM ANALYSES (VLM):\n"
                + "\n".join(
                    f"- quality={a['quality']:g} form={json.dumps(a['form'], ensure_ascii=False)}"
                    f" — {a['summary']}"
                    for a in analyses
                )
            )
    return "\n\n".join(blocks)


# --------------------------------------------------------------------------- #
# Rendered-suite critique (deterministic + optional VLM)                       #
# --------------------------------------------------------------------------- #

_CRITIQUE_PROMPT = (
    "You are a strict publication-figure reviewer for a {venue_hint} manuscript. Judge the "
    "attached RENDERED result figure for publication readiness.\n"
    'Return ONLY JSON: {{"scores": {{"readability": 1-10, "composition": 1-10, '
    '"aesthetics": 1-10, "publication_readiness": 1-10}}, "findings": ["specific, '
    "actionable problems (overlapping labels, unreadable ticks, missing axis units, "
    'cramped legends, wasted space, inconsistent fonts)"], "verdict": "pass|revise"}}.\n'
    "verdict=revise if any score < 6 or any finding would block a camera-ready figure. "
    "Judge form only; never question the data values."
)

_VENUE_HINTS = {
    "stem_conference": "CCF-A / top ML-systems conference",
    "nature_family": "Nature-family journal",
    "social_humanities": "social-science / humanities journal",
    "biomed_omics": "biomedical / clinical journal",
}


def _deterministic_checks(path: str) -> tuple[dict[str, Any], list[str]]:
    findings: list[str] = []
    checks: dict[str, Any] = {"exists": False, "bytes": 0}
    file_path = Path(path)
    if not file_path.is_file():
        findings.append("file_missing")
        return checks, findings
    size = file_path.stat().st_size
    checks.update({"exists": True, "bytes": size})
    if size < 4096:
        findings.append("file_suspiciously_small")
    try:
        png = file_path.read_bytes()
    except Exception:
        findings.append("file_unreadable")
        return checks, findings
    stats = _png_bytes_stats(png)
    if stats is None:
        findings.append("image_undecodable")
        return checks, findings
    width, height, std = stats
    checks.update({"width": width, "height": height, "gray_std": round(std, 2)})
    if min(width, height) < 320:
        findings.append("image_resolution_too_low")
    if std < 10:
        findings.append("image_near_blank")
    return checks, findings


def critique_rendered_figures(
    image_paths: Sequence[str],
    *,
    style_profile: str = "",
    model: str | None = None,
    use_vision: bool | None = None,
) -> list[dict[str, Any]]:
    """Per-figure critique reports. Deterministic always; VLM when configured.

    Report verdicts: ``fail`` (deterministic problem), ``pass``/``revise`` (VLM
    judgement), or ``pass_deterministic_only`` when no vision backend ran.
    """
    venue_hint = _VENUE_HINTS.get(str(style_profile), "peer-reviewed")
    run_vision = _vision_enabled(use_vision)
    reports: list[dict[str, Any]] = []
    for path in image_paths:
        checks, findings = _deterministic_checks(str(path))
        report: dict[str, Any] = {
            "path": str(path),
            "checks": checks,
            "findings": findings,
            "vision": None,
        }
        if findings:
            report["verdict"] = "fail"
            reports.append(report)
            continue
        if run_vision:
            try:
                png = Path(path).read_bytes()
                parsed = _loose_json(
                    _vision_chat(
                        _CRITIQUE_PROMPT.format(venue_hint=venue_hint),
                        _shrink_png(png),
                        model=model,
                    )
                )
            except Exception:
                parsed = {}
            if parsed.get("scores"):
                report["vision"] = {
                    "scores": parsed.get("scores"),
                    "findings": [str(f) for f in (parsed.get("findings") or [])][:8],
                }
                verdict = str(parsed.get("verdict", "")).strip().lower()
                report["verdict"] = (
                    verdict if verdict in ("pass", "revise") else "revise"
                )
                reports.append(report)
                continue
        report["verdict"] = "pass_deterministic_only"
        reports.append(report)
    return reports


_VERDICT_SCORE = {
    "pass": 20.0,
    "pass_deterministic_only": 10.0,
    "revise": 5.0,
    "fail": -100.0,
}

# Skill axes from figure-quality / Nature adaptation / venue grammar.
# Not a trained model. Extra keys in figure_spec["quality_axes"] stay additive.
_STORY_ARCHETYPES = frozenset(
    {
        "schematic_led_composite",
        "asymmetric_mixed_modality",
        "image_plate_plus_quant",
    }
)
_APPLICATION_ROLES = frozenset(
    {
        "case_exhibit",
        "failure_gallery",
        "study_design",
        "protocol",
        "patient_vignette",
        "clinical_workflow",
    }
)
_APPLICATION_TERMS = (
    "clinical",
    "patient",
    "cohort",
    "bedside",
    "diagnosis",
    "treatment",
    "vignette",
    "protocol",
    "decision",
    "workflow",
    "case ",
)
_REFUSED_CHARTS = frozenset({"pie", "3d", "dual_y", "dual-y", "rainbow", "jet", "hsv"})
_NATURE_PROFILES = frozenset({"nature_family", "biomed_omics"})


def _spec_text(spec: dict[str, Any]) -> str:
    parts: list[str] = []
    for key in ("title", "caption", "caption_skeleton", "purpose", "claim"):
        value = spec.get(key)
        if isinstance(value, str) and value.strip():
            parts.append(value)
    return " ".join(parts).lower()


def _spec_charts(spec: dict[str, Any]) -> list[str]:
    charts: list[str] = []
    if spec.get("chart"):
        charts.append(str(spec["chart"]).lower())
    panels = spec.get("panels")
    if isinstance(panels, list):
        for panel in panels:
            if isinstance(panel, dict) and panel.get("chart"):
                charts.append(str(panel["chart"]).lower())
    return charts


def _figure_dimension_scores(
    spec: dict[str, Any] | None,
    *,
    style_profile: str,
    grammar: dict[str, Any],
) -> dict[str, float]:
    """Checklist scores from the figure contract. Missing spec → zeros."""
    dims = {
        "logic": 0.0,
        "texture": 0.0,
        "richness": 0.0,
        "frontier": 0.0,
        "fit": 0.0,
        "story_composite": 0.0,
        "application_scene": 0.0,
        "venue": 0.0,
        "aesthetics": 0.0,
        "form_prior": 0.0,
    }
    if not isinstance(spec, dict) or not spec:
        return dims
    panels = spec.get("panels") if isinstance(spec.get("panels"), list) else []
    n_panels = len(panels)
    archetype = str(spec.get("archetype") or "").strip()
    role = str(spec.get("role") or "").strip()
    blob = _spec_text(spec)
    charts = _spec_charts(spec)
    nature = style_profile in _NATURE_PROFILES
    layout = str(spec.get("layout") or spec.get("composition") or "").lower()

    dims["richness"] = min(n_panels, 6) * 2.0
    if len(blob) >= 80:
        dims["richness"] += 2.0

    if archetype in _STORY_ARCHETYPES:
        dims["story_composite"] += 12.0
    if spec.get("hero_panel") or spec.get("hero"):
        dims["story_composite"] += 6.0
    if n_panels >= 3:
        dims["story_composite"] += 8.0
    elif n_panels <= 1:
        dims["story_composite"] -= 8.0 if nature else 2.0
    if "2x2" in layout or "2×2" in layout or layout in {"equal_grid", "equal-weight"}:
        dims["story_composite"] -= 10.0 if nature else 4.0
    if nature and n_panels == 4 and not (spec.get("hero_panel") or spec.get("hero")):
        if archetype not in _STORY_ARCHETYPES:
            dims["story_composite"] -= 6.0

    if role in _APPLICATION_ROLES:
        dims["application_scene"] += 10.0
    if any(term in blob for term in _APPLICATION_TERMS):
        dims["application_scene"] += 6.0
    if nature and dims["application_scene"] <= 0:
        dims["application_scene"] -= 4.0

    recommended = {
        str(item).lower() for item in (grammar.get("recommended_charts") or [])
    }
    discouraged = {
        str(item).lower() for item in (grammar.get("discouraged_charts") or [])
    }
    for chart in charts:
        if chart in recommended:
            dims["venue"] += 6.0
        if chart in discouraged:
            dims["venue"] -= 12.0
        if chart in _REFUSED_CHARTS:
            dims["venue"] -= 20.0
    if role:
        dims["fit"] += 2.0
    if spec.get("claim"):
        dims["fit"] += 4.0

    purposes = [
        str(panel.get("purpose") or panel.get("role") or "").strip()
        for panel in panels
        if isinstance(panel, dict)
    ]
    unique = {item for item in purposes if item}
    if n_panels >= 2 and len(unique) >= 2:
        dims["logic"] += 8.0
    elif n_panels >= 2:
        dims["logic"] -= 4.0
    if spec.get("claim"):
        dims["logic"] += 3.0

    if archetype in {"asymmetric_mixed_modality", "image_plate_plus_quant"}:
        dims["frontier"] += 6.0
    if dims["application_scene"] > 0:
        dims["frontier"] += 3.0

    extra = spec.get("quality_axes")
    if isinstance(extra, dict):
        for key, value in extra.items():
            try:
                dims[str(key)] = float(value)
            except (TypeError, ValueError):
                continue

    overlay = (
        grammar.get("figure_knowledge")
        if isinstance(grammar.get("figure_knowledge"), dict)
        else {}
    )
    priors = (
        overlay.get("form_priors")
        if isinstance(overlay.get("form_priors"), dict)
        else {}
    )
    form_id = str(spec.get("form_id") or "").strip()
    if form_id and form_id != "unclassified":
        try:
            share = float(priors.get(form_id) or 0.0)
        except (TypeError, ValueError):
            share = 0.0
        dims["form_prior"] = round(share * 10.0, 4)
        dims["venue"] += dims["form_prior"]
    return dims


def rank_figure_candidates(
    candidates: Sequence[str],
    *,
    style_profile: str = "",
    venue_figure_grammar: dict[str, Any] | None = None,
    figure_spec: dict[str, Any] | None = None,
    candidate_specs: Sequence[dict[str, Any] | None] | None = None,
    use_vision: bool | None = None,
) -> dict[str, Any]:
    """Pick one candidate with the figure-quality checklist. Not a trained model.

    Pixel critique + PDF integrity still run. Venue/story/application scores
    come from the figure contract so selection works without a VLM.
    A failing singleton is still returned so fake-provider writes are not
    blocked by the 4 KiB critique floor.
    """
    paths = [str(path) for path in candidates if str(path).strip()]
    if not paths:
        raise ValueError("rank_figure_candidates requires at least one path")
    grammar = venue_figure_grammar if isinstance(venue_figure_grammar, dict) else {}
    profile = str(style_profile or grammar.get("style_profile") or "").strip()
    reports = critique_rendered_figures(
        paths, style_profile=profile, use_vision=use_vision
    )
    specs: list[dict[str, Any] | None]
    if candidate_specs is None:
        specs = [figure_spec] * len(reports)
    else:
        specs = list(candidate_specs)
        if len(specs) < len(reports):
            specs.extend([figure_spec] * (len(reports) - len(specs)))
    ranked: list[dict[str, Any]] = []
    for index, report in enumerate(reports):
        vision = report.get("vision") or {}
        scores = vision.get("scores") or {}
        dims = _figure_dimension_scores(
            specs[index] if index < len(specs) else figure_spec,
            style_profile=profile,
            grammar=grammar,
        )
        score = _VERDICT_SCORE.get(str(report.get("verdict") or ""), 0.0)
        for key, weight in (
            ("aesthetics", 1.0),
            ("publication_readiness", 1.0),
            ("composition", 0.8),
            ("readability", 0.8),
        ):
            try:
                value = float(scores.get(key) or 0)
            except (TypeError, ValueError):
                continue
            score += value * weight
            if key == "aesthetics":
                dims["aesthetics"] += value
        # ponytail: texture without VLM is PDF integrity only; pixels stay unlearned
        path = Path(str(report.get("path") or ""))
        integrity_penalty = 0.0
        if path.suffix.lower() == ".pdf":
            try:
                from research_harness.visualization.figure_integrity import (
                    check_figure,
                )

                inspected = check_figure(path)
                integrity_penalty = 25.0 * len(inspected.majors) + 5.0 * (
                    len(inspected.findings) - len(inspected.majors)
                )
            except Exception:
                integrity_penalty = 0.0
        dims["texture"] -= integrity_penalty
        score += sum(dims.values())
        ranked.append(
            {
                "path": str(report.get("path") or ""),
                "score": score,
                "report": report,
                "dimensions": dims,
            }
        )
    ranked.sort(key=lambda item: item["score"], reverse=True)
    winner = ranked[0]
    return {
        "path": winner["path"],
        "score": winner["score"],
        "report": winner["report"],
        "dimensions": winner["dimensions"],
        "ranked": ranked,
        "style_profile": profile,
    }
