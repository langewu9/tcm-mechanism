# Production deployment

This Compose file is a production-oriented starting point, not a tested public deployment. It runs Django/Gunicorn, Celery, PostgreSQL, Redis, the private R renderer, and the built React/Vite UI. Only Nginx publishes host ports (80/443); PostgreSQL, Redis, Django, and R have no public host ports. The React app and API share one origin, retaining Django session/CSRF authentication.

## Before the first start

1. Provision a Linux server with Docker Engine and the Compose plugin. Point the chosen public DNS name at it and allow inbound TCP 80/443 in the firewall.
2. Provision a private S3-compatible bucket and credentials restricted to that bucket. Keep public access disabled. Configure the provider's versioning/replication and retention policy separately; the database scripts below do not back up uploaded objects.
3. Copy `.env.production.example` to `.env.production`, generate unique random values for all secrets, and enter the DNS name and object-storage settings. Keep `.env.production` out of version control and restrict its filesystem permissions (`chmod 600 .env.production`). Hex-only PostgreSQL and Redis passwords avoid URL-escaping issues in the internal connection strings.
4. Obtain a valid TLS certificate for the domain and install its full chain as `deploy/certs/fullchain.pem` and its private key as `deploy/certs/privkey.pem`. Keep the private key out of Git and restrict its permissions. Renew the certificate using the chosen certificate authority; reload Nginx after renewal.

Example secret generation on Linux:

```sh
openssl rand -hex 32
python3 -c 'import secrets; print(secrets.token_urlsafe(64))'
```

## Start and operate

Run from the repository root:

```sh
docker compose --env-file .env.production -f deploy/compose.production.yml config --quiet
docker compose --env-file .env.production -f deploy/compose.production.yml build
docker compose --env-file .env.production -f deploy/compose.production.yml up -d
docker compose --env-file .env.production -f deploy/compose.production.yml ps
docker compose --env-file .env.production -f deploy/compose.production.yml exec api python manage.py createsuperuser
```

The Django container applies migrations and collects static files before starting Gunicorn. Nginx waits until the API health check succeeds. Create the first administrator with `createsuperuser`. Researcher registration creates an inactive account application; a platform administrator must review the applicant and enable the account in Django Admin before the researcher can sign in. Registration is CSRF-protected and rate-limited by both Django and Nginx. Email ownership verification and approval notifications are not configured yet, so review applicant email addresses through your own approved process before activation. Inspect `docker compose ... logs api worker nginx` for failures. To update, build the new image and run `up -d`; take a verified backup before schema-changing releases.

The Django object-storage adapter uses a private S3-compatible bucket and streams files through permission-checked Django endpoints. It does not publish direct public object URLs. The R service is reachable only over its internal network. Uploaded research files still need a retention, deletion, and restore policy appropriate to their sensitivity. When moving an existing deployment from local `MEDIA_ROOT` to S3, copy every referenced object while preserving its storage key, compare stored checksums, and only then switch the application setting; the Compose file does not migrate local files automatically.

## Database backup and restore

Create a timestamped PostgreSQL custom-format dump and SHA-256 file:

```sh
deploy/backup-postgres.sh
```

The default output directory is `backups/`; pass another directory as the first argument when needed. Copy backups off the application host, encrypt them at rest, restrict access, and regularly test restores against a separate staging database. A same-host backup is not a disaster-recovery copy.

Restore is destructive. First verify that the selected dump is the intended recovery point and that current users are stopped. The script validates the SHA-256 file, stops Nginx/API/worker, then prompts for the exact word `RESTORE`:

```sh
deploy/restore-postgres.sh --confirm /absolute/path/to/tcm-platform-TIMESTAMP.dump
```

After a successful restore, inspect database and service logs, confirm user/data permissions and representative records, then start the services again:

```sh
docker compose --env-file .env.production -f deploy/compose.production.yml up -d
```

This procedure restores PostgreSQL only. Restore S3 object data with the storage provider's versioning/replication or backup tooling before reopening service if those objects are part of the recovery point.

## Current validation boundary

`docker compose ... config --quiet`, Django checks/tests, and the frontend production build can validate configuration in the development environment. Container image builds, live PostgreSQL migration, TLS termination, S3 access, R container startup, and backup/restore execution must still be exercised on a host with working Docker access and real service credentials before public launch. Do not treat this Compose file as evidence that those runtime checks have already passed.
