import unittest

from navi_agent.evolution import InMemoryEvalCaseStore, EvalCase


class EvalCaseStoreTests(unittest.TestCase):
    def test_add_stores_eval_case(self) -> None:
        store = InMemoryEvalCaseStore()
        eval_case = EvalCase(
            workflow_name="prototype-baseline",
            source_session_id="wf-1",
            replay_session_id="wf-2",
            source_average_score=1.0,
            replay_average_score=0.8,
            score_delta=-0.2,
            status="regressed",
            summary="Workflow replay regressed compared with the source run",
        )

        store.add(eval_case)

        self.assertEqual(len(store.eval_cases), 1)
        self.assertEqual(store.eval_cases[0].workflow_name, "prototype-baseline")


if __name__ == "__main__":
    unittest.main()
