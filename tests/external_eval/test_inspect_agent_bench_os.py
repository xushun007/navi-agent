from evals.inspect.agent_bench_os import load_agent_bench_os_samples


def test_loads_ten_public_agent_bench_os_dev_samples() -> None:
    samples = load_agent_bench_os_samples()

    assert len(samples) == 10
    assert {sample.metadata["source_id"] for sample in samples} == {
        3,
        6,
        7,
        9,
        10,
        11,
        12,
        21,
        24,
        25,
    }
    assert {sample.metadata["category"] for sample in samples} == {
        "file_query",
        "shell_query",
        "state_change",
    }
