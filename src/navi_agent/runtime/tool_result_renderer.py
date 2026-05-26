from __future__ import annotations

from typing import Protocol

from .models import ToolArtifact, ToolResult


class ToolResultRenderer(Protocol):
    def render(self, result: ToolResult) -> str: ...


class DefaultToolResultRenderer:
    def render(self, result: ToolResult) -> str:
        lines: list[str] = []
        if result.content:
            lines.append(result.content)
        elif result.structured_content:
            lines.append(self._render_structured_content(result))

        artifact_block = self._render_artifacts(result.artifacts)
        if artifact_block:
            lines.append(artifact_block)

        if not lines:
            return f"{result.name}: {result.status}"
        return "\n\n".join(lines)

    @staticmethod
    def _render_structured_content(result: ToolResult) -> str:
        items = ", ".join(
            f"{key}={value}"
            for key, value in sorted(result.structured_content.items())
        )
        return f"{result.name}: {items}"

    @staticmethod
    def _render_artifacts(artifacts: list[ToolArtifact]) -> str:
        if not artifacts:
            return ""
        lines = ["Artifacts:"]
        for artifact in artifacts:
            label = artifact.title or artifact.uri
            lines.append(f"- {artifact.kind}: {label}")
        return "\n".join(lines)
