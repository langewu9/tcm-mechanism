# R visualization worker

This private Plumber service renders chart-ready JSON into SVG, PDF, PNG, and a self-contained HTML wrapper. It does not connect to Django or PostgreSQL and accepts bounded summary-bar, GO/KEGG enrichment-bubble, and differential-proteomics volcano contracts. The Python worker selects chart data from a completed analysis task, authorizes the service request, and saves returned files into private application storage.

`renv.lock` pins the direct renderer libraries and their CRAN `Depends`/`Imports`/`LinkingTo` dependency closure. The image fixes R at 4.4.3 and restores this lock during its build. Build the image with Docker from the repository root using the Compose configuration; the container listens on its private Compose network and does not publish a host port.

## Contract

- `GET /health` reports only service readiness and renderer version.
- `POST /render` requires `Authorization: Bearer <R_VIZ_API_TOKEN>`.
- The JSON body contains a supported `chartType` (`"bar"`, `"enrichment_bubble"`, or `"volcano"`), a 64-character SHA-256 of the canonical chart input, and a title. Bar and enrichment charts accept 1–100 bounded points. Volcano charts accept up to 5,000 persisted rows with log2FC, P value, FDR, and the analysis threshold-selection flag; rows without valid log2FC and P values are excluded by Django before the payload is sent.
- The response contains base64-encoded artifacts. The caller must enforce a maximum response size and write only to private object/file storage.

The service rejects unconfigured credentials, unsupported chart types, oversized bodies, labels, and non-finite values. The artifacts are static; interactive Plotly/visNetwork output, PCA, and heatmaps remain future work. Never include case text, patient details, account IDs, or uploaded raw matrices in the rendering payload.
