"""Run the offline acceptance suite and write a machine-readable report.

Requires development test dependencies and FFmpeg (PATH or FFMPEG_BINARY).
No application is created before tests pin isolated databases and block HTTP.
"""
import argparse
import json
import os
from pathlib import Path
import shutil
import sys
from datetime import datetime, timezone

import pytest


class Report:
    def __init__(self):
        self.tests = []
        self.evaluations = []

    def pytest_runtest_logreport(self, report):
        if report.when == "call" or report.failed:
            self.tests.append({"test": report.nodeid, "stage": report.when, "outcome": report.outcome,
                               "seconds": report.duration, "failure": str(report.longrepr) if report.failed else None})
            self.evaluations.extend(value for key, value in report.user_properties if key == "evaluation")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True, help="New report directory; must not exist")
    args = parser.parse_args()
    if not (os.environ.get("FFMPEG_BINARY") or shutil.which("ffmpeg")):
        parser.error("FFmpeg must be available for real local media regression tests")
    root = Path(__file__).resolve().parents[2]
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    plugin = Report()
    started = datetime.now(timezone.utc).isoformat()
    code = pytest.main([str(root / "backend/tests"), "-q", "--tb=short", f"--basetemp={output / 'fixtures'}"], plugins=[plugin])
    report = {"started_at": started, "finished_at": datetime.now(timezone.utc).isoformat(),
              "exit_code": int(code), "provider_mode": "mock_or_injected_fake", "paid_tests": False,
              "test_isolation": "tests/conftest.py pins isolated DB/storage and blocks requests.Session.send",
              "tests": plugin.tests, "evaluations": plugin.evaluations,
              "limits": ["No real provider quality, latency or billing measurement", "No Redis or production deployment",
                         "Single Creative baseline uses a fixed brief; quality and real planning correctness are not measured"]}
    (output / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return int(code)


if __name__ == "__main__":
    sys.exit(main())
