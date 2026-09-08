import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from navi_agent.app.bootstrap import build_runtime
from navi_agent.config import (
    LangfuseSettings,
    MCPSettings,
    ModelSettings,
    RuntimeSettings,
)
from navi_agent.memory import FileMemoryStore
from navi_agent.runtime import ToolCall, ToolContext, ToolRegistration
from navi_agent.runtime.tools.approval import AutoApproveApprovalProvider
from navi_agent.telemetry import CompositeTraceStore, JsonlTraceStore
from navi_agent.evolution import (
    FileSkillStore,
    JsonlCandidateStore,
    JsonlEvalCaseStore,
    PromptOverlayStore,
)
from navi_agent.app.bootstrap import build_application
from navi_agent.tooling import ToolResult
from navi_agent.tools.base import FunctionTool


class BootstrapTests(unittest.TestCase):
    def setUp(self) -> None:
        self._home = tempfile.TemporaryDirectory()
        self._environment = patch.dict(os.environ, {"NAVI_HOME": self._home.name})
        self._environment.start()

    def tearDown(self) -> None:
        self._environment.stop()
        self._home.cleanup()

    def test_build_runtime_discovers_mcp_tools_and_closes_provider(self) -> None:
        mcp_tool = FunctionTool(
            name="mcp__files__read",
            description="Read a remote file.",
            handler=lambda: ToolResult.ok(name="mcp__files__read", content="ok"),
        )
        registration = ToolRegistration(
            tool=mcp_tool,
            toolsets=("mcp",),
            source="mcp:files",
        )
        with patch("navi_agent.app.bootstrap.SQLiteSessionStore"):
            with patch("navi_agent.app.bootstrap.setup_logging"):
                with patch("navi_agent.app.bootstrap.build_tool_registry") as registry:
                    with patch("navi_agent.app.bootstrap.MCPToolProvider") as provider_cls:
                        provider_cls.return_value.load_tools.return_value = (registration,)
                        with patch(
                            "navi_agent.app.bootstrap.MCPSettings.from_sources",
                            return_value=MCPSettings(),
                        ):
                            runtime = build_runtime(
                                model_settings=ModelSettings(model="demo", api_key="x"),
                                runtime_settings=RuntimeSettings(max_iterations=3),
                            )

        registrations = registry.call_args.args[0]
        self.assertIn(registration, registrations)
        runtime.close()
        runtime.close()
        provider_cls.return_value.close.assert_called_once_with()

    def test_build_runtime_wires_transport_session_store_and_iterations(self) -> None:
        model_settings = ModelSettings(
            model="gpt-4o-mini",
            api_key="test-key",
            base_url="https://example.com/v1",
            context_limit_tokens=128000,
        )
        runtime_settings = RuntimeSettings(max_iterations=12)

        with patch("navi_agent.app.bootstrap.build_transport") as build_transport_mock:
            with patch("navi_agent.app.bootstrap.SQLiteSessionStore") as store_cls:
                    with patch("navi_agent.app.bootstrap.setup_logging") as setup_logging_mock:
                        with patch("navi_agent.app.bootstrap.build_tool_registry") as build_registry_mock:
                            runtime = build_runtime(model_settings, runtime_settings)

        build_transport_mock.assert_called_once_with(model_settings)
        store_cls.assert_called_once()
        setup_logging_mock.assert_called_once()
        build_registry_mock.assert_called_once()
        self.assertEqual(runtime._max_iterations, 12)
        self.assertEqual(runtime._context_engine._threshold_tokens, 93000)

    def test_build_runtime_reads_defaults_from_env(self) -> None:
        with patch.dict(
            os.environ,
            {
                "NAVI_MODEL": "gpt-4o-mini",
                "NAVI_API_KEY": "test-key",
                "NAVI_HOME": self._home.name,
            },
            clear=True,
        ):
            with patch("navi_agent.app.bootstrap.build_transport") as build_transport_mock:
                with patch("navi_agent.app.bootstrap.SQLiteSessionStore") as store_cls:
                    with patch("navi_agent.app.bootstrap.setup_logging") as setup_logging_mock:
                        with patch("navi_agent.app.bootstrap.build_tool_registry") as build_registry_mock:
                            build_runtime()

        build_transport_mock.assert_called_once()
        store_cls.assert_called_once()
        setup_logging_mock.assert_called_once()
        build_registry_mock.assert_called_once()

    def test_build_runtime_auto_approves_read_only_bash(self) -> None:
        runtime_settings = RuntimeSettings(max_iterations=3)

        with patch("navi_agent.app.bootstrap.SQLiteSessionStore"):
            with patch("navi_agent.app.bootstrap.setup_logging"):
                runtime = build_runtime(
                    model_settings=ModelSettings(model="demo", api_key="x"),
                    runtime_settings=runtime_settings,
                )

        result = runtime._tool_registry.dispatch(
            [ToolCall(id="tc1", name="bash", arguments={"command": "pwd"})],
            context=ToolContext(session_id="s1", user_id="u1", iteration=1),
        )

        self.assertEqual(result[0].status, "success")
        self.assertIn("exit_code: 0", result[0].content)

    def test_build_runtime_passes_approval_provider_to_default_registry(self) -> None:
        provider = AutoApproveApprovalProvider()

        with patch("navi_agent.app.bootstrap.SQLiteSessionStore"):
            with patch("navi_agent.app.bootstrap.setup_logging"):
                with patch("navi_agent.app.bootstrap.BuiltinToolProvider") as builtin_cls:
                    builtin_cls.return_value.load_tools.return_value = ()
                    with patch("navi_agent.app.bootstrap.build_tool_registry") as build_registry_mock:
                        runtime = build_runtime(
                            model_settings=ModelSettings(model="demo", api_key="x"),
                            runtime_settings=RuntimeSettings(max_iterations=3),
                            approval_provider=provider,
                        )

        _, kwargs = build_registry_mock.call_args
        self.assertIs(kwargs["approval_provider"], provider)
        provider_kwargs = builtin_cls.call_args.kwargs
        self.assertIsInstance(provider_kwargs["memory_store"], FileMemoryStore)
        self.assertIsInstance(provider_kwargs["skill_store"], FileSkillStore)
        self.assertIs(
            provider_kwargs["background_task_manager"], runtime._background_task_manager
        )

    def test_build_runtime_passes_workspace_roots_to_registry_and_prompt(self) -> None:
        with tempfile.TemporaryDirectory() as workspace, tempfile.TemporaryDirectory() as added:
            with patch("navi_agent.app.bootstrap.SQLiteSessionStore"):
                with patch("navi_agent.app.bootstrap.setup_logging"):
                    with patch("navi_agent.app.bootstrap.BuiltinToolProvider") as builtin_cls:
                        builtin_cls.return_value.load_tools.return_value = ()
                        runtime = build_runtime(
                            model_settings=ModelSettings(model="demo", api_key="x"),
                            runtime_settings=RuntimeSettings(max_iterations=3),
                            workspace_root=Path(workspace),
                            additional_workspace_roots=[Path(added)],
                        )

        kwargs = builtin_cls.call_args.kwargs
        self.assertEqual(kwargs["root"], Path(workspace).resolve())
        self.assertEqual(kwargs["additional_roots"], (Path(added).resolve(),))
        prompt = runtime._prompt_builder.build_run_system_message(
            user_id="u1",
            user_message="inspect workspace",
        )
        self.assertIn(f"Primary workspace: {Path(workspace).resolve()}", prompt.content)
        self.assertIn(str(Path(added).resolve()), prompt.content)

    def test_build_runtime_uses_composite_trace_store_when_langfuse_enabled(self) -> None:
        with patch("navi_agent.app.bootstrap.SQLiteSessionStore"):
            with patch("navi_agent.app.bootstrap.setup_logging"):
                with patch(
                    "navi_agent.app.bootstrap.LangfuseSettings.from_sources",
                    return_value=LangfuseSettings(enabled=True, public_key="pk", secret_key="sk"),
                ):
                    with patch(
                        "navi_agent.app.bootstrap.LangfuseTraceExporter.from_settings",
                        return_value=object(),
                    ):
                        runtime = build_runtime(
                            model_settings=ModelSettings(model="demo", api_key="x"),
                            runtime_settings=RuntimeSettings(max_iterations=3),
                        )

        self.assertIsInstance(runtime._trace_store, CompositeTraceStore)

    def test_build_runtime_falls_back_to_jsonl_trace_store_when_exporter_init_fails(self) -> None:
        with patch("navi_agent.app.bootstrap.SQLiteSessionStore"):
            with patch("navi_agent.app.bootstrap.setup_logging"):
                with patch(
                    "navi_agent.app.bootstrap.LangfuseSettings.from_sources",
                    return_value=LangfuseSettings(enabled=True, public_key="pk", secret_key="sk"),
                ):
                    with patch(
                        "navi_agent.app.bootstrap.LangfuseTraceExporter.from_settings",
                        side_effect=RuntimeError("boom"),
                    ):
                        runtime = build_runtime(
                            model_settings=ModelSettings(model="demo", api_key="x"),
                            runtime_settings=RuntimeSettings(max_iterations=3),
                        )

        self.assertIsInstance(runtime._trace_store, JsonlTraceStore)

    def test_build_application_wires_evolution_stores(self) -> None:
        with patch("navi_agent.app.bootstrap.build_runtime") as build_runtime_mock:
            app = build_application(
                model_settings=ModelSettings(model="demo", api_key="x"),
                runtime_settings=RuntimeSettings(max_iterations=3),
            )

        build_runtime_mock.assert_called_once()
        self.assertIsInstance(app._candidate_store, JsonlCandidateStore)
        self.assertIsInstance(app._eval_case_store, JsonlEvalCaseStore)
        self.assertIsInstance(app._prompt_overlay_store, PromptOverlayStore)

    def test_build_application_merges_prompt_overlay_into_default_prompt(self) -> None:
        with patch("navi_agent.app.bootstrap.build_runtime") as build_runtime_mock:
            with patch("navi_agent.app.bootstrap.PromptOverlayStore") as overlay_cls:
                overlay_cls.return_value.get.return_value = "overlay prompt"
                app = build_application(
                    model_settings=ModelSettings(model="demo", api_key="x"),
                    runtime_settings=RuntimeSettings(max_iterations=3),
                    default_system_prompt="base prompt",
                    staged_prompt_overlay="staged prompt",
                )

        self.assertEqual(
            app._default_system_prompt,
            "base prompt\n\noverlay prompt\n\nstaged prompt",
        )
        build_runtime_mock.assert_called_once()


if __name__ == "__main__":
    unittest.main()
