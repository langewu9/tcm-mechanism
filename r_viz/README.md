# R visualization worker

This private Plumber service renders chart-ready JSON into SVG, PDF, PNG, and a self-contained HTML wrapper. It does not connect to Django or PostgreSQL and accepts only a bounded bar-chart contract. The Python worker is responsible for selecting chart data from a completed analysis task, authorizing the service request, and saving returned files into private application storage.

`renv.lock` pins the direct renderer libraries and their CRAN `Depends`/`Imports`/`LinkingTo` dependency closure. The image fixes R at 4.4.3 and restores this lock during its build. Build the image with Docker from the repository root using the Compose configuration; the container listens on its private Compose network and does not publish a host port.

## Contract

- `GET /health` reports only service readiness and renderer version.
- `POST /render` requires `Authorization: Bearer <R_VIZ_API_TOKEN>`.
- The JSON body contains `chartType: "bar"`, a 64-character SHA-256 of the canonical chart input, a title, and 1–100 `{label, value}` points.
- The response contains base64-encoded artifacts. The caller must enforce a maximum response size and write only to private object/file storage.

The service rejects unconfigured credentials, unsupported chart types, oversized bodies, labels, and non-finite values. This first renderer is static; interactive Plotly/visNetwork output and case-specific charts remain future work. Never include case text, patient details, account IDs, or uploaded raw matrices in the rendering payload.
