"""Exercise current -> baseline -> current code against ONE isolated migrated DB.

No checkout, production DB, Redis or paid provider is used. The output directory
must be new. Each code version runs in a fresh process to avoid import leakage.
"""
import argparse
import io
import json
from pathlib import Path
import subprocess
import sys
import zipfile


CHILD = r'''
import json, sys
from pathlib import Path
backend, root, phase = Path(sys.argv[1]), Path(sys.argv[2]), sys.argv[3]
sys.path.insert(0, str(backend))
from tests import conftest  # Forces Mock and clears API key environment variables.
import requests
def blocked(*args, **kwargs):
    raise AssertionError("Outbound HTTP is forbidden in rollback verification")
requests.Session.send = blocked
from app import create_app
from app.extensions import db
from app.models import Job, Artifact
from app.services.job_run_service import JobRunService
from tests import helpers as h
from flask_migrate import stamp, upgrade
app = create_app('testing', config_overrides={
    'SQLALCHEMY_DATABASE_URI': 'sqlite:///' + (root / 'rollback.db').as_posix(),
    'SQLALCHEMY_ENGINE_OPTIONS': {'connect_args': {'timeout': 30}},
    'STORAGE_ROOT': str(root / 'storage'), 'UPLOAD_FOLDER': str(root / 'storage/uploads'),
    'AUTO_REPAIR_SCHEMA': False, 'MQ_ENABLED': phase != 'baseline',
    'MQ_WORKER_ACTIVE': True, 'WORKFLOW_MAX_PARALLEL_NODES': 1,
    'MODEL_ADAPTER_MODE': 'mock', 'VIDEO_COMPRESSION_ENABLED': False,
    'FAILURE_AGENT_ENABLED': False, 'FACTORY_PROMPTS_DIR': str(backend.parent / 'factory_prompts'),
})
with app.app_context():
    if phase in {'baseline', 'restored'}:
        # Exercise each version's actual migration startup, not just its ORM.
        upgrade(directory=str(backend / 'migrations'))
    if phase == 'initial':
        upgrade(directory=str(backend / 'migrations'))
        seeded = app.test_cli_runner().invoke(args=['seed-defaults'])
        assert seeded.exit_code == 0, seeded.output
    source = root / 'source.mp4'
    source.write_bytes(b'Mock source media')
    job = h.make_job(source)
    if phase == 'baseline':
        JobRunService.run_inline(job.job_id)
    else:
        from app.models import JobDispatch, TaskOutbox
        from app.queue.dispatch import dispatch_once
        from app.queue.execution import process_event
        from app.utils.time_utils import utc_now
        JobRunService.start(job.job_id, 'run_full')
        for _ in range(60):
            JobDispatch.query.filter_by(status='ready').update({'available_at': utc_now()})
            TaskOutbox.query.filter_by(consumed_at=None).update({'available_at': utc_now()})
            db.session.commit()
            dispatch_once()
            for event_id in [row.id for row in TaskOutbox.query.filter_by(consumed_at=None).all()]:
                process_event(event_id)
            if h.reload_job(job.job_id).status in h.TERMINAL_STATUSES:
                break
        assert JobDispatch.query.filter_by(status='ready').count() == 0
    assert h.reload_job(job.job_id).status == 'success'
    for artifact in Artifact.query.filter_by(artifact_type='i2v_video').all():
        assert (root / 'storage' / artifact.file_path).is_file()
    if phase == 'initial':
        # Drained schema is additive/backward-compatible. Only move the Alembic
        # marker so the baseline entrypoint can recognize its installed revision.
        stamp(directory=str(backend / 'migrations'), revision='20261016_001')
    print(json.dumps({'phase': phase, 'success_jobs': Job.query.filter_by(status='success').count(),
                      'videos': Artifact.query.filter_by(artifact_type='i2v_video').count()}))
    db.session.remove()
    db.engine.dispose()
'''


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True)
    parser.add_argument("--baseline", default="214ce686384f45ad6bc7991d756d69cfeece102d")
    args = parser.parse_args()
    root = Path(args.output).resolve()
    root.mkdir(parents=True, exist_ok=False)
    repo = Path(__file__).resolve().parents[2]
    archive = subprocess.check_output(["git", "archive", "--format=zip", args.baseline, "backend", "factory_prompts"], cwd=repo)
    baseline = root / "baseline"
    with zipfile.ZipFile(io.BytesIO(archive)) as bundle:
        for name in bundle.namelist():
            if not (baseline / name).resolve().is_relative_to(baseline.resolve()):
                raise ValueError("Unsafe archive path")
        bundle.extractall(baseline)
    results = []
    for phase, backend in (("initial", repo / "backend"), ("baseline", baseline / "backend"), ("restored", repo / "backend")):
        result = subprocess.run([sys.executable, "-c", CHILD, str(backend), str(root), phase], cwd=repo,
                                capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=180)
        (root / f"{phase}.log").write_text(result.stdout + result.stderr, encoding="utf-8")
        if result.returncode:
            raise RuntimeError(f"{phase} failed; inspect {root / (phase + '.log')}")
        results.append(json.loads(result.stdout.strip().splitlines()[-1]))
    assert [row["videos"] for row in results] == [1, 2, 3]
    (root / "report.json").write_text(json.dumps({"baseline": args.baseline, "results": results}, indent=2), encoding="utf-8")
    print(json.dumps(results))


if __name__ == "__main__":
    main()
