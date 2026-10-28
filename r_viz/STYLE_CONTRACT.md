# R chart style contract — 0.3.0

Goal: make persisted evidence and synthetic previews easier to compare without changing statistical meaning. This is a product visualization iteration, not a claim of journal submission compliance.

All rendering and preview/export generation use R. SVG/PDF retain text; PNG is exported at 300 dpi. White backgrounds, consistent sans-serif typography, grey guides, and restrained colours are shared across charts. Images keep their natural aspect ratio in the webpage.

| Chart | Question | Encoding |
| --- | --- | --- |
| Counts / degree | How do recorded counts compare? | Sorted discrete points with numeric labels; no connecting lines or invented uncertainty. |
| GO significance | Which recorded terms have stronger adjusted significance? | Purple points by −log10(FDR), faceted by supplied ontology. No inferred GeneRatio. |
| Enrichment bubbles | How do recorded ratios, hit counts and FDR differ? | Position = supplied ratio; area = hit count; purple light-to-dark = −log10(FDR). |
| Volcano | Which already-selected proteins increased or decreased? | log2FC/P axes retained; direction is derived only from log2FC, selection is never recomputed. Brick red/up triangle; blue/down triangle; grey/not selected. A few selected labels use collision avoidance. |
| Networks | Which nodes and edges were actually returned? | Fixed node-type colours/shapes; size = supplied degree, linewidth = supplied score. No new edges or claimed causal modules. |

Palette: brick red `#B65A50`, slate blue `#4E6D9C`, violet `#70578B`, neutral grey `#B8BCC5`, text `#30343B`. Herb/compound/pathway/disease accents have fixed type mappings, not arbitrary per-image colour assignment. Purple sequential scales include labelled colour bars; shape coding supports monochrome readability.

Existing chart keys and the legacy `bar` wire type stay compatible; their new rendering is a point chart. Archived task artifacts are not rewritten. New renderings report `r-viz-0.3.0` and the demo catalog uses versioned image URLs.

QA: R contract tests inspect data, point layers, colour scales, shapes, input preservation and invalid input handling. All 14 synthetic fixtures are regenerated through the R renderer; SVG/PDF/PNG/HTML signatures and hashes are checked. Review PNGs for fonts, clipping, crowded labels, legends and colour consistency. Synthetic previews are not experimental evidence.

## Unified product typography — 2026-10-14

The web interface and echarts4r labels/HTML controls share the offline font stack:
Microsoft YaHei → PingFang SC → Noto Sans CJK SC → Noto Sans SC → system sans-serif.
Static R plots retain Microsoft YaHei on Windows and Noto Sans CJK SC on Linux.
Headings use weight 600, body 400, controls 500; numerical tables use tabular figures.
Technical code/identifiers use a separate monospace stack. Calligraphy and Google
Fonts imports are removed from the interface; existing colour/layout and full
chart height are preserved.

New renders report r-viz-0.4.1. Only the 16 synthetic and 7 public demo HTML widgets
are refreshed here; input fixtures and static SVG/PDF/PNG are unchanged. Their
manifests retain the static renderer version and record htmlRendererVersion for
the refreshed HTML. Historical user task artifacts are not overwritten.
Run web test:typography and the R interactive/style contracts before packaging.
