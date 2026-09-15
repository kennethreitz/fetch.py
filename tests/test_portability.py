"""The copy-in contract: no installed packages or import-name assumptions."""

import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        body = b'{"portable":true}'
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass


class PortabilityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.url = f"http://127.0.0.1:{cls.server.server_port}"

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join()

    def test_copy_without_site_packages(self):
        source = Path(__file__).resolve().parents[1] / "fetch.py"
        for module in ("fetch", "myapp.vendor.fetch"):
            with self.subTest(module=module), tempfile.TemporaryDirectory() as tmp:
                target = Path(tmp)
                for part in module.split(".")[:-1]:
                    target /= part
                    target.mkdir()
                    (target / "__init__.py").touch()
                shutil.copyfile(source, target / "fetch.py")
                program = """
import importlib, json, logging, socket, sys
from unittest.mock import patch

root = logging.getLogger()
handlers, level = list(root.handlers), root.level
with patch.object(socket, "create_connection", side_effect=AssertionError("network on import")):
    fetch = importlib.import_module(sys.argv[1])
assert list(root.handlers) == handlers and root.level == level
assert "pydantic" not in sys.modules
records = []
class Capture(logging.Handler):
    def emit(self, record):
        records.append(record)
logger = logging.getLogger(sys.argv[1])
logger.addHandler(Capture())
logger.setLevel(logging.DEBUG)
response = fetch.get(sys.argv[2], timeout=2)
assert response.parse(json.loads) == {"portable": True}
assert [r.fetch_event for r in records] == ["request.started", "request.completed"]
assert all(r.name == sys.argv[1] for r in records)
with fetch.Session(timeout=2) as session:
    assert session.get(sys.argv[2]).parse(json.loads) == {"portable": True}
assert session.closed
print(json.dumps({"status": response.status, "version": fetch.__version__}))
"""
                env = {
                    key: value for key, value in os.environ.items() if not key.startswith("PYTHON")
                }
                result = subprocess.run(
                    [sys.executable, "-S", "-B", "-c", program, module, self.url],
                    cwd=tmp,
                    env=env,
                    text=True,
                    capture_output=True,
                    check=False,
                    timeout=10,
                )
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(result.stderr, "")
                self.assertEqual(json.loads(result.stdout)["status"], 200)


if __name__ == "__main__":
    unittest.main()
