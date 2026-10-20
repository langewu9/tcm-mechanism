# Production deployment

This Compose file is a production-oriented starting point, not a tested public deployment. It runs Django/Gunicorn, Celery, PostgreSQL, Redis, the private R renderer, and the built React/Vite UI. Only Nginx publishes host ports (80/443); PostgreSQL, Redis, Django, and R have no public host ports. The React app and API share one origin, retaining Django session/CSRF authentication.

## Before the first start

1. Provision a Linux server with Docker Engine and the Compose plugin. Point the chosen public DNS name at it and allow inbound TCP 80/443 in the firewall.
2. Provision a private S3-compatible bucket and credentials restricted to that bucket. Keep public access disabled. Configure the provider's versioning/replication and retention policy separately; the database scripts below do not back up uploaded objects.
3. Copy `.env.production.example` to `.env.production`, generate unique random values for all secrets, and enter the DNS name, object-storage settings, and real SMTP credentials/from address. Configure `PUBLIC_BASE_URL` as the public HTTPS origin. Set `ADMIN_NOTIFICATION_EMAILS` to one or more mailbox addresses if the platform should notify administrators after an applicant verifies their email. Keep `.env.production` out of version control and restrict its filesystem permissions (`chmod 600 .env.production`). Hex-only PostgreSQL and Redis passwords avoid URL-escaping issues in the internal connection strings.
4. Obtain a valid TLS certificate for the domain and install its full chain as `deploy/certs/fullchain.pem` and its private key as `deploy/certs/privkey.pem`. Keep the private key out of Git and restrict its permissions. Renew the certificate using the chosen certificate authority; reload Nginx after renewal.

Example secret generation on Linux:

```sh
openssl rand -hex 32
python3 -c 'import secrets; print(secrets.token_urlsafe(64))'
```

## Start and operate

### Prepare synthetic presentation assets before building Nginx

The Vite build reads the repository-root `public/` directory. The Nginx image now includes it and uses `pnpm build:delivery`, which refuses to package an incomplete R demonstration gallery. Generated gallery artifacts are intentionally not committed to Git. On a trusted preparation machine, start the private R service as described in `r_viz/README.md`, set `R_VIZ_BASE_URL` and `R_VIZ_API_TOKEN` locally, then run:

```sh
python r_viz/test_demo_fixtures.py
python r_viz/prepare_demo_gallery.py
cd web
pnpm test:demo
pnpm build:delivery
```

Return to the repository root before running Compose. This prepares only synthetic, explicitly labeled examples; never copy uploaded files, database exports, secrets or patient information into `public/`. Missing assets should be regenerated, not replaced by real research records. The gate checks all 14 JSON keys, 56 image/document artifacts and artifact SHA-256 digests in source and built output. See `docs/delivery-readiness-2026-10-11.md` for demonstration boundaries and remaining production acceptance work.

Run from the repository root:

```sh
docker compose --env-file .env.production -f deploy/compose.production.yml config --quiet
docker compose --env-file .env.production -f deploy/compose.production.yml build
docker compose --env-file .env.production -f deploy/compose.production.yml up -d
docker compose --env-file .env.production -f deploy/compose.production.yml ps
docker compose --env-file .env.production -f deploy/compose.production.yml exec api python manage.py createsuperuser
```

The one-shot `setup` service runs `check --deploy --fail-level WARNING`, migrations and static collection. Both API and worker wait for its successful exit; the API does not run migrations per Gunicorn replica. Nginx waits until the API health check succeeds. HSTS applies to the configured host. The optional domain-wide `includeSubDomains` and browser-preload policies are deliberately not required (`security.W005`/`security.W021` are silenced); enabling them requires the domain owner's review of every subdomain. Other deployment warnings, including use of a process-local rate-limit cache, still fail setup. Create the first administrator with `createsuperuser`.

Researcher registration creates an inactive account application. The applicant must verify the submitted address using the emailed, 24-hour link, then a platform administrator must review and enable the account in Django Admin before sign-in. Changing an applicant's email in Admin invalidates the previous verification and deactivates the account. Registration, verification, and resend endpoints are CSRF-protected and rate-limited by Django; registration also has an Nginx limit. Resending uses the same public response for existing and unknown addresses. Verify SMTP delivery, spam filtering, and administrator notification with a staging mailbox before public launch; the Compose configuration cannot validate external mail credentials. Inspect `docker compose ... logs setup api worker nginx` for failures. To update, build the new image and run `up -d`; take a verified backup before schema-changing releases. These steps do not provide rolling, zero-downtime schema deployment.

Django maintenance access now requires an active staff superuser, including the login form; staff model permissions do not grant platform-wide access. Research tasks, proteomics rows, datasets and cases are read-only in maintenance. Sensitive research reads/downloads/exports are recorded as bounded identity/record references in `SensitiveAccessEvent`, without copying research content or credentials. If access evidence cannot be saved, sensitive responses return 503. Apply migrations 0026/0027 before loading this API version. See [security boundaries and quotas](../docs/security-boundary-audit-quota-2026-10-20.md) for exact coverage and limits.

API documentation and integration monitoring are maintenance tools at `/django-admin/platform-api/` and `/django-admin/platform-integrations/`, with links on the maintenance index. Both require the same superuser boundary; documentation/schema aliases do not expose content anonymously. The React homepage, workspace navigation and public demos no longer advertise these tools. Rebuild the React assets and run the existing static collection/setup lifecycle to deploy this relocation; the maintenance script is served from Django static files. Existing test APIs, CSRF and per-request model/external consent remain unchanged. This relocation introduces no database migration.

Retained original uploads default to 1 GiB and 100 datasets per account, including archived originals. `DATASET_STORAGE_QUOTA_BYTES` and `DATASET_COUNT_QUOTA` set global defaults. Superusers can adjust a user's MiB/count overrides in the existing Users edit page; blank inherits defaults and zero blocks new uploads. Lowering a budget never deletes existing files. Upload admission uses a PostgreSQL user-row lock through file/record creation; SQLite is development-only for this guarantee. Quota changes record the administrator and before/after values. Generated results and charts are outside this original-upload budget.

The Django object-storage adapter uses a private S3-compatible bucket and streams files through permission-checked Django endpoints. It does not publish direct public object URLs. The R service is reachable only over its internal network. Uploaded research files still need a retention, deletion, and restore policy appropriate to their sensitivity. When moving an existing deployment from local `MEDIA_ROOT` to S3, copy every referenced object while preserving its storage key, compare stored checksums, and only then switch the application setting; the Compose file does not migrate local files automatically.

## HTTP limits and process controls

The read-only `/api/v1/admin/runtime-logs/` endpoint is linked from Django Admin and requires an active staff superuser. It queries allowlisted diagnostic metadata, not arbitrary log files. API and worker share the private `runtime_logs` volume at `/app/var/runtime-logs`; Nginx has no mount. Rebuild the Python image and recreate API/worker to load this addition; no database migration is introduced. Linux local POSIX file locks coordinate rotation. Four files retain at most about 4 MiB and each query scans at most the latest 1 MiB, so this is not a complete historical log archive. Diagnostic write failures do not block business work; read failures return safe 503, and sensitive-access audit failure still withholds the response. See [interface coverage and limits](../docs/runtime-log-interface-2026-10-20.md).

- Ordinary request bodies are limited to 1 MiB by Nginx and `API_REQUEST_MAX_BYTES` (default 1048576) by Django. JSON is read with a bounded parser and has a 64-level nesting cap. Login and registration passwords have a 1024-character input cap. Dataset POSTs have a separate 100 MiB file limit plus 1 MiB multipart allowance in Django, and a 110 MiB edge limit; only one file per request is accepted. Raising an application limit also requires reviewing the Nginx limit.
- `DJANGO_USER_RATE` defaults to 600/minute per signed-in user. Expensive research submissions share `DJANGO_RESEARCH_SUBMISSION_RATE` (120/hour), with existing external-service limits retained. Production uses the private Redis cache database across workers. DRF cache throttles are approximate under races, not billing quotas or DDoS protection.
- The Nginx edge has a separate 600/minute IP budget and existing login/registration budgets. It overwrites forwarded client-IP/protocol headers. Django and Gunicorn must remain private behind this single trusted edge. A CDN or extra load balancer requires a reviewed real-IP configuration; simply exposing Gunicorn or trusting arbitrary forwarding chains invalidates this setup.
- API responses, including errors and private file streams, use `private, no-store`. Hashed static assets cache for one year and can use gzip; SPA HTML uses `no-cache`; proxied private responses do not use gzip. API exceptions and edge 413/429/502/504 failures use a JSON error envelope with a request ID. Protocol errors rejected before an HTTP request is accepted need not be JSON.
- Nginx and Gunicorn access logs omit query strings. Proxy API logs use the response request ID so they can be matched to WSGI logs; logs still require access restrictions, rotation and retention configuration. Unknown HTTP Hosts and TLS SNI are rejected. Private uploads are never served as public static files.
- `config/gunicorn.py` sets bounded workers, request recycling and timeouts; the runtime control socket is disabled. Adjust concurrency only after measuring database connections, CPU, upload parsing and job load on the target server. This round has no production capacity measurement.

The Docker build context excludes `.env.*`, TLS certificates, database dumps and backups. Keep real credentials and research data out of all source/public asset directories even when ignored by Git.

## Database backup and restore

Create a timestamped PostgreSQL custom-format dump and SHA-256 file:

```sh
deploy/backup-postgres.sh
```

The default output directory is `backups/`; pass another directory as the first argument when needed. New backup directories use mode 0700 and new dump/checksum files use 0600 (`umask 077`). Existing directories and old backups require a separate permission review. Copy backups off the application host, encrypt them at rest, restrict access, and regularly test restores against a separate staging database. A same-host backup is not a disaster-recovery copy.

Restore is destructive. First verify that the selected dump is the intended recovery point and that current users are stopped. The script validates the SHA-256 file, prompts for the exact word `RESTORE`, then stops Nginx/API/worker/beat/setup and invokes `pg_restore --single-transaction`. Review and quarantine pending Redis jobs from the old database state before restarting workers; the script does not purge queues automatically:

```sh
deploy/restore-postgres.sh --confirm /absolute/path/to/tcm-platform-TIMESTAMP.dump
```

After a successful restore, inspect database and service logs, confirm user/data permissions and representative records, then start the services again:

```sh
docker compose --env-file .env.production -f deploy/compose.production.yml up -d
```

This procedure restores PostgreSQL only. Restore S3 object data with the storage provider's versioning/replication or backup tooling before reopening service if those objects are part of the recovery point.

## Current validation boundary

On 2026-10-20, both database test suites passed, and a real local Nginx → Gunicorn → Django → isolated PostgreSQL chain passed TLS, permission, cache, rate-limit and bounded concurrent-read checks. The certificate was self-signed for a local test domain. Earlier isolated PostgreSQL backup/restore also passed. Four fake-Docker shell tests cover private backup permissions, failed-dump cleanup, restore confirmation and stop/transaction arguments; they do not execute the production restore command against a database. See `docs/framework-audit-2026-10-20.md` for versions, measurements and remaining dependency notices.

Container image builds and the full production Compose lifecycle, public DNS/certificate renewal, real SMTP, private S3 and production-sized workloads remain unverified. Local native binaries and synthetic fixtures cannot substitute for these staging checks. Keep model and external biological API validation deferred as previously agreed.
