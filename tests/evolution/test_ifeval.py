from __future__ import annotations

import unittest
from pathlib import Path

from navi_agent.evolution import EvalSeed, IfevalEvaluator
from navi_agent.evolution import EvalSeedStore


class IfevalEvaluatorTests(unittest.TestCase):
    def test_evaluate_seed_matches_known_pass_case(self) -> None:
        seed = EvalSeed(
            key=1,
            prompt="repeat the prompt and keep it lowercase.",
            instruction_id_list=[
                "combination:repeat_prompt",
                "detectable_format:title",
                "change_case:english_lowercase",
            ],
            kwargs=[
                {"prompt_to_repeat": "repeat the prompt and keep it lowercase."},
                {},
                {},
            ],
            session_id="s1",
            output="repeat the prompt and keep it lowercase.\n\n<<title>>\nall lower case.",
            pass_fail=True,
        )

        result = IfevalEvaluator().evaluate_seed(seed)

        self.assertTrue(result.overall_pass)
        self.assertEqual(result.score, 1.0)
        self.assertEqual(result.passed_count, 3)
        self.assertEqual(result.failed_count, 0)
        self.assertEqual([item.passed for item in result.instruction_results], [True, True, True])

    def test_evaluate_seed_reports_failures(self) -> None:
        seed = EvalSeed(
            key=2,
            prompt="Write 10 words without commas.",
            instruction_id_list=["punctuation:no_comma", "length_constraints:number_words"],
            kwargs=[{}, {"relation": "at least", "num_words": 10}],
            session_id="s2",
            output="one, two three",
            pass_fail=False,
        )

        result = IfevalEvaluator().evaluate_seed(seed)

        self.assertFalse(result.overall_pass)
        self.assertEqual(result.score, 0.0)
        self.assertEqual(result.failed_count, 2)
        self.assertIn("punctuation:no_comma", result.summary)
        self.assertIn("length_constraints:number_words", result.summary)
        self.assertFalse(result.instruction_results[0].passed)
        self.assertFalse(result.instruction_results[1].passed)

    def test_evaluate_supports_all_seed_instruction_types(self) -> None:
        evaluator = IfevalEvaluator()

        comma_case = evaluator.evaluate(
            key=3,
            session_id="s3",
            prompt="Say hello without commas.",
            output="hello world",
            instruction_id_list=["punctuation:no_comma"],
            kwargs_list=[{}],
        )
        placeholder_case = evaluator.evaluate(
            key=4,
            session_id="s4",
            prompt="Use placeholders.",
            output="[name] [address]",
            instruction_id_list=["detectable_content:number_placeholders"],
            kwargs_list=[{"num_placeholders": 2}],
        )
        highlight_case = evaluator.evaluate(
            key=5,
            session_id="s5",
            prompt="Use markdown titles.",
            output="**One**\n**Two**\n# Three",
            instruction_id_list=["detectable_format:number_highlighted_sections"],
            kwargs_list=[{"relation": "at least", "num_highlights": 3}],
        )
        title_case = evaluator.evaluate(
            key=6,
            session_id="s6",
            prompt="Add a title.",
            output="<<title>>",
            instruction_id_list=["detectable_format:title"],
            kwargs_list=[{}],
        )
        lowercase_case = evaluator.evaluate(
            key=7,
            session_id="s7",
            prompt="Keep it lowercase.",
            output="all lowercase text",
            instruction_id_list=["change_case:english_lowercase"],
            kwargs_list=[{}],
        )

        self.assertTrue(comma_case.overall_pass)
        self.assertTrue(placeholder_case.overall_pass)
        self.assertTrue(highlight_case.overall_pass)
        self.assertTrue(title_case.overall_pass)
        self.assertTrue(lowercase_case.overall_pass)

    def test_evaluate_seed_file_samples(self) -> None:
        store = EvalSeedStore(Path("data/eval/ifeval_seed.jsonl"))
        seeds = {seed.key: seed for seed in store.list_recent(limit=None)}
        evaluator = IfevalEvaluator()

        self.assertFalse(evaluator.evaluate_seed(seeds[1000]).overall_pass)
        self.assertTrue(evaluator.evaluate_seed(seeds[1001]).overall_pass)
        self.assertTrue(evaluator.evaluate_seed(seeds[1005]).overall_pass)
        self.assertTrue(evaluator.evaluate_seed(seeds[1012]).overall_pass)
        self.assertTrue(evaluator.evaluate_seed(seeds[1019]).overall_pass)


if __name__ == "__main__":
    unittest.main()
