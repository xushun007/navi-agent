import pytest

from evals.longmemeval_review import prepare


def rows():
    common = {"question_id": "a_abs", "question_type": "single-session-user", "question": "Where?",
              "reference_answer": "Unknown"}
    return ([{**common, "hypothesis": "I don't know", "runtime_status": "success"}],
            [{**common, "hypothesis": "Cannot tell", "completed": False}])


def test_prepare_preserves_abstention_and_incomplete_run_for_separate_review():
    references, navi, hermes, review = prepare(*rows())
    assert references[0]["answer"] == "Unknown"
    assert navi == [{"question_id": "a_abs", "hypothesis": "I don't know"}]
    assert hermes == [{"question_id": "a_abs", "hypothesis": "Cannot tell"}]
    assert review[0]["hermes_completed"] is False
    assert review[0]["navi_evidence_supported"] is None


def test_prepare_rejects_unpaired_duplicate_or_inconsistent_data():
    left, right = rows()
    with pytest.raises(ValueError, match="identical"):
        prepare(left, [])
    with pytest.raises(ValueError, match="Duplicate"):
        prepare(left * 2, right)
    right[0]["reference_answer"] = "Different"
    with pytest.raises(ValueError, match="Inconsistent"):
        prepare(left, right)
