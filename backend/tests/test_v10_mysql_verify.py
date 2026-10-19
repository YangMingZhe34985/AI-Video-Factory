"""Offline regression for the V10c disposable database verification harness."""
import importlib.util
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

HERE = Path(__file__).resolve().parents[1] / "scripts" / "v3_eval"
SPEC = importlib.util.spec_from_file_location("mysql_verify", HERE / "mysql_verify.py")
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class GuardTests(unittest.TestCase):
    def test_storage_rejects_temp_root_and_external_paths(self):
        root = Path(tempfile.gettempdir()).resolve()
        with self.assertRaises(ValueError):
            MODULE.require_temp(root)
        with self.assertRaises(ValueError):
            MODULE.require_temp(root.parent / "outside-v10c")
        self.assertEqual(MODULE.require_temp(root / "cinecrew-v10c-test"), root / "cinecrew-v10c-test")

    def child(self, code):
        setup = f"import sys; sys.path.insert(0, {str(HERE)!r}); import mysql_verify as m; "
        return subprocess.run([sys.executable, "-B", "-c", setup + code], capture_output=True, text=True, timeout=30)

    def test_network_guard_blocks_http_and_non_test_mysql(self):
        result = self.child("m.install_network_guard(3307, False); import socket; "
                            "s=socket.socket(); s.connect(('127.0.0.1',3306))")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("outside disposable MySQL", result.stderr)

    def test_sqlite_harness_blocks_even_designated_mysql(self):
        result = self.child("m.install_network_guard(3307, True); import socket; "
                            "s=socket.socket(); s.connect(('127.0.0.1',3307))")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("outside disposable MySQL", result.stderr)

    def test_configuration_disables_dotenv_and_overrides_inherited_services(self):
        result = self.child("from pathlib import Path; import os,dotenv; "
            "os.environ.update(DATABASE_URL='mysql://untrusted',MQ_ENABLED='true',MODEL_ADAPTER_MODE='real'); "
            "m.isolate_environment(Path('.')); "
            "assert os.environ['DATABASE_URL']=='sqlite:///:memory:'; "
            "assert os.environ['MQ_ENABLED']=='false'; assert os.environ['MODEL_ADAPTER_MODE']=='mock'; "
            "assert dotenv.load_dotenv('anything') is False; dotenv.dotenv_values('anything')")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("must never parse dotenv", result.stderr)

    def test_cli_rejects_default_port_before_connecting(self):
        result = subprocess.run([sys.executable, "-B", str(HERE / "mysql_verify.py"),
                                 "--backend", ".", "--work", ".", "--port", "3306"],
                                capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 2)
        self.assertIn("nondefault high MySQL port", result.stderr)


if __name__ == "__main__":
    unittest.main()
