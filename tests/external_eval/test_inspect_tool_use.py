import importlib.util
import sys
from pathlib import Path


MODULE_PATH = Path(__file__).resolve().parents[2] / "evals" / "inspect_tool_use.py"
SPEC = importlib.util.spec_from_file_location("inspect_tool_use_adapter", MODULE_PATH)
assert SPEC is not None
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)

build_navi_eval_command = MODULE.build_navi_eval_command
load_tool_use_cases = MODULE.load_tool_use_cases
parse_passed = MODULE.parse_passed


def test_load_tool_use_cases_from_seed() -> None:
    cases = load_tool_use_cases()

    assert len(cases) >= 10
    first = cases[0]
    assert first.id == "tooluse_l0_file_read_001"
    assert first.level == "L0"
    assert first.required_tools == ["read_file"]
    assert first.expected_args["read_file"]["path"] == "README.md"


def test_build_navi_eval_command() -> None:
    command = build_navi_eval_command("case-1")

    assert command == [
        "uv",
        "run",
        "navi-agent",
        "--workflow-kind",
        "tool_use_eval",
        "--workflow-phase",
        "run",
        "--workflow-case-id",
        "case-1",
    ]


def test_parse_passed_requires_case_pass_and_full_pass_rate() -> None:
    assert parse_passed(
        "tool_use_eval_pass_rate: 1.0\ntooluse_l0_file_read_001 [pass] score=1.0 pass",
        "tooluse_l0_file_read_001",
    )
    assert not parse_passed(
        "tool_use_eval_pass_rate: 0.0\ntooluse_l0_file_read_001 [fail] score=0.0 missing",
        "tooluse_l0_file_read_001",
    )


def test_load_tool_use_cases_from_custom_file(tmp_path: Path) -> None:
    seed = tmp_path / "tool_use.jsonl"
    seed.write_text(
        '{"id":"c1","level":"L1","prompt":"p","required_tools":["todo"],'
        '"forbidden_tools":["bash"],"expected_args":{"todo":{"action":"list"}}}\n',
        encoding="utf-8",
    )

    cases = load_tool_use_cases(seed)

    assert len(cases) == 1
    assert cases[0].id == "c1"
    assert cases[0].forbidden_tools == ["bash"]
