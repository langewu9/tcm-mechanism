# Django API

`python_app/` contains the platform API, authentication and permissions, Django Admin, knowledge catalogue, research workspaces and background analysis tasks.

## Run the local platform

On Windows, use the repository root `start-all-services.cmd` to start the original SQLite database stack, R renderer, task workers and Vite frontend. See [the Windows startup guide](../docs/Windows启动手册.md) and [the original database Docker guide](../docs/原数据库Docker启动说明.md).

For isolated PostgreSQL development, use `deploy/compose.python.yml`. It has a separate database volume and is not the local original-database configuration. Production deployment is documented in `deploy/README-production.md`.

## Data boundaries

- The original business database is `python_app/var/qa.sqlite3`; local startup checks it before bringing up services.
- The case research corpus is a separate database under `python_app/var/case-rag/` and is not written into the business database.
- Approved SQLite source files are mounted read-only from `var/source-databases/` and managed from the React `/admin/sources` page.
- User uploads and generated analysis artifacts remain private and are served through Django permission checks.

## Local development

From this directory, create an environment using `requirements.txt`, copy `.env.example` to `.env`, and configure a development database URL. Start PostgreSQL and Redis with `docker compose -f ../deploy/compose.python.yml up -d postgres redis`, then run:

```bash
python manage.py migrate
python manage.py runserver 127.0.0.1:8020
```

Run background analysis separately with `celery -A config worker --loglevel=INFO` when needed. The API schema and interactive documentation are available at `/api/schema/` and `/api/docs/` to authorized users.

## Checks

```bash
python manage.py check
python manage.py makemigrations --check --dry-run
python manage.py test
```
