"""At-least-once transport. A lost Redis database is rebuilt from unconsumed SQL events."""
from datetime import timedelta
import os
import socket

from flask import current_app
from redis import Redis
from redis.exceptions import ResponseError
from sqlalchemy import or_

from app.extensions import db
from app.models import TaskOutbox
from app.queue.state import seconds
from app.utils.ids import new_id
from app.utils.time_utils import utc_now

PHASES = ("submit", "poll", "download")
GROUP = "cinecrew-executors"


class Streams:
    def __init__(self, client=None):
        self.client = client or Redis.from_url(current_app.config["REDIS_URL"], decode_responses=True,
                                              socket_connect_timeout=5, socket_timeout=5)
        self.consumer = f"{socket.gethostname()}:{os.getpid()}:{new_id('consumer')}"
        self.cursors = {phase: "0-0" for phase in PHASES}

    @staticmethod
    def stream(phase):
        return f"avf:task:{phase}"

    def ensure_groups(self):
        for phase in PHASES:
            try:
                self.client.xgroup_create(self.stream(phase), GROUP, id="0-0", mkstream=True)
            except ResponseError as error:
                if "BUSYGROUP" not in str(error):
                    raise

    def publish(self, limit=50):
        now = utc_now()
        due = TaskOutbox.query.filter(
            TaskOutbox.consumed_at.is_(None), TaskOutbox.available_at <= now,
            or_(TaskOutbox.published_at.is_(None), TaskOutbox.published_at < now - timedelta(seconds=60)),
            or_(TaskOutbox.lease_until.is_(None), TaskOutbox.lease_until < now),
        ).order_by(TaskOutbox.id).limit(limit).all()
        ids = [row.id for row in due]
        db.session.commit()
        for event_id in ids:
            token = new_id("publish")
            won = TaskOutbox.query.filter(TaskOutbox.id == event_id,
                or_(TaskOutbox.lease_until.is_(None), TaskOutbox.lease_until < now)
            ).update({"lease_token": token, "lease_until": now + timedelta(seconds=30)}, synchronize_session=False)
            db.session.commit()
            if not won:
                continue
            event = db.session.get(TaskOutbox, event_id)
            phase = event.phase
            db.session.commit()
            try:
                self.client.xadd(self.stream(phase), {"event_id": str(event_id)})
            except Exception as error:
                TaskOutbox.query.filter_by(id=event_id, lease_token=token).update({
                    "last_error": type(error).__name__, "attempts": TaskOutbox.attempts + 1,
                    "lease_token": None, "lease_until": None}, synchronize_session=False)
                db.session.commit()
                raise
            TaskOutbox.query.filter_by(id=event_id, lease_token=token).update({
                "published_at": utc_now(), "attempts": TaskOutbox.attempts + 1,
                "last_error": None, "lease_token": None, "lease_until": None}, synchronize_session=False)
            db.session.commit()
        return len(ids)

    def consume(self, phase, handler):
        stream = self.stream(phase)
        claimed = self.client.xautoclaim(stream, GROUP, self.consumer,
            min_idle_time=seconds("MQ_RECLAIM_SEC", 60) * 1000,
            start_id=self.cursors[phase], count=10)
        self.cursors[phase] = claimed[0]
        messages = claimed[1]
        if not messages:
            batches = self.client.xreadgroup(GROUP, self.consumer, {stream: ">"}, count=1)
            messages = batches[0][1] if batches else []
        for message_id, fields in messages:
            # Any DB/handler exception leaves the message pending for recovery.
            handler(int(fields["event_id"]), phase)
            self.client.xack(stream, GROUP, message_id)
            # This application owns one consumer group. Delete only the ACKed message.
            self.client.xdel(stream, message_id)
        return len(messages)
