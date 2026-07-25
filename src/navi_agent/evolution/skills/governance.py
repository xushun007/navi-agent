from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
import json
from pathlib import Path
import shutil
from typing import Protocol
from uuid import uuid4

from .store import FileSkillStore, SkillAttachment, SkillRecord, append_to_markdown_section


@dataclass(frozen=True, slots=True)
class SkillDraftProvenance:
    review_run_id: str
    source_session_id: str
    source_trace_id: str
    evidence_ids: tuple[str, ...] = ()


@dataclass(slots=True)
class SkillDraft:
    draft_id: str
    skill_name: str
    operation: str
    status: str
    created_at: str
    provenance: SkillDraftProvenance
    previous_version_id: str = ""
    active_version_id: str = ""
    decision_reason: str = ""
    evaluation_suites: list[str] = field(default_factory=list)


@dataclass(frozen=True, slots=True)
class SkillEvaluationResult:
    suite: str
    passed: bool
    baseline_score: float
    draft_score: float
    reason: str = ""


class SkillDraftEvaluator(Protocol):
    def evaluate(
        self,
        draft: SkillDraft,
        proposed: SkillRecord,
        active: SkillRecord | None,
    ) -> list[SkillEvaluationResult]: ...


@dataclass(frozen=True, slots=True)
class SkillPromotionGate:
    required_suites: tuple[str, ...]
    minimum_score_delta: float = 0.0


class DefaultSkillDraftEvaluator:
    def evaluate(
        self,
        draft: SkillDraft,
        proposed: SkillRecord,
        active: SkillRecord | None,
    ) -> list[SkillEvaluationResult]:
        has_structure = all(
            marker in proposed.content
            for marker in ("---", "## When To Use", "## Procedure")
        )
        targeted = SkillEvaluationResult(
            suite="draft_validation",
            passed=has_structure and bool(draft.provenance.source_trace_id),
            baseline_score=0.0,
            draft_score=1.0 if has_structure else 0.0,
            reason="draft must be structured and linked to source evidence",
        )
        active_lines = set(active.content.splitlines()) if active is not None else set()
        proposed_lines = set(proposed.content.splitlines())
        preserved = active is None or active_lines.issubset(proposed_lines)
        regression = SkillEvaluationResult(
            suite="content_regression",
            passed=preserved,
            baseline_score=1.0,
            draft_score=1.0 if preserved else 0.0,
            reason="existing skill content must be preserved",
        )
        return [targeted, regression]


class SkillGovernanceService:
    def __init__(
        self,
        skill_store: FileSkillStore,
        *,
        gate: SkillPromotionGate,
    ) -> None:
        self._skill_store = skill_store
        self._gate = gate
        self._root = skill_store.root / ".governance"

    def create_draft(
        self,
        *,
        skill_name: str,
        content: str,
        provenance: SkillDraftProvenance,
    ) -> SkillDraft:
        if self._skill_store.get(skill_name) is not None:
            raise ValueError(f"skill already exists: {skill_name}")
        draft = self._new_draft(
            skill_name=skill_name,
            operation="create",
            provenance=provenance,
        )
        self._draft_store(draft.draft_id).create(name=skill_name, content=content)
        self._save_draft(draft)
        self._record_event(draft, "draft_created")
        return draft

    def append_draft(
        self,
        *,
        skill_name: str,
        section: str,
        content: str,
        provenance: SkillDraftProvenance,
    ) -> SkillDraft:
        active = self._skill_store.get(skill_name)
        if active is None:
            raise ValueError(f"skill not found: {skill_name}")
        draft = self._new_draft(
            skill_name=skill_name,
            operation="append",
            provenance=provenance,
        )
        draft_skill_dir = self._draft_root(draft.draft_id) / skill_name
        shutil.copytree(active.path.parent, draft_skill_dir)
        updated = append_to_markdown_section(
            active.content,
            section=section,
            content=content,
        )
        (draft_skill_dir / "SKILL.md").write_text(updated, encoding="utf-8")
        self._save_draft(draft)
        self._record_event(draft, "draft_created")
        return draft

    def write_draft_attachment(
        self,
        *,
        draft_id: str,
        relative_path: str,
        content: str,
    ) -> SkillAttachment:
        draft = self.get_draft(draft_id)
        if draft is None:
            raise ValueError(f"draft not found: {draft_id}")
        if draft.status != "draft":
            raise ValueError(f"draft is not editable: {draft_id}")
        attachment = self._draft_store(draft_id).write_attachment(
            name=draft.skill_name,
            relative_path=relative_path,
            content=content,
        )
        if attachment is None:
            raise ValueError(f"draft content not found: {draft_id}")
        self._record_event(draft, "draft_attachment_written")
        return attachment

    def evaluate_and_promote(
        self,
        draft_id: str,
        *,
        evaluator: SkillDraftEvaluator,
    ) -> SkillDraft:
        draft = self._require_pending_draft(draft_id)
        proposed = self._draft_store(draft_id).get(draft.skill_name)
        if proposed is None:
            return self.reject(draft_id, reason="draft content is missing")
        active = self._skill_store.get(draft.skill_name)
        try:
            results = evaluator.evaluate(draft, proposed, active)
        except Exception as error:
            return self.reject(draft_id, reason=f"evaluation failed: {error}")

        draft.evaluation_suites = [result.suite for result in results]
        decision, reason = self._gate_decision(results)
        if decision != "promoted":
            draft.status = decision
            draft.decision_reason = reason
            self._save_draft(draft)
            self._record_event(draft, decision)
            return draft

        previous_version_id = self._ensure_active_version(draft.skill_name)
        self._save_version_from_draft(draft)
        self._replace_active(draft)
        draft.status = "promoted"
        draft.active_version_id = draft.draft_id
        draft.previous_version_id = previous_version_id
        draft.decision_reason = reason
        self._save_draft(draft)
        self._save_state(
            draft.skill_name,
            active_version_id=draft.draft_id,
            previous_version_id=previous_version_id,
        )
        self._record_event(draft, "promoted")
        return draft

    def reject(self, draft_id: str, *, reason: str) -> SkillDraft:
        draft = self._require_pending_draft(draft_id)
        draft.status = "rejected"
        draft.decision_reason = reason
        self._save_draft(draft)
        self._record_event(draft, "rejected")
        return draft

    def rollback(self, skill_name: str) -> SkillDraft:
        state = self._read_state(skill_name)
        previous_version_id = str(state.get("previous_version_id") or "")
        active_version_id = str(state.get("active_version_id") or "")
        if not previous_version_id:
            promoted = self.get_draft(active_version_id)
            if promoted is None or promoted.operation != "create":
                raise ValueError(f"no previous active version for skill: {skill_name}")
            self._skill_store.remove(skill_name)
            promoted.status = "rolled_back"
            self._save_draft(promoted)
            self._save_state(
                skill_name,
                active_version_id="",
                previous_version_id="",
            )
            self._record_event(promoted, "rolled_back")
            return promoted
        source = self._version_root(skill_name, previous_version_id) / skill_name
        if not source.exists():
            raise ValueError(f"skill version not found: {previous_version_id}")
        self._replace_skill_dir(skill_name, source)
        promoted = self.get_draft(active_version_id)
        if promoted is None:
            raise ValueError(f"active draft metadata not found: {active_version_id}")
        promoted.status = "rolled_back"
        self._save_draft(promoted)
        previous_draft = self.get_draft(previous_version_id)
        next_previous = previous_draft.previous_version_id if previous_draft else ""
        self._save_state(
            skill_name,
            active_version_id=previous_version_id,
            previous_version_id=next_previous,
        )
        self._record_event(promoted, "rolled_back")
        return promoted

    def get_draft(self, draft_id: str) -> SkillDraft | None:
        path = self._draft_metadata_path(draft_id)
        if not path.exists():
            return None
        payload = json.loads(path.read_text(encoding="utf-8"))
        provenance = SkillDraftProvenance(**payload.pop("provenance"))
        return SkillDraft(**payload, provenance=provenance)

    def list_drafts(self, *, skill_name: str | None = None) -> list[SkillDraft]:
        drafts = []
        for path in sorted(self._drafts_root.glob("*.json")):
            draft = self.get_draft(path.stem)
            if draft is not None and (skill_name is None or draft.skill_name == skill_name):
                drafts.append(draft)
        return drafts

    def _gate_decision(self, results: list[SkillEvaluationResult]) -> tuple[str, str]:
        by_suite = {result.suite: result for result in results}
        missing = [suite for suite in self._gate.required_suites if suite not in by_suite]
        if missing:
            return "rejected", f"missing required evaluation suites: {', '.join(missing)}"
        required = [by_suite[suite] for suite in self._gate.required_suites]
        failed = [result for result in required if not result.passed]
        if any(result.draft_score < result.baseline_score for result in failed):
            return "regressed", failed[0].reason or "a required evaluation regressed"
        if failed:
            return "rejected", failed[0].reason or "a required evaluation failed"
        if required and not any(
            result.draft_score - result.baseline_score > self._gate.minimum_score_delta
            for result in required
        ):
            return "no_improvement", "required evaluations did not improve"
        return "promoted", "configured promotion gate passed"

    def _new_draft(
        self,
        *,
        skill_name: str,
        operation: str,
        provenance: SkillDraftProvenance,
    ) -> SkillDraft:
        return SkillDraft(
            draft_id=uuid4().hex[:12],
            skill_name=skill_name,
            operation=operation,
            status="draft",
            created_at=datetime.now(UTC).isoformat(timespec="seconds"),
            provenance=provenance,
        )

    def _require_pending_draft(self, draft_id: str) -> SkillDraft:
        draft = self.get_draft(draft_id)
        if draft is None:
            raise ValueError(f"draft not found: {draft_id}")
        if draft.status != "draft":
            raise ValueError(f"draft already decided: {draft_id}")
        return draft

    def _ensure_active_version(self, skill_name: str) -> str:
        state = self._read_state(skill_name)
        active_version_id = str(state.get("active_version_id") or "")
        if active_version_id:
            return active_version_id
        active = self._skill_store.get(skill_name)
        if active is None:
            return ""
        version_id = f"baseline-{uuid4().hex[:8]}"
        destination = self._version_root(skill_name, version_id) / skill_name
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(active.path.parent, destination)
        return version_id

    def _save_version_from_draft(self, draft: SkillDraft) -> None:
        source = self._draft_root(draft.draft_id) / draft.skill_name
        destination = self._version_root(draft.skill_name, draft.draft_id) / draft.skill_name
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(source, destination)

    def _replace_active(self, draft: SkillDraft) -> None:
        source = self._draft_root(draft.draft_id) / draft.skill_name
        self._replace_skill_dir(draft.skill_name, source)

    def _replace_skill_dir(self, skill_name: str, source: Path) -> None:
        target = self._skill_store.root / skill_name
        temporary = self._skill_store.root / f".{skill_name}.promoting-{uuid4().hex[:8]}"
        backup = self._skill_store.root / f".{skill_name}.backup-{uuid4().hex[:8]}"
        shutil.copytree(source, temporary)
        try:
            if target.exists():
                target.rename(backup)
            temporary.rename(target)
        except Exception:
            if not target.exists() and backup.exists():
                backup.rename(target)
            raise
        finally:
            if temporary.exists():
                shutil.rmtree(temporary)
            if backup.exists():
                shutil.rmtree(backup)

    @property
    def _drafts_root(self) -> Path:
        return self._root / "drafts"

    def _draft_root(self, draft_id: str) -> Path:
        return self._drafts_root / draft_id

    def _draft_store(self, draft_id: str) -> FileSkillStore:
        return FileSkillStore(self._draft_root(draft_id))

    def _draft_metadata_path(self, draft_id: str) -> Path:
        return self._drafts_root / f"{draft_id}.json"

    def _version_root(self, skill_name: str, version_id: str) -> Path:
        return self._root / "versions" / skill_name / version_id

    def _state_path(self, skill_name: str) -> Path:
        return self._root / "state" / f"{skill_name}.json"

    def _read_state(self, skill_name: str) -> dict:
        path = self._state_path(skill_name)
        if not path.exists():
            return {}
        return json.loads(path.read_text(encoding="utf-8"))

    def _save_state(
        self,
        skill_name: str,
        *,
        active_version_id: str,
        previous_version_id: str,
    ) -> None:
        self._write_json(
            self._state_path(skill_name),
            {
                "active_version_id": active_version_id,
                "previous_version_id": previous_version_id,
            },
        )

    def _save_draft(self, draft: SkillDraft) -> None:
        self._write_json(self._draft_metadata_path(draft.draft_id), asdict(draft))

    def _record_event(self, draft: SkillDraft, action: str) -> None:
        self._root.mkdir(parents=True, exist_ok=True)
        payload = {
            "action": action,
            "timestamp": datetime.now(UTC).isoformat(timespec="seconds"),
            "draft_id": draft.draft_id,
            "skill_name": draft.skill_name,
            "status": draft.status,
            "review_run_id": draft.provenance.review_run_id,
            "source_session_id": draft.provenance.source_session_id,
            "source_trace_id": draft.provenance.source_trace_id,
            "decision_reason": draft.decision_reason,
        }
        with (self._root / "history.jsonl").open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(payload, ensure_ascii=True) + "\n")

    @staticmethod
    def _write_json(path: Path, payload: dict) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(f"{path.suffix}.tmp")
        temporary.write_text(
            json.dumps(payload, ensure_ascii=True, indent=2, sort_keys=True),
            encoding="utf-8",
        )
        temporary.replace(path)
