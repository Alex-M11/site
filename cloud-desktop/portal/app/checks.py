"""Автоперевірка зданих робіт скриптом викладача в ізольованому контейнері."""
from __future__ import annotations

import logging
import threading

from .db import db_session
from .drivers import CheckSpec, DriverError, get_driver
from .models import Submission, utcnow
from .storage import host_submission_dir, submission_dir

log = logging.getLogger("cloud_desktop.checks")
MAX_OUTPUT = 10_000
DEFAULT_IMAGE = "python:3.12-slim"
# Не більше двох перевірок одночасно, щоб здача всією групою не «поклала» сервер.
_slots = threading.BoundedSemaphore(2)

PENDING, PASSED, FAILED, ERROR = "pending", "passed", "failed", "error"


def run_check(submission_id: int) -> None:
    with _slots, db_session() as db:
        sub = db.get(Submission, submission_id)
        if sub is None or sub.check_status != PENDING:
            return
        a = sub.assignment
        if not (a.check_script or "").strip():
            sub.check_status = ""
            db.commit()
            return
        work = submission_dir(a.id, sub.student.username)
        spec = CheckSpec(image=a.check_image or DEFAULT_IMAGE, script=a.check_script.replace("\r\n", "\n"),
                         work_host_path=host_submission_dir(a.id, sub.student.username) if work.exists() else "",
                         timeout=max(5, min(a.check_timeout or 60, 600)))
        try:
            if not spec.work_host_path:
                raise DriverError("Файли роботи не знайдено")
            result = get_driver().run_check(spec)
        except (DriverError, OSError) as exc:
            log.warning("Автоперевірка %s не виконалась: %s", submission_id, exc)
            sub.check_status, sub.check_output = ERROR, f"Перевірку не вдалося запустити: {exc}"
        else:
            output = result.output[-MAX_OUTPUT:]
            if result.timed_out:
                sub.check_status = FAILED
                output += f"\n⏱ Перевищено ліміт часу ({spec.timeout} с)."
            else:
                sub.check_status = PASSED if result.exit_code == 0 else FAILED
                if result.exit_code:
                    output += f"\nКод завершення: {result.exit_code}"
            sub.check_output = output.strip()
        sub.checked_at = utcnow()
        db.commit()


def mark_pending(sub: Submission) -> bool:
    """Позначити роботу для перевірки. False — у завдання немає скрипта."""
    if not (sub.assignment.check_script or "").strip():
        sub.check_status, sub.check_output, sub.checked_at = "", "", None
        return False
    sub.check_status, sub.check_output, sub.checked_at = PENDING, "", None
    return True
