"""Check launcher queue coverage without reading profiles or starting services."""
import ast
import importlib.util
import os
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

from celery import Celery


ROOT = Path(__file__).resolve().parents[1]


def load_launcher(name):
    spec = importlib.util.spec_from_file_location(f"queue_test_{name}", ROOT / "tools" / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def configured_routes():
    # Inspect the public constant; importing Django settings would load .env.
    tree = ast.parse((ROOT / "python_app/config/settings.py").read_text())
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(
            isinstance(target, ast.Name) and target.id == "CELERY_TASK_ROUTES" for target in node.targets
        ):
            return ast.literal_eval(node.value)
    raise AssertionError("CELERY_TASK_ROUTES is missing")


class WorkerQueueTests(unittest.TestCase):
    def assert_routes_consumed(self, command):
        command = [str(argument) for argument in command]
        self.assertIn("worker", command)
        queues = next(argument.split("=", 1)[1] for argument in command if argument.startswith("--queues="))
        subscribed = set(queues.split(","))
        app = Celery("launcher_queue_test", broker="memory://")
        try:
            app.conf.task_routes = configured_routes()
            router = app.amqp.Router()
            default_queue = router.route({}, "core.complete_evidence")["queue"].name
            render_queue = router.route({}, "core.render_visualization")["queue"].name
            self.assertEqual(default_queue, "celery")
            self.assertEqual(render_queue, "r_visualization")
            self.assertEqual(subscribed, {default_queue, render_queue})
        finally:
            app.close()

    def test_postgres_worker_consumes_default_and_render_routes(self):
        launcher = load_launcher("postgres_acceptance")
        with patch.dict(os.environ, {}, clear=True), patch.object(sys, "argv", ["postgres_acceptance.py", "worker"]), \
                patch.object(launcher, "environment", return_value={}) as environment, \
                patch.object(launcher, "execute") as execute:
            launcher.main()
        environment.assert_called_once_with()
        execute.assert_called_once()
        command = execute.call_args.args[0]
        self.assertIn("--pool=prefork", command)
        self.assertIn("--concurrency=1", command)
        self.assertIn("--hostname=pg-acceptance@%h", command)
        self.assert_routes_consumed(command)

    def test_preview_worker_consumes_default_and_render_routes(self):
        launcher = load_launcher("local_preview")
        with patch.dict(os.environ, {}, clear=True), patch.object(sys, "argv", ["local_preview.py", "worker"]), \
                patch.object(launcher.Path, "is_file", return_value=True), \
                patch.object(launcher.environ.Env, "read_env") as read_env, \
                patch.object(launcher, "execute") as execute:
            launcher.main()
        read_env.assert_called_once()
        execute.assert_called_once()
        command = execute.call_args.args[0]
        self.assertIn("--pool=solo", command)
        self.assertIn("--concurrency=1", command)
        self.assertIn("--hostname=local-preview@%h", command)
        self.assert_routes_consumed(command)


if __name__ == "__main__":
    unittest.main()
