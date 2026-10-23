"""Parent-process failure hooks for persisted background jobs."""
import logging

from billiard.exceptions import Terminated, TimeLimitExceeded, WorkerLostError
from celery import Task
from celery.worker.request import Request


logger = logging.getLogger(__name__)


def _record_interruption(name, args, kwargs, reason):
    try:
        from django.db import close_old_connections
        from apps.core.services.task_recovery import mark_interrupted
        close_old_connections()
        mark_interrupted(name, args, kwargs, reason=reason)
    except Exception as exc:
        # If the database is unavailable, the explicit maintenance command is
        # still required. Do not include payloads or exception messages in logs.
        logger.error("Could not record background interruption task=%s error_type=%s",
                     name, type(exc).__name__)


class RecoverableRequest(Request):
    def on_failure(self, exc_info, send_failed_event=True, return_ok=False):
        exception = exc_info.exception
        exception = getattr(exception, "exc", exception)
        if isinstance(exception, (WorkerLostError, Terminated, TimeLimitExceeded)):
            reason = "hard_timeout" if isinstance(exception, TimeLimitExceeded) else "worker_lost"
            _record_interruption(self.name, self.args, self.kwargs, reason)
        return super().on_failure(exc_info, send_failed_event=send_failed_event, return_ok=return_ok)

    def on_timeout(self, soft, timeout):
        if not soft:
            _record_interruption(self.name, self.args, self.kwargs, "hard_timeout")
        return super().on_timeout(soft, timeout)


class RecoverableTask(Task):
    abstract = True
    Request = "config.background_tasks:RecoverableRequest"
    # Re-running can repeat model/external side effects. Preserve a failed
    # record instead; a researcher must explicitly create another task.
    reject_on_worker_lost = False
    acks_on_failure_or_timeout = True

    def on_failure(self, exc, task_id, args, kwargs, einfo):
        _record_interruption(self.name, args, kwargs, "worker_exception")
        return super().on_failure(exc, task_id, args, kwargs, einfo)
