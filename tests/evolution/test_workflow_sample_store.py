import unittest

from navi_agent.evolution import InMemoryWorkflowSampleStore, WorkflowEvolutionSample


class WorkflowSampleStoreTests(unittest.TestCase):
    def test_add_stores_workflow_sample(self) -> None:
        store = InMemoryWorkflowSampleStore()
        sample = WorkflowEvolutionSample(
            workflow_name="prototype-baseline",
            source_session_id="wf-1",
            replay_session_id="wf-2",
            source_average_score=1.0,
            replay_average_score=0.8,
            score_delta=-0.2,
            status="regressed",
            summary="Workflow replay regressed compared with the source run",
        )

        store.add(sample)

        self.assertEqual(len(store.samples), 1)
        self.assertEqual(store.samples[0].workflow_name, "prototype-baseline")


if __name__ == "__main__":
    unittest.main()
