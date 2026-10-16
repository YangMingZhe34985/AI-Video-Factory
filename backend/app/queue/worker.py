import time

from flask import current_app

from app.extensions import db
from app.queue.dispatch import dispatch_once
from app.queue.execution import process_event, recover_expired
from app.queue.transport import PHASES, Streams


def run_worker(role="all", once=False):
    current_app.config.update(MQ_WORKER_ACTIVE=True, FAILURE_AGENT_ENABLED=False, FAILURE_AGENT_ON_ERROR=False)
    streams = Streams()
    while True:
        try:
            streams.ensure_groups()
            if role in {"all", "scheduler"}:
                recover_expired()
                dispatch_once()
                streams.publish()
            for phase in PHASES if role == "all" else ([role] if role in PHASES else []):
                streams.consume(phase, process_event)
        except Exception:
            db.session.rollback()
            current_app.logger.exception("MQ worker iteration failed; committed work remains recoverable")
            if once:
                raise
        finally:
            db.session.remove()
        if once:
            return
        time.sleep(1)
