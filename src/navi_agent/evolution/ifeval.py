from __future__ import annotations

import json
from dataclasses import asdict
from dataclasses import dataclass
from dataclasses import field
from datetime import datetime
from datetime import timezone
import re
from pathlib import Path
from typing import Any

from .models import EvaluationResult
from .seed import EvalSeed
from .seed import EvalSeedStore

_PLACEHOLDER_PATTERN = re.compile(r"\[[^\[\]\n]+\]")
_MARKDOWN_HEADING_PATTERN = re.compile(r"^#{1,6}\s+\S")
_TITLE_TAG_PATTERN = re.compile(r"<<[^<>\n]+>>")
_WORD_PATTERN = re.compile(r"[A-Za-z0-9]+(?:'[A-Za-z0-9]+)?")
_UPPERCASE_PATTERN = re.compile(r"[A-Z]")


@dataclass(frozen=True, slots=True)
class IfevalInstructionResult:
    instruction_id: str
    passed: bool
    evidence: str


@dataclass(frozen=True, slots=True)
class IfevalEvaluationResult:
    key: int
    session_id: str
    prompt: str
    output: str
    instruction_results: list[IfevalInstructionResult]
    score: float
    summary: str
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def overall_pass(self) -> bool:
        return bool(self.instruction_results) and all(result.passed for result in self.instruction_results)

    @property
    def passed_count(self) -> int:
        return sum(1 for result in self.instruction_results if result.passed)

    @property
    def failed_count(self) -> int:
        return len(self.instruction_results) - self.passed_count

    def to_evaluation_result(self) -> EvaluationResult:
        return EvaluationResult(
            session_id=self.session_id,
            score=self.score,
            summary=self.summary,
            metadata={
                **self.metadata,
                "key": self.key,
                "prompt": self.prompt,
                "output": self.output,
                "overall_pass": self.overall_pass,
                "passed_count": self.passed_count,
                "failed_count": self.failed_count,
                "instruction_results": [asdict(result) for result in self.instruction_results],
            },
        )


@dataclass(frozen=True, slots=True)
class IfevalRunRecord:
    seed_path: str
    report_path: Path
    count: int
    passed_count: int
    failed_count: int
    pass_rate: float
    created_at: str | None = None


class IfevalEvaluator:
    def evaluate_seed(self, seed: EvalSeed) -> IfevalEvaluationResult:
        return self.evaluate(
            key=seed.key,
            session_id=seed.session_id,
            prompt=seed.prompt,
            output=seed.output,
            instruction_id_list=seed.instruction_id_list,
            kwargs_list=seed.kwargs,
        )

    def evaluate(
        self,
        *,
        key: int,
        session_id: str,
        prompt: str,
        output: str,
        instruction_id_list: list[str],
        kwargs_list: list[dict[str, Any]],
    ) -> IfevalEvaluationResult:
        instruction_results: list[IfevalInstructionResult] = []
        for index, instruction_id in enumerate(instruction_id_list):
            instruction_kwargs = kwargs_list[index] if index < len(kwargs_list) and isinstance(kwargs_list[index], dict) else {}
            instruction_results.append(
                self._evaluate_instruction(
                    instruction_id=instruction_id,
                    instruction_kwargs=instruction_kwargs,
                    prompt=prompt,
                    output=output,
                )
            )

        passed_count = sum(1 for result in instruction_results if result.passed)
        total_count = len(instruction_results)
        score = round(passed_count / total_count, 3) if total_count else 0.0
        failed_ids = [result.instruction_id for result in instruction_results if not result.passed]
        if not instruction_results:
            summary = "No IFEval instructions supplied"
        elif not failed_ids:
            summary = "All IFEval instructions passed"
        else:
            summary = f"Failed instructions: {', '.join(failed_ids)}"
        return IfevalEvaluationResult(
            key=key,
            session_id=session_id,
            prompt=prompt,
            output=output,
            instruction_results=instruction_results,
            score=score,
            summary=summary,
            metadata={
                "instruction_id_list": list(instruction_id_list),
                "kwargs_list": kwargs_list,
                "word_count": self._count_words(output),
                "placeholder_count": self._count_placeholders(output),
                "title_tag_count": self._count_title_tags(output),
                "comma_count": output.count(","),
            },
        )

    def _evaluate_instruction(
        self,
        *,
        instruction_id: str,
        instruction_kwargs: dict[str, Any],
        prompt: str,
        output: str,
    ) -> IfevalInstructionResult:
        if instruction_id == "punctuation:no_comma":
            passed = "," not in output
            evidence = "No commas found in the output." if passed else f"Found {output.count(',')} comma(s) in the output."
            return IfevalInstructionResult(instruction_id=instruction_id, passed=passed, evidence=evidence)
        if instruction_id == "detectable_format:number_highlighted_sections":
            expected = self._as_int(instruction_kwargs.get("num_highlights"), default=1)
            relation = self._as_relation(instruction_kwargs.get("relation"), default="at least")
            observed = self._count_markdown_titles(output)
            passed = self._compare_count(observed=observed, expected=expected, relation=relation)
            evidence = f"Found {observed} markdown title section(s); expected {relation} {expected}."
            return IfevalInstructionResult(instruction_id=instruction_id, passed=passed, evidence=evidence)
        if instruction_id == "length_constraints:number_words":
            expected = self._as_int(instruction_kwargs.get("num_words"), default=1)
            relation = self._as_relation(instruction_kwargs.get("relation"), default="at least")
            observed = self._count_words(output)
            passed = self._compare_count(observed=observed, expected=expected, relation=relation)
            evidence = f"Found {observed} word(s); expected {relation} {expected}."
            return IfevalInstructionResult(instruction_id=instruction_id, passed=passed, evidence=evidence)
        if instruction_id == "detectable_content:number_placeholders":
            expected = self._as_int(instruction_kwargs.get("num_placeholders"), default=1)
            relation = self._as_relation(instruction_kwargs.get("relation"), default="at least")
            observed = self._count_placeholders(output)
            passed = self._compare_count(observed=observed, expected=expected, relation=relation)
            evidence = f"Found {observed} placeholder(s); expected {relation} {expected}."
            return IfevalInstructionResult(instruction_id=instruction_id, passed=passed, evidence=evidence)
        if instruction_id == "combination:repeat_prompt":
            prompt_to_repeat = str(instruction_kwargs.get("prompt_to_repeat", ""))
            passed = bool(prompt_to_repeat) and output.startswith(prompt_to_repeat)
            evidence = (
                "Output begins with the exact repeated prompt."
                if passed
                else "Output does not begin with the exact repeated prompt."
            )
            return IfevalInstructionResult(instruction_id=instruction_id, passed=passed, evidence=evidence)
        if instruction_id == "detectable_format:title":
            observed = self._count_title_tags(output)
            passed = observed >= 1
            evidence = f"Found {observed} title tag(s) wrapped in double angle brackets."
            return IfevalInstructionResult(instruction_id=instruction_id, passed=passed, evidence=evidence)
        if instruction_id == "change_case:english_lowercase":
            uppercase_match = _UPPERCASE_PATTERN.search(output)
            passed = uppercase_match is None
            evidence = (
                "No ASCII uppercase letters found."
                if passed
                else f"Found uppercase letter {uppercase_match.group(0)!r}."
            )
            return IfevalInstructionResult(instruction_id=instruction_id, passed=passed, evidence=evidence)
        return IfevalInstructionResult(
            instruction_id=instruction_id,
            passed=False,
            evidence=f"Unsupported IFEval instruction: {instruction_id}",
        )

    @staticmethod
    def _count_words(text: str) -> int:
        return len(_WORD_PATTERN.findall(text))

    @staticmethod
    def _count_placeholders(text: str) -> int:
        return len(_PLACEHOLDER_PATTERN.findall(text))

    @staticmethod
    def _count_title_tags(text: str) -> int:
        return len(_TITLE_TAG_PATTERN.findall(text))

    @staticmethod
    def _count_markdown_titles(text: str) -> int:
        count = 0
        for line in text.splitlines():
            stripped = line.strip()
            if not stripped:
                continue
            if _MARKDOWN_HEADING_PATTERN.match(stripped):
                count += 1
                continue
            if IfevalEvaluator._is_emphasis_title(stripped):
                count += 1
        return count

    @staticmethod
    def _is_emphasis_title(line: str) -> bool:
        if len(line) < 2:
            return False
        for marker in ("**", "__", "*", "_"):
            if line.startswith(marker) and line.endswith(marker):
                body = line[len(marker) : -len(marker)].strip()
                return bool(body) and marker not in body
        return False

    @staticmethod
    def _as_int(value: Any, *, default: int) -> int:
        try:
            return int(value)
        except (TypeError, ValueError):
            return default

    @staticmethod
    def _as_relation(value: Any, *, default: str) -> str:
        relation = str(value).strip().lower() if value is not None else default
        return relation or default

    @staticmethod
    def _compare_count(*, observed: int, expected: int, relation: str) -> bool:
        relation = relation.strip().lower()
        if relation in {"at least", "minimum", "min"}:
            return observed >= expected
        if relation in {"at most", "maximum", "max"}:
            return observed <= expected
        if relation in {"exactly", "equal to"}:
            return observed == expected
        if relation in {"more than", "greater than"}:
            return observed > expected
        if relation in {"less than"}:
            return observed < expected
        return False


class IfevalRunWriter:
    def __init__(self, reports_root: Path) -> None:
        self._reports_root = reports_root

    def write_run_report(
        self,
        *,
        seed_store: EvalSeedStore,
        results: list[IfevalEvaluationResult],
    ) -> Path:
        run_dir = self._new_run_dir()
        payload = self._build_payload(seed_store=seed_store, results=results)
        (run_dir / "run.json").write_text(
            json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True),
            encoding="utf-8",
        )
        (run_dir / "REPORT.md").write_text(
            self._build_markdown(payload),
            encoding="utf-8",
        )
        return run_dir

    def _new_run_dir(self) -> Path:
        self._reports_root.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
        run_dir = self._reports_root / timestamp
        suffix = 1
        while run_dir.exists():
            run_dir = self._reports_root / f"{timestamp}-{suffix}"
            suffix += 1
        run_dir.mkdir(parents=True, exist_ok=False)
        return run_dir

    @staticmethod
    def _build_payload(
        *,
        seed_store: EvalSeedStore,
        results: list[IfevalEvaluationResult],
    ) -> dict[str, object]:
        passed_count = sum(1 for result in results if result.overall_pass)
        count = len(results)
        return {
            "seed_path": str(seed_store.path),
            "count": count,
            "passed_count": passed_count,
            "failed_count": count - passed_count,
            "pass_rate": IfevalRunWriter._pass_rate(count, passed_count),
            "results": [IfevalRunWriter._result_payload(result) for result in results],
        }

    @staticmethod
    def _result_payload(result: IfevalEvaluationResult) -> dict[str, object]:
        return {
            "key": result.key,
            "session_id": result.session_id,
            "prompt": result.prompt,
            "output": result.output,
            "score": result.score,
            "summary": result.summary,
            "overall_pass": result.overall_pass,
            "passed_count": result.passed_count,
            "failed_count": result.failed_count,
            "instruction_results": [asdict(item) for item in result.instruction_results],
            "metadata": result.metadata,
        }

    @staticmethod
    def _build_markdown(payload: dict[str, object]) -> str:
        lines = [
            "# IFEval run report",
            "",
            "## Summary",
            f"- seed path: `{payload['seed_path']}`",
            f"- count: `{payload['count']}`",
            f"- passed: `{payload['passed_count']}`",
            f"- failed: `{payload['failed_count']}`",
            f"- pass rate: `{payload['pass_rate']}`",
            "",
            "## Results",
        ]
        for result in payload.get("results", []):
            if not isinstance(result, dict):
                continue
            status = "pass" if result.get("overall_pass") else "fail"
            lines.extend(
                [
                    f"- `{result.get('key')}` [{status}] `{result.get('session_id')}`",
                    f"  prompt: {result.get('prompt', '')}",
                    f"  score: `{result.get('score')}`",
                    f"  summary: {result.get('summary', '')}",
                ]
            )
        return "\n".join(lines) + "\n"

    @staticmethod
    def _pass_rate(count: int, passed_count: int) -> float:
        if count <= 0:
            return 0.0
        return round(passed_count / count, 3)


class IfevalRunStore:
    def __init__(self, reports_root: Path) -> None:
        self._reports_root = reports_root

    def get_latest(self) -> IfevalRunRecord | None:
        records = self.list_recent(limit=1)
        if not records:
            return None
        return records[0]

    def list_recent(self, limit: int | None = None) -> list[IfevalRunRecord]:
        if not self._reports_root.exists():
            return []
        run_dirs = [path for path in self._reports_root.iterdir() if path.is_dir() and (path / "run.json").exists()]
        run_dirs.sort(key=lambda path: path.name, reverse=True)
        if limit is not None:
            run_dirs = run_dirs[:limit]
        records: list[IfevalRunRecord] = []
        for run_dir in run_dirs:
            record = self._load_record(run_dir)
            if record is not None:
                records.append(record)
        return records

    @staticmethod
    def _load_record(run_dir: Path) -> IfevalRunRecord | None:
        try:
            payload = json.loads((run_dir / "run.json").read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None
        count = int(payload.get("count", 0))
        passed_count = int(payload.get("passed_count", 0))
        failed_count = int(payload.get("failed_count", 0))
        pass_rate = IfevalRunWriter._pass_rate(count, passed_count)
        seed_path = str(payload.get("seed_path", ""))
        created_at = run_dir.name
        return IfevalRunRecord(
            seed_path=seed_path,
            report_path=run_dir,
            count=count,
            passed_count=passed_count,
            failed_count=failed_count,
            pass_rate=pass_rate,
            created_at=created_at,
        )
