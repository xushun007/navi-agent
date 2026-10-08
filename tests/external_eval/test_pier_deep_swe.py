import asyncio
import importlib
import sys
from types import ModuleType, SimpleNamespace


def _load_adapter(monkeypatch):
    class FakeBaseAgent:
        def __init__(self, *args, **kwargs) -> None:
            self.logs_dir = kwargs.get("logs_dir")

    pier = ModuleType("pier")
    agents = ModuleType("pier.agents")
    agents_base = ModuleType("pier.agents.base")
    environments = ModuleType("pier.environments")
    environments_base = ModuleType("pier.environments.base")
    agents_base.BaseAgent = FakeBaseAgent
    environments_base.BaseEnvironment = object
    monkeypatch.setitem(sys.modules, "pier", pier)
    monkeypatch.setitem(sys.modules, "pier.agents", agents)
    monkeypatch.setitem(sys.modules, "pier.agents.base", agents_base)
    monkeypatch.setitem(sys.modules, "pier.environments", environments)
    monkeypatch.setitem(sys.modules, "pier.environments.base", environments_base)
    sys.modules.pop("evals.pier.deep_swe", None)
    return importlib.import_module("evals.pier.deep_swe")


def test_pier_bridge_exposes_bash_and_preserves_command_result(monkeypatch) -> None:
    adapter = _load_adapter(monkeypatch)

    class Environment:
        async def exec(self, command, *, cwd, timeout_sec):
            assert command == "git status --short"
            assert cwd == "/workspace"
            assert timeout_sec == 120
            return SimpleNamespace(stdout=" M source.py\n", stderr="", return_code=0)

    async def run_test():
        bridge = adapter.PierSandboxBridge(
            loop=asyncio.get_running_loop(),
            environment=Environment(),
        )
        assert [schema["name"] for schema in bridge.tool_registry().schemas()] == ["bash"]
        result = await asyncio.to_thread(
            bridge._bash,
            command="git status --short",
            cwd="/workspace",
            timeout_seconds=120,
        )
        assert result.status == "success"
        assert result.structured_content["exit_code"] == 0
        assert "M source.py" in result.content

    asyncio.run(run_test())


def test_pier_agent_records_navi_trace_metrics(monkeypatch) -> None:
    adapter = _load_adapter(monkeypatch)
    fake_result = SimpleNamespace(
        input_tokens=120,
        output_tokens=45,
        cost_usd=0.03,
        iterations=4,
        run_id="run-1",
        trace_id="trace-1",
        status="success",
        completion_verified=True,
        completion_reason="verified",
    )

    class FakeRunner:
        def run(self, instruction, **kwargs):
            assert instruction == "Implement the feature"
            assert kwargs["suite"] == "deep-swe-1-1"
            return fake_result

    monkeypatch.setattr(adapter, "build_inspect_runtime_runner", lambda: FakeRunner())
    agent = adapter.NaviDeepSweAgent(logs_dir=None)

    class Environment:
        session_id = "deep-swe-smoke"

    context = SimpleNamespace(
        n_input_tokens=None,
        n_output_tokens=None,
        cost_usd=None,
        n_agent_steps=None,
        metadata=None,
    )

    asyncio.run(agent.run("Implement the feature", Environment(), context))

    assert context.n_input_tokens == 120
    assert context.n_output_tokens == 45
    assert context.cost_usd == 0.03
    assert context.n_agent_steps == 4
    assert context.metadata == {
        "navi_run_id": "run-1",
        "navi_trace_id": "trace-1",
        "navi_status": "success",
        "completion_verified": True,
        "completion_reason": "verified",
    }
