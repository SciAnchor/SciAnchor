# Style Fingerprints For RH Paper Figures

Use this reference when a figure risks looking like previous academic diagrams.

## Archetype Catalog

1. **Control-plane overlay**: a governance layer sits above a main model pipeline. Good for EventWiki, memory, audit, and agent systems.
2. **Layered stack**: raw inputs at bottom, abstractions in the middle, decisions at top. Good for representation learning and hierarchical methods.
3. **Cyclic loop**: forecast, observe, write back, update, forecast again. Good for self-evolution and feedback mechanisms.
4. **Swimlane**: separate lanes for data, text/event, model, evaluation. Good for leakage-safe workflows.
5. **Radial hub**: a central abstraction connected to modules. Good for unifying thesis figures, but avoid if it becomes generic.
6. **Hourglass**: many raw signals compress into a bottleneck then expand into tasks. Good for temporal primitives or state abstraction.
7. **Matrix grid**: rows are domains/stages, columns are controls/evidence. Good for evaluation protocols.
8. **Timeline-to-forecast**: event timeline feeds forecast windows. Good for origin-safe event handling.

## Palette Rotation

Avoid repeating palettes across papers.

- Graphite + amber + green: event/control/calibration.
- Ink + teal + coral: multimodal alignment and contrast.
- Warm paper + black + red oxide: editorial systems paper.
- Cool gray + blue + lime: benchmark/evaluation figure.
- White + charcoal + violet + orange: method comparison.
- Deep navy + cyan + pale yellow: only for night/operations themes; avoid generic AI look.
- Print-safe monochrome + one hatch pattern: camera-ready grayscale robustness.

## Anti-Similarity Checks

Reject a draft if:

- It could be mistaken for the previous paper's figure after replacing labels.
- It uses the same left-to-right block pipeline with the same blue accents as a default.
- The central contribution is visually smaller than generic inputs/outputs.
- Colors are decorative instead of encoding semantic roles.
- Text boxes dominate and the reader cannot infer the mechanism from shape/flow.

## Prompt Diversity Moves

To diversify, change at least two:

- layout archetype;
- palette strategy;
- geometry language;
- density and label strategy;
- camera/depth model;
- caption framing.
