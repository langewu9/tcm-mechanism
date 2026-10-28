"""Check normalized `docker compose config --format json` from stdin."""
import json
import sys

config = json.load(sys.stdin)
services = config["services"]
for name in ("api", "worker", "r-worker", "r-viz", "redis"):
    assert name in services, f"Missing service: {name}"
for name in ("api", "worker", "r-worker"):
    service = services[name]
    env = service["environment"]
    assert env["DATABASE_URL"] == "sqlite:////app/var/qa.sqlite3", name
    assert env["SOURCE_SCHEDULED_PREVIEWS_ENABLED"] == "false", name
    mounts = {mount["target"]: mount for mount in service["volumes"]}
    assert mounts["/app/var"]["type"] == "bind", name
    assert mounts["/app/var"]["source"].replace("\\", "/").endswith("/python_app/var"), name
    assert mounts["/app/var"]["bind"]["create_host_path"] is False, name
    assert env["R_VIZ_BASE_URL"] == "http://r-viz:8001", name
    assert env["R_VIZ_API_TOKEN"] == services["r-viz"]["environment"]["R_VIZ_API_TOKEN"], name
assert "migrate --check" in " ".join(services["api"]["command"])
assert "migrate &&" not in " ".join(services["api"]["command"])
assert "--queues=celery " in " ".join(services["worker"]["command"])
assert "--queues=r_visualization " in " ".join(services["r-worker"]["command"])
assert services["r-worker"]["depends_on"]["r-viz"]["condition"] == "service_healthy"
assert "r-viz" not in services["worker"].get("depends_on", {})
assert not services["r-viz"].get("ports"), "R must not publish a host port"
assert config["networks"]["visualization"]["internal"] is True
for name in ("api", "r-worker", "r-viz"):
    assert "visualization" in services[name]["networks"], name
for name in services:
    assert services[name]["restart"] == "unless-stopped", name
print("PASS: original database binds, no auto-migration, isolated R network, matching authentication, healthy R dependency and separate task queues.")
