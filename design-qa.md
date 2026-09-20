# Network Evidence Figure Design QA

## Evidence

- Source visual truth: `C:\Users\liuli\AppData\Local\Temp\codex-clipboard-704e118c-33d0-420a-82a7-6c23e4b67509.png`
- Browser-rendered implementation: `D:\MMDD\tcm_pharmacology_platform\network-evidence-wide-final.png`
- Combined before/after comparison: `D:\MMDD\tcm_pharmacology_platform\network-evidence-comparison-wide.png`
- Route and state: `http://127.0.0.1:3000/visualization`, default 麦门冬汤–肺纤维化 query, Reactome enrichment complete, “03 证据链网络” selected.
- Browser viewport: 1920 × 1200 CSS px, device scale factor 1.
- Source image: 1228 × 793 px.
- Implementation screenshot: 1858 × 1191 px captured from the 1920 × 1200 desktop viewport.
- Density normalization: source and implementation were placed in a single 1920 px-wide comparison canvas without evaluating differences caused solely by source density.

## Full-view comparison evidence

The original circular-node layout visibly collapses long target labels and packs adjacent target circles into a continuous column. The revised browser-rendered layout uses five semantic layers, fixed minimum node separation, two-line truncation, degree-aware node widths, restrained edge opacity, and separate solid/dashed relationship styles. At the desktop reference breakpoint all five layers are visible without horizontal panning, node overlap, or label collision.

## Focused-region comparison evidence

The central component–target region and the right target-set–pathway region were inspected in `network-evidence-comparison-wide.png`. Focused evidence was necessary because label collision and edge density were the primary defects. Component pills, target cards, enrichment pathways, and the disease node remain individually readable after the fix.

## Fidelity surfaces

- Fonts and typography: existing product typography is preserved. Network labels use readable 10.4–11 px optical sizes, two-line wrapping, semibold hierarchy, and full labels in SVG titles.
- Spacing and layout rhythm: vertical placement is calculated from the largest layer. The network is reduced to the nine highest-evidence targets, producing consistent gaps without changing surrounding card rhythm.
- Colors and visual tokens: the existing parchment, cinnabar, ochre, moss, and brown palette is retained. Nodes use white paper fills with categorical strokes; edges are lower-contrast so labels remain dominant.
- Image quality and asset fidelity: the figure remains a data-driven vector visualization, appropriate for publication-style network output. No raster placeholders or decorative substitute assets were introduced.
- Copy and content: layer headings now distinguish active compounds, candidate targets, target set, pathways, and disease. The caption explains top-nine selection, node sizing, and solid/dashed edge semantics.

## Comparison history

1. Initial finding — P1: circular nodes overlapped vertically and clipped long names.  
   Fix: replaced circles with category-coded rounded cards, added deterministic layer spacing, and wrapped long names to two lines.
2. First implementation finding — P2: the graph scaled too small in a narrow result column.  
   Fix: made completed results span the full workbench width and preserved a readable minimum graph width with responsive horizontal browsing on narrow screens.
3. Second implementation finding — P2: the multi-herb label exceeded its node width.  
   Fix: applied category-specific line lengths and two-line truncation for herb, target, pathway, set, and disease nodes.
4. Post-fix evidence: `network-evidence-wide-final.png` shows the complete 1920 px desktop network with no overlapping nodes or labels. Browser console contains no warnings or errors.

## Interaction checks

- Submitted the default herb/disease query.
- Waited for Reactome enrichment completion.
- Selected the “03 证据链网络” tab.
- Confirmed the network updates with enrichment pathways.
- Checked browser console errors and warnings: none.

## Findings

- No actionable P0, P1, or P2 findings remain.
- P3: on narrow desktop and tablet widths the graph intentionally uses horizontal browsing to preserve publication-grade text size.

## Final result

final result: passed
