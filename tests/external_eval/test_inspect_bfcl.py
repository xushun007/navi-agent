from evals.inspect.bfcl import load_bfcl_samples


def test_loads_balanced_curated_bfcl_samples() -> None:
    samples = load_bfcl_samples()

    assert len(samples) == 10
    assert {sample.metadata["category"] for sample in samples} == {
        "simple",
        "multiple",
        "parallel",
        "irrelevance",
    }
    assert sum(sample.metadata["category"] == "simple" for sample in samples) == 3
    assert sum(sample.metadata["category"] == "multiple" for sample in samples) == 3
    assert sum(sample.metadata["category"] == "parallel" for sample in samples) == 2
    assert sum(sample.metadata["category"] == "irrelevance" for sample in samples) == 2
