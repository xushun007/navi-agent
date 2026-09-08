from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol


class PromptLayer(StrEnum):
    STABLE = "stable"
    CONTEXT = "context"
    VOLATILE = "volatile"


@dataclass(frozen=True, slots=True)
class PromptRequest:
    user_id: str
    user_message: str
    system_prompt: str | None = None


@dataclass(frozen=True, slots=True)
class PromptSection:
    source: str
    layer: PromptLayer
    content: str
    references: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.source.strip():
            raise ValueError("Prompt section source must not be empty")


@dataclass(frozen=True, slots=True)
class PromptParts:
    stable: str
    context: str = ""
    volatile: str = ""

    def render(self) -> str:
        return "\n\n".join(
            part.strip()
            for part in [self.stable, self.context, self.volatile]
            if part.strip()
        )


@dataclass(frozen=True, slots=True)
class PromptBuildResult:
    parts: PromptParts
    sections: tuple[PromptSection, ...]

    def references_from(self, source: str) -> tuple[str, ...]:
        return tuple(
            reference
            for section in self.sections
            if section.source == source
            for reference in section.references
        )


class PromptContributor(Protocol):
    name: str

    def contribute(self, request: PromptRequest) -> PromptSection | None: ...


class PromptContributionError(RuntimeError):
    def __init__(self, contributor: str, cause: Exception) -> None:
        super().__init__(f"Prompt contributor {contributor!r} failed: {cause}")
        self.contributor = contributor
        self.__cause__ = cause


class PromptPipeline:
    def __init__(self, contributors: Iterable[PromptContributor]) -> None:
        self._contributors = tuple(contributors)

    def build(self, request: PromptRequest) -> PromptBuildResult:
        sections: list[PromptSection] = []
        for contributor in self._contributors:
            try:
                section = contributor.contribute(request)
            except Exception as error:
                raise PromptContributionError(contributor.name, error) from error
            if section is None or not section.content.strip():
                continue
            sections.append(section)

        return PromptBuildResult(
            parts=PromptParts(
                stable=self._render_layer(sections, PromptLayer.STABLE),
                context=self._render_layer(sections, PromptLayer.CONTEXT),
                volatile=self._render_layer(sections, PromptLayer.VOLATILE),
            ),
            sections=tuple(sections),
        )

    @staticmethod
    def _render_layer(
        sections: Iterable[PromptSection],
        layer: PromptLayer,
    ) -> str:
        return "\n\n".join(
            section.content.strip() for section in sections if section.layer is layer
        )
