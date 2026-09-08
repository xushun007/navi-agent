from __future__ import annotations

import unittest

from navi_agent.runtime.agent.prompt_pipeline import (
    PromptContributionError,
    PromptLayer,
    PromptPipeline,
    PromptRequest,
    PromptSection,
)


class StaticContributor:
    def __init__(
        self,
        name: str,
        layer: PromptLayer,
        content: str,
        references: tuple[str, ...] = (),
    ) -> None:
        self.name = name
        self._section = PromptSection(
            source=name,
            layer=layer,
            content=content,
            references=references,
        )

    def contribute(self, request: PromptRequest) -> PromptSection:
        return self._section


class EmptyContributor:
    name = "empty"

    def contribute(self, request: PromptRequest) -> None:
        return None


class FailingContributor:
    name = "project-context"

    def contribute(self, request: PromptRequest) -> PromptSection:
        raise OSError("cannot read AGENTS.md")


class PromptPipelineTests(unittest.TestCase):
    def test_groups_sections_by_layer_and_preserves_order_within_layer(self) -> None:
        pipeline = PromptPipeline(
            [
                StaticContributor("base", PromptLayer.STABLE, "Base"),
                StaticContributor("system", PromptLayer.CONTEXT, "System"),
                StaticContributor("memory", PromptLayer.VOLATILE, "Memory"),
                StaticContributor("guidance", PromptLayer.STABLE, "Guidance"),
                EmptyContributor(),
                StaticContributor("skills", PromptLayer.VOLATILE, "Skills"),
            ]
        )

        result = pipeline.build(PromptRequest(user_id="u1", user_message="hello"))

        self.assertEqual(result.parts.stable, "Base\n\nGuidance")
        self.assertEqual(result.parts.context, "System")
        self.assertEqual(result.parts.volatile, "Memory\n\nSkills")
        self.assertEqual(
            result.parts.render(),
            "Base\n\nGuidance\n\nSystem\n\nMemory\n\nSkills",
        )

    def test_keeps_references_with_the_contributing_section(self) -> None:
        pipeline = PromptPipeline(
            [
                StaticContributor(
                    "project-context",
                    PromptLayer.CONTEXT,
                    "Project",
                    references=("AGENTS.md",),
                )
            ]
        )

        result = pipeline.build(PromptRequest(user_id="u1", user_message="hello"))

        self.assertEqual(result.references_from("project-context"), ("AGENTS.md",))
        self.assertEqual(result.references_from("skills"), ())

    def test_reports_the_contributor_that_failed(self) -> None:
        pipeline = PromptPipeline([FailingContributor()])

        with self.assertRaises(PromptContributionError) as raised:
            pipeline.build(PromptRequest(user_id="u1", user_message="hello"))

        self.assertEqual(raised.exception.contributor, "project-context")
        self.assertIn("cannot read AGENTS.md", str(raised.exception))

    def test_section_requires_a_source(self) -> None:
        with self.assertRaisesRegex(ValueError, "source must not be empty"):
            PromptSection(source=" ", layer=PromptLayer.STABLE, content="Base")


if __name__ == "__main__":
    unittest.main()
