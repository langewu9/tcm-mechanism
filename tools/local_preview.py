"""Start one localhost development service using existing project dependencies.

Run each service in a separate terminal with python_app/.venv/bin/python.
This helper does not install packages, initialize data, or start external calls.
"""
import argparse
import os
from pathlib import Path
import shutil
import sys

import environ


ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "python_app"
RUNTIME = APP / "var/local-runtime"


def execute(command, cwd):
    executable = Path(command[0])
    if not executable.is_file():
        raise SystemExit(f"Missing local dependency: {executable}")
    os.chdir(cwd)
    os.execv(str(executable), [str(arg) for arg in command])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("service", choices=["api", "web", "redis", "worker", "r"])
    role = parser.parse_args().service
    if not (APP / ".env").is_file():
        raise SystemExit("Configure python_app/.env for local development first.")
    environ.Env.read_env(APP / ".env", overwrite=False)
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
    if role == "api":
        execute([sys.executable, APP / "manage.py", "runserver", "127.0.0.1:8020", "--noreload"], APP)
    elif role == "web":
        node = shutil.which("node") or str(Path.home() / ".cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node")
        execute([node, ROOT / "web/node_modules/vite/bin/vite.js", "--host", "127.0.0.1", "--port", "5173", "--strictPort"], ROOT / "web")
    elif role == "redis":
        directory = RUNTIME / "redis"
        directory.mkdir(parents=True, exist_ok=True)
        os.environ["LD_LIBRARY_PATH"] = str(RUNTIME / "root/usr/lib/x86_64-linux-gnu")
        server = shutil.which("redis-server") or str(RUNTIME / "root/usr/bin/redis-server")
        execute([server, "--bind", "127.0.0.1", "--port", "6389", "--protected-mode", "yes", "--appendonly", "yes", "--dir", directory, "--save", ""], APP)
    elif role == "worker":
        execute([APP / ".venv/bin/celery", "-A", "config", "worker", "--loglevel=INFO", "--pool=solo", "--concurrency=1", "--queues=celery,r_visualization", "--hostname=local-preview@%h"], APP)
    else:
        if not os.environ.get("R_VIZ_API_TOKEN"):
            raise SystemExit("Configure R_VIZ_API_TOKEN in python_app/.env first.")
        r_home = RUNTIME / "root/usr/lib/R"
        if r_home.is_dir():
            os.environ.update(
                R_HOME=str(r_home), R_LIBS_SITE=str(r_home / "site-library"),
                LD_LIBRARY_PATH=":".join(str(path) for path in [r_home / "lib", RUNTIME / "root/usr/lib/x86_64-linux-gnu", RUNTIME / "root/usr/lib/x86_64-linux-gnu/blas", RUNTIME / "root/usr/lib/x86_64-linux-gnu/lapack"]),
                XDG_CACHE_HOME=str(RUNTIME / "cache"),
            )
            program = r_home / "bin/exec/R"
        else:
            program = shutil.which("Rscript") or "Rscript"
        execute([program, "--vanilla", "--slave", "-e", "plumber::pr_run(plumber::pr('plumber.R'), host='127.0.0.1', port=8001)"], ROOT / "r_viz")


if __name__ == "__main__":
    main()
