"""Shared durable execution for classic workflows and Agent jobs."""


class TaskPending(Exception):
    """The node has saved work and can yield without being marked failed."""


class DispatchLost(Exception):
    """A newer scheduler owns this job; the old owner must not confirm work."""
