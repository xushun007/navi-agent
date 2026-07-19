from __future__ import annotations

from dataclasses import dataclass

from .skill_provenance import SkillProvenanceStore
from .skill_usage import SkillUsageRecord, SkillUsageService, SkillUsageStore
from .skills import FileSkillStore


@dataclass(frozen=True, slots=True)
class SkillCuratorRecord:
    name: str
    description: str
    origin: str
    injected_count: int
    last_injected_at: str | None = None
    candidate_action: str = "ignore"


@dataclass(frozen=True, slots=True)
class SkillCuratorStatus:
    skill_count: int
    agent_created_count: int
    manual_count: int
    unused_agent_created_count: int
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
    ) -> None:
        self._usage_service = usage_service
        self._provenance_store = provenance_store

    def summarize(self) -> SkillCuratorStatus:
        records = [self._build_record(record) for record in self._usage_service.summarize()]
        agent_created_count = sum(1 for record in records if record.origin == "agent")
        manual_count = sum(1 for record in records if record.origin == "manual")
        unused_agent_created_count = sum(
            1
            for record in records
            if record.origin == "agent" and record.injected_count == 0
        )
        return SkillCuratorStatus(
            skill_count=len(records),
            agent_created_count=agent_created_count,
            manual_count=manual_count,
            unused_agent_created_count=unused_agent_created_count,
            records=sorted(records, key=lambda record: (record.origin != "agent", -record.injected_count, record.name)),
        )

    def _build_record(self, usage: SkillUsageRecord) -> SkillCuratorRecord:
        origin = "agent" if self._provenance_store.is_agent_created(usage.name) else "manual"
        return SkillCuratorRecord(
            name=usage.name,
            description=usage.description,
            origin=origin,
            injected_count=usage.injected_count,
            last_injected_at=usage.last_injected_at,
            candidate_action=_candidate_action(origin=origin, injected_count=usage.injected_count),
        )


def _candidate_action(*, origin: str, injected_count: int) -> str:
    if origin != "agent":
        return "ignore"
    if injected_count == 0:
        return "review-unused"
    return "keep-observe"


class SkillCuratorService:
    def __init__(
        self,
        *,
        skill_store: FileSkillStore,
        usage_service: SkillUsageService,
        provenance_store: SkillProvenanceStore,
        usage_store: SkillUsageStore | None = None,
    ) -> None:
        self._skill_store = skill_store
        self._usage_service = usage_service
        self._provenance_store = provenance_store
        self._usage_store = usage_store

    def archive_unused_agent_created(self) -> SkillCuratorArchiveResult:
        status = SkillCuratorStatusService(
            usage_service=self._usage_service,
            provenance_store=self._provenance_store,
        ).summarize()
        archived_names: list[str] = []
        skipped_count = 0
        for record in status.records:
            if record.origin != "agent" or record.injected_count != 0:
                skipped_count += 1
                continue
            archived = self._skill_store.archive(record.name)
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
