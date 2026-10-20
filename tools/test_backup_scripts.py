"""Exercise backup shell safety with a fake Docker executable, never a database."""
import hashlib
import json
import os
from pathlib import Path
import stat
import subprocess
import sys
from tempfile import TemporaryDirectory
import unittest


ROOT = Path(__file__).resolve().parents[1]


class BackupScriptTests(unittest.TestCase):
    def setUp(self):
        self.temporary = TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        (self.root / "bin").mkdir()
        self.log = self.root / "docker-calls.jsonl"
        docker = self.root / "bin/docker"
        docker.write_text(f"#!{sys.executable}\n" + '''
import json, os, sys
from pathlib import Path
with Path(os.environ["TEST_DOCKER_LOG"]).open("a") as log:
    log.write(json.dumps(sys.argv[1:])+"\\n")
command = " ".join(sys.argv[1:])
if "pg_dump" in command:
    sys.stdout.write("SYNTHETIC_BACKUP_ONLY")
    if os.environ.get("TEST_DUMP_FAIL"):
        sys.exit(2)
elif "pg_restore" in command:
    assert sys.stdin.read() == "SYNTHETIC_BACKUP_ONLY"
''')
        docker.chmod(0o700)
        environment_file = self.root / "synthetic.env"
        environment_file.write_text("SYNTHETIC_ONLY=true\n")
        self.environment = dict(os.environ, PATH=f"{self.root}/bin:{os.environ['PATH']}",
                                ENV_FILE=str(environment_file), TEST_DOCKER_LOG=str(self.log))

    def run_script(self, name, *arguments, input_text=None):
        return subprocess.run(["bash", str(ROOT / "deploy" / name), *map(str, arguments)],
                              env=self.environment, input=input_text, capture_output=True, text=True)

    def test_backup_and_checksum_are_private(self):
        output = self.root / "backups"
        result = self.run_script("backup-postgres.sh", output)
        self.assertEqual(result.returncode, 0, result.stderr)
        dump, = output.glob("*.dump")
        checksum = Path(str(dump) + ".sha256")
        self.assertEqual(stat.S_IMODE(dump.stat().st_mode), 0o600)
        self.assertEqual(stat.S_IMODE(checksum.stat().st_mode), 0o600)
        self.assertEqual(stat.S_IMODE(output.stat().st_mode), 0o700)
        self.assertIn(hashlib.sha256(dump.read_bytes()).hexdigest(), checksum.read_text())

    def test_failed_dump_leaves_no_partial_or_final_backup(self):
        self.environment["TEST_DUMP_FAIL"] = "1"
        output = self.root / "backups"
        self.assertNotEqual(self.run_script("backup-postgres.sh", output).returncode, 0)
        self.assertEqual(list(output.iterdir()), [])

    def backup(self):
        dump = self.root / "synthetic.dump"
        dump.write_text("SYNTHETIC_BACKUP_ONLY")
        Path(str(dump) + ".sha256").write_text(f"{hashlib.sha256(dump.read_bytes()).hexdigest()}  {dump.name}\n")
        return dump

    def test_restore_requires_exact_confirmation_before_touching_services(self):
        result = self.run_script("restore-postgres.sh", "--confirm", self.backup(), input_text="NO\n")
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(self.log.exists())

    def test_restore_stops_writers_and_requests_one_transaction(self):
        result = self.run_script("restore-postgres.sh", "--confirm", self.backup(), input_text="RESTORE\n")
        self.assertEqual(result.returncode, 0, result.stderr)
        calls = [json.loads(line) for line in self.log.read_text().splitlines()]
        self.assertEqual(calls[0][-6:], ["stop", "nginx", "api", "worker", "beat", "setup"])
        self.assertIn("--profile", calls[0])
        self.assertIn("--single-transaction", calls[1][-1])


if __name__ == "__main__":
    unittest.main()
