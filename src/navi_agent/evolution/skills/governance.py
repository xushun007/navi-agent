from __future__ import annotations

from dataclasses import asdict, dataclass, field, replace
from datetime import UTC, datetime
import difflib
import hashlib
import json
from pathlib import Path
import shutil
from typing import Protocol
from uuid import uuid4

from .store import FileSkillStore, SkillAttachment, SkillRecord, append_to_markdown_section


@dataclass(frozen=True, slots=True)
class SkillDraftProvenance:
    review_run_id: str = ""
    source_session_id: str = ""
    source_trace_id: str = ""
    evidence_ids: tuple[str, ...] = ()
    source_kind: str = "agent"
    source_uri: str = ""


@dataclass(frozen=True, slots=True)
class SkillAdmissionResult:
    check: str
    passed: bool
    reason: str = ""


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
    admission_results: list[SkillAdmissionResult] = field(default_factory=list)
    evaluation_results: list[SkillEvaluationResult] = field(default_factory=list)


@dataclass(frozen=True, slots=True)
class SkillEvaluationResult:
    suite: str
    passed: bool
    baseline_score: float
    draft_score: float
    reason: str = ""


@dataclass(frozen=True, slots=True)
class SkillVersionRecord:
    version_id: str
    skill_name: str
    parent_version_id: str
    status: str
    operation: str
    created_at: str
    content_hash: str
    provenance: SkillDraftProvenance | None = None
    evaluation_results: tuple[SkillEvaluationResult, ...] = ()
    diff_path: str = ""


class SkillAdmissionValidator(Protocol):
    def validate(
        self,
        draft: SkillDraft,
        proposed: SkillRecord,
        active: SkillRecord | None,
    ) -> list[SkillAdmissionResult]: ...


@dataclass(frozen=True, slots=True)
class SkillPromotionGate:
    required_suites: tuple[str, ...]
    minimum_score_delta: float = 0.0


class DefaultSkillAdmissionValidator:
    def validate(
        self,
        draft: SkillDraft,
        proposed: SkillRecord,
        active: SkillRecord | None,
    ) -> list[SkillAdmissionResult]:
        has_structure = all(
            marker in proposed.content
            for marker in ("---", "## When To Use", "## Procedure")
        )
        structure = SkillAdmissionResult(
            check="structure",
            passed=has_structure,
            reason="draft must include frontmatter, usage guidance, and a procedure",
        )
        source_kind = draft.provenance.source_kind
        provenance_valid = source_kind in {"agent", "human", "external", "revision"}
        if source_kind == "agent":
            provenance_valid = provenance_valid and bool(draft.provenance.source_trace_id)
        elif source_kind == "external":
            provenance_valid = provenance_valid and bool(draft.provenance.source_uri)
        provenance = SkillAdmissionResult(
            check="provenance",
            passed=provenance_valid,
            reason="skill source must be identified and linked to its available evidence",
        )
        active_lines = set(active.content.splitlines()) if active is not None else set()
        proposed_lines = set(proposed.content.splitlines())
        preserved = active is None or active_lines.issubset(proposed_lines)
        content_preserved = SkillAdmissionResult(
            check="content_preserved",
            passed=preserved,
            reason="existing skill content must be preserved",
        )
        return [structure, provenance, content_preserved]


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

    def admit(
        self,
        draft_id: str,
        *,
        validator: SkillAdmissionValidator,
    ) -> SkillDraft:
        draft = self._require_pending_draft(draft_id)
        proposed = self._draft_store(draft_id).get(draft.skill_name)
        if proposed is None:
            return self.reject(draft_id, reason="draft content is missing")
        active = self._skill_store.get(draft.skill_name)
        try:
            results = validator.validate(draft, proposed, active)
        except Exception as error:
            return self.reject(draft_id, reason=f"admission failed: {error}")

        draft.admission_results = list(results)
        failed = next((result for result in results if not result.passed), None)
        if failed is not None:
            draft.status = "rejected"
            draft.decision_reason = failed.reason or f"admission check failed: {failed.check}"
            self._save_draft(draft)
            self._record_event(draft, "rejected")
            return draft
        draft.status = "candidate"
        draft.decision_reason = "skill admission checks passed; evaluation required"
        self._save_draft(draft)
        self._record_event(draft, "admitted")
        return draft

    def activate(
        self,
        draft_id: str,
        *,
        evaluation_results: list[SkillEvaluationResult],
    ) -> SkillDraft:
        draft = self._require_candidate_draft(draft_id)
        active = self._skill_store.get(draft.skill_name)

        draft.evaluation_results = list(evaluation_results)
        decision, reason = self._gate_decision(evaluation_results)
        if decision != "promoted":
            draft.status = decision
            draft.decision_reason = reason
            self._save_draft(draft)
            self._record_event(draft, decision)
            return draft

        previous_version_id = self._ensure_active_version(draft.skill_name)
        self._save_version_from_draft(
            draft,
            parent_version_id=previous_version_id,
            active=active,
            evaluation_results=evaluation_results,
        )
        if previous_version_id:
            self._set_version_status(
                draft.skill_name,
                previous_version_id,
                "deprecated",
            )
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

    def discard(self, draft_id: str, *, reason: str) -> SkillDraft:
        draft = self._require_candidate_draft(draft_id)
        draft.status = "rejected"
        draft.decision_reason = reason
        self._save_draft(draft)
        self._record_event(draft, "discarded")
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
            self._set_version_status(skill_name, active_version_id, "archived")
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
        self._set_version_status(skill_name, active_version_id, "deprecated")
        self._set_version_status(skill_name, previous_version_id, "active")
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

    def archive(self, skill_name: str) -> SkillRecord | None:
        active_version_id = self._ensure_active_version(skill_name)
        if not active_version_id:
            return None
        archived = self._skill_store.archive(skill_name)
        if archived is None:
            return None
        version = self._set_version_status(
            skill_name,
            active_version_id,
            "archived",
        )
        self._save_state(
            skill_name,
            active_version_id="",
            previous_version_id="",
        )
        self._record_version_event(version, "archived")
        return archived

    def get_draft(self, draft_id: str) -> SkillDraft | None:
        path = self._draft_metadata_path(draft_id)
        if not path.exists():
            return None
        payload = json.loads(path.read_text(encoding="utf-8"))
        provenance = self._load_provenance(payload.pop("provenance"))
        if provenance is None:
            raise ValueError(f"draft provenance is missing: {draft_id}")
        payload["admission_results"] = [
            SkillAdmissionResult(**item)
            for item in payload.get("admission_results", [])
        ]
        payload["evaluation_results"] = [
            SkillEvaluationResult(**item)
            for item in payload.get("evaluation_results", [])
        ]
        return SkillDraft(**payload, provenance=provenance)

    def list_drafts(self, *, skill_name: str | None = None) -> list[SkillDraft]:
        drafts = []
        for path in sorted(self._drafts_root.glob("*.json")):
            draft = self.get_draft(path.stem)
            if draft is not None and (skill_name is None or draft.skill_name == skill_name):
                drafts.append(draft)
        return drafts

    def get_version(
        self,
        skill_name: str,
        version_id: str,
    ) -> SkillVersionRecord | None:
        path = self._version_metadata_path(skill_name, version_id)
        if not path.exists():
            return None
        payload = json.loads(path.read_text(encoding="utf-8"))
        provenance_payload = payload.pop("provenance", None)
        provenance = self._load_provenance(provenance_payload)
        payload["evaluation_results"] = tuple(
            SkillEvaluationResult(**item)
            for item in payload.get("evaluation_results", [])
        )
        return SkillVersionRecord(**payload, provenance=provenance)

    def list_versions(self, skill_name: str) -> list[SkillVersionRecord]:
        root = self._root / "versions" / skill_name
        if not root.exists():
            return []
        versions = []
        for path in sorted(root.glob("*/version.json")):
            version = self.get_version(skill_name, path.parent.name)
            if version is not None:
                versions.append(version)
        return versions

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

    def _require_candidate_draft(self, draft_id: str) -> SkillDraft:
        draft = self.get_draft(draft_id)
        if draft is None:
            raise ValueError(f"draft not found: {draft_id}")
        if draft.status != "candidate":
            raise ValueError(f"draft is not ready for activation: {draft_id}")
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
        self._save_version_record(
            SkillVersionRecord(
                version_id=version_id,
                skill_name=skill_name,
                parent_version_id="",
                status="active",
                operation="baseline",
                created_at=datetime.now(UTC).isoformat(timespec="seconds"),
                content_hash=self._content_hash(destination),
            )
        )
        return version_id

    def _save_version_from_draft(
        self,
        draft: SkillDraft,
        *,
        parent_version_id: str,
        active: SkillRecord | None,
        evaluation_results: list[SkillEvaluationResult],
    ) -> None:
        source = self._draft_root(draft.draft_id) / draft.skill_name
        version_root = self._version_root(draft.skill_name, draft.draft_id)
        destination = version_root / draft.skill_name
        version_root.mkdir(parents=True, exist_ok=True)
        shutil.copytree(source, destination)
        diff_path = version_root / "change.diff"
        diff_path.write_text(
            self._build_change_diff(
                active.path.parent if active is not None else None,
                source,
            ),
            encoding="utf-8",
        )
        self._save_version_record(
            SkillVersionRecord(
                version_id=draft.draft_id,
                skill_name=draft.skill_name,
                parent_version_id=parent_version_id,
                status="active",
                operation=draft.operation,
                created_at=draft.created_at,
                content_hash=self._content_hash(destination),
                provenance=draft.provenance,
                evaluation_results=tuple(evaluation_results),
                diff_path=diff_path.name,
            )
        )

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

    def _version_metadata_path(self, skill_name: str, version_id: str) -> Path:
        return self._version_root(skill_name, version_id) / "version.json"

    def _save_version_record(self, version: SkillVersionRecord) -> None:
        self._write_json(
            self._version_metadata_path(version.skill_name, version.version_id),
            asdict(version),
        )

    def _set_version_status(
        self,
        skill_name: str,
        version_id: str,
        status: str,
    ) -> SkillVersionRecord:
        version = self.get_version(skill_name, version_id)
        if version is None:
            raise ValueError(f"skill version metadata not found: {version_id}")
        updated = replace(version, status=status)
        self._save_version_record(updated)
        return updated

    @staticmethod
    def _content_hash(skill_dir: Path) -> str:
        digest = hashlib.sha256()
        for path in sorted(item for item in skill_dir.rglob("*") if item.is_file()):
            digest.update(path.relative_to(skill_dir).as_posix().encode("utf-8"))
            digest.update(b"\0")
            digest.update(path.read_bytes())
            digest.update(b"\0")
        return digest.hexdigest()

    @classmethod
    def _build_change_diff(
        cls,
        before: Path | None,
        after: Path,
    ) -> str:
        before_files = cls._relative_files(before)
        after_files = cls._relative_files(after)
        chunks: list[str] = []
        for relative_path in sorted(before_files.keys() | after_files.keys()):
            before_content = before_files.get(relative_path)
            after_content = after_files.get(relative_path)
            if before_content == after_content:
                continue
            try:
                before_lines = (
                    before_content.decode("utf-8").splitlines(keepends=True)
                    if before_content is not None
                    else []
                )
                after_lines = (
                    after_content.decode("utf-8").splitlines(keepends=True)
                    if after_content is not None
                    else []
                )
            except UnicodeDecodeError:
                chunks.append(f"Binary files a/{relative_path} and b/{relative_path} differ\n")
                continue
            chunks.extend(
                difflib.unified_diff(
                    before_lines,
                    after_lines,
                    fromfile=f"a/{relative_path}" if before_content is not None else "/dev/null",
                    tofile=f"b/{relative_path}" if after_content is not None else "/dev/null",
                )
            )
        return "".join(chunks)

    @staticmethod
    def _relative_files(root: Path | None) -> dict[str, bytes]:
        if root is None or not root.exists():
            return {}
        return {
            path.relative_to(root).as_posix(): path.read_bytes()
            for path in root.rglob("*")
            if path.is_file()
        }

    @staticmethod
    def _load_provenance(payload: object) -> SkillDraftProvenance | None:
        if not isinstance(payload, dict):
            return None
        values = dict(payload)
        values["evidence_ids"] = tuple(values.get("evidence_ids") or ())
        return SkillDraftProvenance(**values)

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

    def _record_version_event(
        self,
        version: SkillVersionRecord,
        action: str,
    ) -> None:
        self._root.mkdir(parents=True, exist_ok=True)
        payload = {
            "action": action,
            "timestamp": datetime.now(UTC).isoformat(timespec="seconds"),
            "version_id": version.version_id,
            "skill_name": version.skill_name,
            "status": version.status,
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
