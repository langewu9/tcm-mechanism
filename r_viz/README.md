# R visualization worker

This private Plumber service renders chart-ready JSON into SVG, PDF, PNG, and a self-contained HTML wrapper. It does not connect to Django or PostgreSQL and accepts bounded summary-bar, GO/KEGG enrichment-bubble, and differential-proteomics volcano contracts. The Python worker selects chart data from a completed analysis task, authorizes the service request, and saves returned files into private application storage.

`renv.lock` pins the direct renderer libraries and their CRAN `Depends`/`Imports`/`LinkingTo` dependency closure. The image fixes R at 4.4.3 and restores this lock during its build. Build the image with Docker from the repository root using the Compose configuration; the container listens on its private Compose network and does not publish a host port.

## Contract

- `GET /health` reports only service readiness and renderer version.
- `POST /render` requires `Authorization: Bearer <R_VIZ_API_TOKEN>`.
- The JSON body contains a supported `chartType` (`"bar"`, `"enrichment_bubble"`, or `"volcano"`), a 64-character SHA-256 of the canonical chart input, and a title. Bar and enrichment charts accept 1–100 bounded points. Volcano charts accept up to 5,000 persisted rows with log2FC, P value, FDR, and the analysis threshold-selection flag; rows without valid log2FC and P values are excluded by Django before the payload is sent.
- The response contains base64-encoded artifacts. The caller must enforce a maximum response size and write only to private object/file storage.

The service rejects unconfigured credentials, unsupported chart types, oversized bodies, labels, and non-finite values. SVG/PDF/PNG exports are static; HTML exports contain self-contained echarts4r interactions. PCA and expression-matrix heatmaps remain separate work. Never include case text, patient details, account IDs, or uploaded raw matrices in the rendering payload.

The renderer additionally accepts `network`: 2–80 validated nodes, 1–500 actual edges, and a deterministic circular or layered layout. Python provides the persisted STRING physical graph or local evidence graph, calculates unique-neighbor degrees, and discloses input/subgraph counts. No edges are inferred by R. The four artifacts include node and edge tables in HTML. Reactome has its own labeled enrichment category and is not merged into KEGG.

R 0.2.0 fixes UTF-8 JSON decoding and scalar JSON serialization, and uses an explicit CJK font. Set `R_VIZ_FONT_FAMILY` for another installed font (Windows default: Microsoft YaHei; Docker default: Noto Sans CJK SC). On native Windows start R with `Sys.setlocale('LC_CTYPE', '.UTF-8')` before loading `plumber.R`. Native Windows Celery solo is for local preview only, not production deployment.

Renderer 0.4.2 uses a coordinated blue/rose/purple palette, directional volcano symbols, point-based summaries and circular evidence networks. Interactive HTML supports name lookup, legend filtering, neighbour highlighting, zoom and pan. Plotted values, selection flags and saved source evidence remain unchanged. Regenerate galleries after renderer upgrades; historical private artifacts retain their original version.

## Synthetic delivery gallery

Start the trusted local service from `r_viz/` with `R_VIZ_API_TOKEN` set to a local secret (never commit its value):

```sh
Rscript -e "Sys.setlocale('LC_CTYPE', '.UTF-8'); plumber::pr_run(plumber::pr('plumber.R'), host='127.0.0.1', port=8001)"
```

Then from the repository root, set the same `R_VIZ_API_TOKEN` and `R_VIZ_BASE_URL` and run:

```sh
python r_viz/test_demo_fixtures.py
python r_viz/prepare_demo_gallery.py
python r_viz/prepare_public_gallery.py
cd web
pnpm build:delivery
```

The first generator creates 16 deterministic synthetic fixtures and 64 artifacts in `public/r-demo/`. The second creates 7 public STRING examples and 28 artifacts in `public/r-public-demo/`, using the checked-in STRING 12.5 snapshot and its CC BY 4.0 attribution. It contacts STRING only with explicit `--refresh` or if the snapshot is missing. Both output directories are ignored by Git; regenerate them before packaging Nginx. The `/demo` gallery uses six-card pages with full-size chart windows. Synthetic examples and public reference data are labelled separately from private task results.
