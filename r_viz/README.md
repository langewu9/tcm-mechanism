# R visualization worker

This private Plumber service renders chart-ready JSON into SVG, PDF, PNG, and a self-contained HTML wrapper. It does not connect to Django or PostgreSQL and accepts bounded summary-bar, GO/KEGG enrichment-bubble, and differential-proteomics volcano contracts. The Python worker selects chart data from a completed analysis task, authorizes the service request, and saves returned files into private application storage.

`renv.lock` pins the direct renderer libraries and their CRAN `Depends`/`Imports`/`LinkingTo` dependency closure. The image fixes R at 4.4.3 and restores this lock during its build. Build the image with Docker from the repository root using the Compose configuration; the container listens on its private Compose network and does not publish a host port.

## Contract

- `GET /health` reports only service readiness and renderer version.
- `POST /render` requires `Authorization: Bearer <R_VIZ_API_TOKEN>`.
- The JSON body contains a supported `chartType` (`"bar"`, `"enrichment_bubble"`, or `"volcano"`), a 64-character SHA-256 of the canonical chart input, and a title. Bar and enrichment charts accept 1–100 bounded points. Volcano charts accept up to 5,000 persisted rows with log2FC, P value, FDR, and the analysis threshold-selection flag; rows without valid log2FC and P values are excluded by Django before the payload is sent.
- The response contains base64-encoded artifacts. The caller must enforce a maximum response size and write only to private object/file storage.

The service rejects unconfigured credentials, unsupported chart types, oversized bodies, labels, and non-finite values. The artifacts are static; interactive Plotly/visNetwork output, PCA, and heatmaps remain future work. Never include case text, patient details, account IDs, or uploaded raw matrices in the rendering payload.

The renderer additionally accepts `network`: 2–80 validated nodes, 1–500 actual edges, and a deterministic circular or layered layout. Python provides the persisted STRING physical graph or local evidence graph, calculates unique-neighbor degrees, and discloses input/subgraph counts. No edges are inferred by R. The four artifacts include node and edge tables in HTML. Reactome has its own labeled enrichment category and is not merged into KEGG.

R 0.2.0 fixes UTF-8 JSON decoding and scalar JSON serialization, and uses an explicit CJK font. Set `R_VIZ_FONT_FAMILY` for another installed font (Windows default: Microsoft YaHei; Docker default: Noto Sans CJK SC). On native Windows start R with `Sys.setlocale('LC_CTYPE', '.UTF-8')` before loading `plumber.R`. Native Windows Celery solo is for local preview only, not production deployment.

Renderer 0.3.0 applies a shared light research theme, a teal/coral directional volcano palette, explicit counts and bounded gene labels, labeled summary bars with visible zero values, and coordinated enrichment/network styles. Point coordinates, input relationships and persisted selection flags are preserved. Volcano background regions illustrate only the supplied log2FC/P thresholds; point colours follow the full analysis selection flags, including any additional filters. No new statistics or enrichment evidence are calculated by these style changes. Regenerate the synthetic gallery after restarting R. Previously saved private artifacts remain historical outputs; newly analyzed datasets use the current renderer.

## Synthetic delivery gallery

Start the trusted local service from `r_viz/` with `R_VIZ_API_TOKEN` set to a local secret (never commit its value):

```sh
Rscript -e "Sys.setlocale('LC_CTYPE', '.UTF-8'); plumber::pr_run(plumber::pr('plumber.R'), host='127.0.0.1', port=8001)"
```

Then from the repository root, set the same `R_VIZ_API_TOKEN` and `R_VIZ_BASE_URL=http://127.0.0.1:8001` in the preparation environment and run `python r_viz/prepare_demo_gallery.py`. The script uses only deterministic synthetic fixtures, not uploaded files or the database. It creates 14 JSON keys and 56 R artifacts under `public/r-demo/`, then publishes a manifest with artifact hashes. `cd web` and run `pnpm build:delivery` to verify and package these resources. The `/demo` page provides 11 module scenarios alongside the gallery. See `docs/delivery-readiness-2026-10-11.md` for remaining production requirements. These examples are not scientific evidence; HTML exports are static image/data wrappers.
