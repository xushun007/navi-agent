from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime, timedelta
import json
import os
from pathlib import Path
from typing import Protocol
from uuid import uuid4


@dataclass(slots=True)
class CronJob:
    id: str
    prompt: str
    user_id: str
    session_id: str
    schedule_type: str
    enabled: bool = True
    cron: str | None = None
    run_at: str | None = None
    next_run_at: str | None = None
    last_run_at: str | None = None
    created_at: str = field(default_factory=lambda: _now().isoformat(timespec="seconds"))


@dataclass(slots=True)
class CronRunRecord:
    job_id: str
    session_id: str
    status: str
    final_response: str
    ran_at: str


class CronJobStore:
    def __init__(self, path: Path) -> None:
        self.path = path

    def list_jobs(self) -> list[CronJob]:
        if not self.path.exists():
            return []
        payload = json.loads(self.path.read_text(encoding="utf-8") or "[]")
        return [CronJob(**item) for item in payload]

    def write_jobs(self, jobs: list[CronJob]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(
            json.dumps([asdict(job) for job in jobs], ensure_ascii=False, indent=2, sort_keys=True),
            encoding="utf-8",
        )

    def add(self, job: CronJob) -> CronJob:
        jobs = self.list_jobs()
        jobs.append(job)
        self.write_jobs(jobs)
        return job

    def update(self, job: CronJob) -> None:
        jobs = [job if existing.id == job.id else existing for existing in self.list_jobs()]
        self.write_jobs(jobs)

    def cancel(self, job_id: str) -> CronJob | None:
        jobs = self.list_jobs()
        target = None
        for job in jobs:
            if job.id == job_id:
                job.enabled = False
                target = job
                break
        if target is None:
            return None
        self.write_jobs(jobs)
        return target



class AgentApp(Protocol):
    def handle(self, request): ...


class CronTickLock:
    def __init__(self, path: Path) -> None:
        self._path = path
        self._handle = None

    def __enter__(self) -> bool:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._handle = self._path.open("w", encoding="utf-8")
        try:
            if os.name == "posix":
                import fcntl

                fcntl.flock(self._handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            return True
        except BlockingIOError:
            self._handle.close()
            self._handle = None
            return False

    def __exit__(self, exc_type, exc, tb) -> None:
        if self._handle is None:
            return
        if os.name == "posix":
            import fcntl

            fcntl.flock(self._handle.fileno(), fcntl.LOCK_UN)
        self._handle.close()
        self._handle = None


class CronSchedulerService:
    def __init__(self, store: CronJobStore, lock_path: Path | None = None) -> None:
        self._store = store
        self._lock_path = lock_path

    def create_once(
        self,
        *,
        prompt: str,
        user_id: str,
        session_id: str,
        run_at: datetime,
    ) -> CronJob:
        job = CronJob(
            id=uuid4().hex[:12],
            prompt=prompt,
            user_id=user_id,
            session_id=session_id,
            schedule_type="once",
            run_at=_normalize(run_at).isoformat(timespec="seconds"),
            next_run_at=_normalize(run_at).isoformat(timespec="seconds"),
        )
        return self._store.add(job)

    def create_cron(
        self,
        *,
        prompt: str,
        user_id: str,
        session_id: str,
        cron: str,
        now: datetime | None = None,
    ) -> CronJob:
        next_run_at = next_cron_run(cron, after=now or _now())
        job = CronJob(
            id=uuid4().hex[:12],
            prompt=prompt,
            user_id=user_id,
            session_id=session_id,
            schedule_type="cron",
            cron=cron,
            next_run_at=next_run_at.isoformat(timespec="seconds"),
        )
        return self._store.add(job)

    def list_jobs(self) -> list[CronJob]:
        return self._store.list_jobs()

    def cancel(self, job_id: str) -> CronJob | None:
        return self._store.cancel(job_id)

    def run_due(
        self,
        *,
        app: AgentApp,
        now: datetime | None = None,
    ) -> list[CronRunRecord]:
        if self._lock_path is not None:
            with CronTickLock(self._lock_path) as acquired:
                if not acquired:
                    return []
                return self._run_due_unlocked(app=app, now=now)
        return self._run_due_unlocked(app=app, now=now)

    def _run_due_unlocked(
        self,
        *,
        app: AgentApp,
        now: datetime | None = None,
    ) -> list[CronRunRecord]:
        now = _normalize(now or _now())
        jobs = self._store.list_jobs()
        records: list[CronRunRecord] = []
        for job in jobs:
            if not _is_due(job, now):
                continue
            from navi_agent.app import AppRequest

            result = app.handle(
                AppRequest(
                    user_id=job.user_id,
                    session_id=job.session_id,
                    message=job.prompt,
                )
            )
            ran_at = now.isoformat(timespec="seconds")
            job.last_run_at = ran_at
            records.append(
                CronRunRecord(
                    job_id=job.id,
                    session_id=job.session_id,
                    status=result.status,
                    final_response=result.final_response,
                    ran_at=ran_at,
                )
            )
            if job.schedule_type == "once":
                job.enabled = False
                job.next_run_at = None
            elif job.schedule_type == "cron" and job.cron:
                job.next_run_at = next_cron_run(job.cron, after=now).isoformat(timespec="seconds")
        self._store.write_jobs(jobs)
        return records


def next_cron_run(expression: str, *, after: datetime) -> datetime:
    fields = expression.split()
    if len(fields) != 5:
        raise ValueError("cron expression must have five fields: minute hour day month weekday")
    minute_values = _parse_field(fields[0], 0, 59)
    hour_values = _parse_field(fields[1], 0, 23)
    day_values = _parse_field(fields[2], 1, 31)
    month_values = _parse_field(fields[3], 1, 12)
    weekday_values = {0 if value == 7 else value for value in _parse_field(fields[4], 0, 7)}
    candidate = (_normalize(after) + timedelta(minutes=1)).replace(second=0, microsecond=0)
    deadline = candidate + timedelta(days=366)
    while candidate <= deadline:
        if (
            candidate.minute in minute_values
            and candidate.hour in hour_values
            and candidate.day in day_values
            and candidate.month in month_values
            and _cron_weekday(candidate) in weekday_values
        ):
            return candidate
        candidate += timedelta(minutes=1)
    raise ValueError("cron expression has no run time within 366 days")


def _cron_weekday(value: datetime) -> int:
    return (value.weekday() + 1) % 7


def parse_run_at(value: str) -> datetime:
    text = value.strip()
    if not text:
        raise ValueError("run_at is required")
    if text.endswith("Z"):
        text = f"{text[:-1]}+00:00"
    return _normalize(datetime.fromisoformat(text))


def _parse_field(raw: str, minimum: int, maximum: int) -> set[int]:
    values: set[int] = set()
    for part in raw.split(","):
        part = part.strip()
        if not part:
            raise ValueError("empty cron field")
        if part == "*":
            values.update(range(minimum, maximum + 1))
            continue
        if part.startswith("*/"):
            step = int(part[2:])
            if step <= 0:
                raise ValueError("cron step must be positive")
            values.update(range(minimum, maximum + 1, step))
            continue
        value = int(part)
        if value < minimum or value > maximum:
            raise ValueError(f"cron value out of range: {value}")
        values.add(value)
    return values


def _is_due(job: CronJob, now: datetime) -> bool:
    if not job.enabled or not job.next_run_at:
        return False
    return parse_run_at(job.next_run_at) <= now


def _normalize(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _now() -> datetime:
    return datetime.now(UTC)
