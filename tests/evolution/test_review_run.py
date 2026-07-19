from pathlib import Path

from navi_agent.evolution import JsonlReviewRunStore, ReviewRunRecord, ReviewToolResultRecord


def test_review_run_store_persists_records(tmp_path: Path) -> None:
    store = JsonlReviewRunStore(tmp_path / "review-runs.jsonl")
    store.add(
        ReviewRunRecord(
            session_id="s1",
            trace_id="trace-1",
            user_id="u1",
            review_memory=True,
            review_skill=True,
            status="success",
            review_session_id="review:s1",
            tool_results=[
                ReviewToolResultRecord(
                    name="memory",
                    status="success",
                    action="add",
                    structured_content={"target": "user"},
                )
            ],
            memory_writes=[{"target": "user", "kind": "preference"}],
            skill_writes=[{"skill_name": "readme-summary", "action": "append"}],
        )
    )

    records = JsonlReviewRunStore(tmp_path / "review-runs.jsonl").list_recent()

    assert len(records) == 1
    assert records[0].session_id == "s1"
    assert records[0].tool_results[0].name == "memory"
    assert records[0].memory_writes == [{"target": "user", "kind": "preference"}]
    assert records[0].skill_writes == [{"skill_name": "readme-summary", "action": "append"}]
