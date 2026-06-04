from app.extensions import db
from app.models import Job, JobEvent


class EventService:
    @staticmethod
    def record(
        job: Job,
        event_type: str,
        message: str = "",
        node_key: str | None = None,
        payload: dict | None = None,
        level: str = "info",
    ) -> JobEvent:
        event = JobEvent(
            job_id=job.id,
            event_type=event_type,
            node_key=node_key,
            message=message,
            payload=payload or {},
            level=level,
        )
        db.session.add(event)
        return event
