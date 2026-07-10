from __future__ import annotations

from dataclasses import dataclass

from navi_agent.telemetry import TraceStore

from .skills import FileSkillStore


@dataclass(frozen=True, slots=True)
class SkillUsageRecord:
    name: str
    description: str
    injected_count: int
    last_injected_at: str | None = None


class SkillUsageService:
    def __init__(
        self,
        *,
        skill_store: FileSkillStore,
        trace_store: TraceStore,
    ) -> None:
        self._skill_store = skill_store
        self._trace_store = trace_store

    def summarize(self, *, trace_limit: int | None = None) -> list[SkillUsageRecord]:
        skills = self._skill_store.list()
        usage = {
            skill.name: {
                "count": 0,
                "last_injected_at": None,
            }
            for skill in skills
        }
        for trace in self._trace_store.list_traces(limit=trace_limit):
            timestamp = trace.completed_at or trace.started_at
            for skill_name in trace.injected_skill_names:
                if skill_name not in usage:
                    usage[skill_name] = {
                        "count": 0,
                        "last_injected_at": None,
                    }
                usage[skill_name]["count"] += 1
                if timestamp and (
                    usage[skill_name]["last_injected_at"] is None
                    or timestamp > usage[skill_name]["last_injected_at"]
                ):
                    usage[skill_name]["last_injected_at"] = timestamp

        descriptions = {skill.name: skill.description for skill in skills}
        records = [
            SkillUsageRecord(
                name=name,
                description=descriptions.get(name, ""),
                injected_count=int(values["count"]),
                last_injected_at=values["last_injected_at"],
            )
            for name, values in usage.items()
        ]
        return sorted(records, key=lambda record: (-record.injected_count, record.name))
