from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from .provenance import SkillProvenanceStore
from .governance import SkillGovernanceService
from .usage import SkillUsageRecord, SkillUsageService, SkillUsageStore


@dataclass(frozen=True, slots=True)
class SkillCuratorRecord:
    name: str
    description: str
    origin: str
    injected_count: int
    last_injected_at: str | None = None
    created_at: str | None = None
    age_days: int | None = None
    candidate_action: str = "ignore"


@dataclass(frozen=True, slots=True)
class SkillCuratorStatus:
    skill_count: int
    agent_created_count: int
    manual_count: int
    unused_agent_created_count: int
    review_unused_count: int
    records: list[SkillCuratorRecord]


@dataclass(frozen=True, slots=True)
class SkillCuratorArchiveResult:
    archived_count: int
    archived_names: list[str]
    skipped_count: int


class SkillCuratorStatusService:
    def __init__(
        self,
        *,
        usage_service: SkillUsageService,
        provenance_store: SkillProvenanceStore,
        minimum_unused_days: int = 30,
    ) -> None:
        if minimum_unused_days < 0:
            raise ValueError("minimum_unused_days must not be negative")
        self._usage_service = usage_service
        self._provenance_store = provenance_store
        self._minimum_unused_days = minimum_unused_days

    def summarize(self, *, now: datetime | None = None) -> SkillCuratorStatus:
        now = _normalize_datetime(now or datetime.now(UTC))
        records = [
            self._build_record(record, now=now)
            for record in self._usage_service.summarize()
        ]
        agent_created_count = sum(1 for record in records if record.origin == "agent")
        manual_count = sum(1 for record in records if record.origin == "manual")
        unused_agent_created_count = sum(
            1
            for record in records
            if record.origin == "agent" and record.injected_count == 0
        )
        review_unused_count = sum(
            1 for record in records if record.candidate_action == "review-unused"
        )
        return SkillCuratorStatus(
            skill_count=len(records),
            agent_created_count=agent_created_count,
            manual_count=manual_count,
            unused_agent_created_count=unused_agent_created_count,
            review_unused_count=review_unused_count,
            records=sorted(records, key=lambda record: (record.origin != "agent", -record.injected_count, record.name)),
        )

    def _build_record(self, usage: SkillUsageRecord, *, now: datetime) -> SkillCuratorRecord:
        provenance = self._provenance_store.get(usage.name)
        origin = "agent" if provenance is not None and provenance.origin == "agent" else "manual"
        created_at = provenance.created_at if provenance is not None else usage.last_created_at
        age_days = _age_days(created_at, now=now)
        return SkillCuratorRecord(
            name=usage.name,
            description=usage.description,
            origin=origin,
            injected_count=usage.injected_count,
            last_injected_at=usage.last_injected_at,
            created_at=created_at,
            age_days=age_days,
            candidate_action=_candidate_action(
                origin=origin,
                injected_count=usage.injected_count,
                age_days=age_days,
                minimum_unused_days=self._minimum_unused_days,
            ),
        )


def _candidate_action(
    *,
    origin: str,
    injected_count: int,
    age_days: int | None,
    minimum_unused_days: int,
) -> str:
    if origin != "agent":
        return "ignore"
    if injected_count == 0:
        if age_days is None or age_days < minimum_unused_days:
            return "grace-period"
        return "review-unused"
    return "keep-observe"


class SkillCuratorService:
    def __init__(
        self,
        *,
        skill_governance: SkillGovernanceService,
        usage_service: SkillUsageService,
        provenance_store: SkillProvenanceStore,
        usage_store: SkillUsageStore | None = None,
        minimum_unused_days: int = 30,
    ) -> None:
        self._skill_governance = skill_governance
        self._usage_service = usage_service
        self._provenance_store = provenance_store
        self._usage_store = usage_store
        self._minimum_unused_days = minimum_unused_days

    def archive_unused_agent_created(
        self,
        *,
        now: datetime | None = None,
    ) -> SkillCuratorArchiveResult:
        status = SkillCuratorStatusService(
            usage_service=self._usage_service,
            provenance_store=self._provenance_store,
            minimum_unused_days=self._minimum_unused_days,
        ).summarize(now=now)
        archived_names: list[str] = []
        skipped_count = 0
        for record in status.records:
            if record.candidate_action != "review-unused":
                skipped_count += 1
                continue
            archived = self._skill_governance.archive(record.name)
            if archived is None:
                skipped_count += 1
                continue
            archived_names.append(record.name)
            if self._usage_store is not None:
                self._usage_store.record_archive(record.name)
        return SkillCuratorArchiveResult(
            archived_count=len(archived_names),
            archived_names=archived_names,
            skipped_count=skipped_count,
        )


def _age_days(value: str | None, *, now: datetime) -> int | None:
    if not value:
        return None
    try:
        created_at = _normalize_datetime(datetime.fromisoformat(value))
    except ValueError:
        return None
    return max(0, (now - created_at).days)


def _normalize_datetime(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)
