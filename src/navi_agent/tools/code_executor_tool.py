from __future__ import annotations

from typing import Any

from navi_agent.tooling import ToolContext, ToolResult

from .bash_tool import BashTool
from .patch_tool import PatchTool
from .read_file_tool import ReadFileTool
from .workspace_tool import WorkspaceTool
from .write_file_tool import WriteFileTool


class CodeExecutorTool(WorkspaceTool):
    _ACTIONS = {"read_file", "write_file", "patch", "run"}

    def __init__(
        self,
        root=None,
        default_timeout_seconds: int = 20,
        max_timeout_seconds: int = 60,
        max_output_chars: int = 20_000,
        max_steps: int = 12,
    ) -> None:
        super().__init__(root=root)
        self._max_steps = max_steps
        self._tools = {
            "read_file": ReadFileTool(root=self.root),
            "write_file": WriteFileTool(root=self.root),
            "patch": PatchTool(root=self.root),
            "run": BashTool(
                root=self.root,
                default_timeout_seconds=default_timeout_seconds,
                max_timeout_seconds=max_timeout_seconds,
                max_output_chars=max_output_chars,
            ),
        }

    @property
    def name(self) -> str:
        return "code_executor"

    @property
    def description(self) -> str:
        return "Execute a bounded coding workflow inside the workspace: inspect files, edit files, and run verification commands."

    def schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "task": {"type": "string"},
                "steps": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "action": {"type": "string", "enum": sorted(self._ACTIONS)},
                            "path": {"type": "string"},
                            "content": {"type": "string"},
                            "old": {"type": "string"},
                            "new": {"type": "string"},
                            "replace_all": {"type": "boolean"},
                            "expected_sha256": {"type": "string"},
                            "start_line": {"type": "integer", "minimum": 1},
                            "line_count": {"type": "integer", "minimum": 1},
                            "command": {"type": "string"},
                            "cwd": {"type": "string"},
                            "timeout_seconds": {"type": "integer", "minimum": 1, "maximum": 60},
                        },
                        "required": ["action"],
                    },
                    "minItems": 1,
                },
            },
            "required": ["task", "steps"],
        }

    def invoke(self, context: ToolContext | None = None, **kwargs: Any) -> ToolResult:
        task = str(kwargs.get("task") or "").strip()
        if not task:
            return ToolResult.error(name=self.name, content="Task must not be empty")

        raw_steps = kwargs.get("steps")
        if not isinstance(raw_steps, list) or not raw_steps:
            return ToolResult.error(name=self.name, content="Steps must be a non-empty list")
        if len(raw_steps) > self._max_steps:
            return ToolResult.error(
                name=self.name,
                content=f"Too many steps: {len(raw_steps)} > {self._max_steps}",
                structured_content={"task": task, "step_count": len(raw_steps), "max_steps": self._max_steps},
            )

        steps = []
        changed_files: list[str] = []
        commands_run: list[str] = []
        overall_success = True

        for index, raw_step in enumerate(raw_steps, start=1):
            normalized, error = self._normalize_step(raw_step)
            if error is not None:
                overall_success = False
                steps.append({"index": index, "status": "error", "content": error})
                break

            action = normalized.pop("action")
            result = self._tools[action].invoke(context=context, **normalized)
            step = {
                "index": index,
                "action": action,
                "status": result.status,
                "content": result.content,
                "structured_content": result.structured_content,
            }
            if action == "run":
                step["command"] = normalized.get("command")
                commands_run.append(str(normalized.get("command")))
            if action in {"write_file", "patch"} and result.status == "success":
                path = result.structured_content.get("path")
                if isinstance(path, str) and path not in changed_files:
                    changed_files.append(path)
            steps.append(step)
            if result.status != "success":
                overall_success = False
                break

        content = self._render_summary(
            task=task,
            steps=steps,
            success=overall_success,
            changed_files=changed_files,
            commands_run=commands_run,
        )
        result_cls = ToolResult.ok if overall_success else ToolResult.error
        return result_cls(
            name=self.name,
            content=content,
            structured_content={
                "task": task,
                "success": overall_success,
                "changed_files": changed_files,
                "commands_run": commands_run,
                "steps": steps,
            },
            metadata={
                "task": task,
                "success": overall_success,
                "step_count": len(steps),
            },
        )

    def _normalize_step(self, raw_step: Any) -> tuple[dict[str, Any], str | None]:
        if not isinstance(raw_step, dict):
            return {}, "Step must be an object"
        action = str(raw_step.get("action") or "").strip()
        if action not in self._ACTIONS:
            return {}, f"Unsupported action: {action or '-'}"

        required_fields = {
            "read_file": ("path",),
            "write_file": ("path", "content"),
            "patch": ("path", "old", "new"),
            "run": ("command",),
        }[action]
        for field in required_fields:
            if raw_step.get(field) is None or str(raw_step.get(field)).strip() == "":
                return {}, f"{action} requires non-empty {field}"

        allowed_fields = {
            "read_file": ("path", "start_line", "line_count"),
            "write_file": ("path", "content", "expected_sha256"),
            "patch": ("path", "old", "new", "replace_all", "expected_sha256"),
            "run": ("command", "cwd", "timeout_seconds"),
        }[action]
        normalized: dict[str, Any] = {"action": action}
        for field in allowed_fields:
            if raw_step.get(field) is not None:
                normalized[field] = raw_step[field]
        return normalized, None

    def _render_summary(
        self,
        *,
        task: str,
        steps: list[dict[str, Any]],
        success: bool,
        changed_files: list[str],
        commands_run: list[str],
    ) -> str:
        lines = [
            f"task: {task}",
            f"status: {'success' if success else 'error'}",
            f"steps: {len(steps)}",
        ]
        if changed_files:
            lines.append("changed_files:")
            lines.extend(f"- {path}" for path in changed_files)
        if commands_run:
            lines.append("commands_run:")
            lines.extend(f"- {command}" for command in commands_run)
        for step in steps:
            action = step.get("action", "-")
            lines.append(f"[{step['index']}] {step.get('status', 'error')}: {action}")
            if step.get("command"):
                lines.append(f"command: {step['command']}")
            content = str(step.get("content") or "").strip()
            if content:
                lines.append(content)
        return "\n".join(lines)
