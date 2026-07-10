import os
import unittest
from unittest.mock import patch

from navi_agent.bootstrap import build_runtime
from navi_agent.config import LangfuseSettings, ModelSettings, RuntimeSettings
from navi_agent.runtime import ToolCall, ToolContext
from navi_agent.runtime.approval import AutoApproveApprovalProvider
from navi_agent.telemetry import CompositeTraceStore, JsonlTraceStore
from navi_agent.evolution import JsonlCandidateStore, JsonlEvalCaseStore, PromptOverlayStore
from navi_agent.bootstrap import build_application


class BootstrapTests(unittest.TestCase):
    def test_build_runtime_wires_transport_session_store_and_iterations(self) -> None:
        model_settings = ModelSettings(
            model="gpt-4o-mini",
            api_key="test-key",
            base_url="https://example.com/v1",
        )
        runtime_settings = RuntimeSettings(max_iterations=12)

        with patch("navi_agent.bootstrap.build_transport") as build_transport_mock:
            with patch("navi_agent.bootstrap.SQLiteSessionStore") as store_cls:
                    with patch("navi_agent.bootstrap.setup_logging") as setup_logging_mock:
                        with patch("navi_agent.bootstrap.build_default_tool_registry") as build_registry_mock:
                            runtime = build_runtime(model_settings, runtime_settings)

        build_transport_mock.assert_called_once_with(model_settings)
        store_cls.assert_called_once()
        setup_logging_mock.assert_called_once()
        build_registry_mock.assert_called_once()
        self.assertEqual(runtime._max_iterations, 12)

    def test_build_runtime_reads_defaults_from_env(self) -> None:
        with patch.dict(
            os.environ,
            {
                "NAVI_MODEL": "gpt-4o-mini",
                "NAVI_API_KEY": "test-key",
                "NAVI_HOME": "/tmp/navi-home",
            },
            clear=True,
        ):
            with patch("navi_agent.bootstrap.build_transport") as build_transport_mock:
                with patch("navi_agent.bootstrap.SQLiteSessionStore") as store_cls:
                    with patch("navi_agent.bootstrap.setup_logging") as setup_logging_mock:
                        with patch("navi_agent.bootstrap.build_default_tool_registry") as build_registry_mock:
                            build_runtime()

        build_transport_mock.assert_called_once()
        store_cls.assert_called_once()
        setup_logging_mock.assert_called_once()
        build_registry_mock.assert_called_once()

    def test_build_runtime_uses_default_sensitive_tool_policy(self) -> None:
        runtime_settings = RuntimeSettings(max_iterations=3)

        with patch("navi_agent.bootstrap.SQLiteSessionStore"):
            with patch("navi_agent.bootstrap.setup_logging"):
                runtime = build_runtime(
                    model_settings=ModelSettings(model="demo", api_key="x"),
                    runtime_settings=runtime_settings,
                )

        result = runtime._tool_registry.dispatch(
            [ToolCall(id="tc1", name="bash", arguments={"command": "pwd"})],
            context=ToolContext(session_id="s1", user_id="u1", iteration=1),
        )

        self.assertEqual(result[0].status, "error")
        self.assertIn("approval", result[0].content)
        self.assertTrue(result[0].structured_content["approval_required"])

    def test_build_runtime_passes_approval_provider_to_default_registry(self) -> None:
        provider = AutoApproveApprovalProvider()

        with patch("navi_agent.bootstrap.SQLiteSessionStore"):
            with patch("navi_agent.bootstrap.setup_logging"):
                with patch("navi_agent.bootstrap.build_default_tool_registry") as build_registry_mock:
                    build_runtime(
                        model_settings=ModelSettings(model="demo", api_key="x"),
                        runtime_settings=RuntimeSettings(max_iterations=3),
                        approval_provider=provider,
                    )

        _, kwargs = build_registry_mock.call_args
        self.assertIs(kwargs["approval_provider"], provider)

    def test_build_runtime_uses_composite_trace_store_when_langfuse_enabled(self) -> None:
        with patch("navi_agent.bootstrap.SQLiteSessionStore"):
            with patch("navi_agent.bootstrap.setup_logging"):
                with patch(
                    "navi_agent.bootstrap.LangfuseSettings.from_sources",
                    return_value=LangfuseSettings(enabled=True, public_key="pk", secret_key="sk"),
                ):
                    with patch(
                        "navi_agent.bootstrap.LangfuseTraceExporter.from_settings",
                        return_value=object(),
                    ):
                        runtime = build_runtime(
                            model_settings=ModelSettings(model="demo", api_key="x"),
                            runtime_settings=RuntimeSettings(max_iterations=3),
                        )

        self.assertIsInstance(runtime._trace_store, CompositeTraceStore)

    def test_build_runtime_falls_back_to_jsonl_trace_store_when_exporter_init_fails(self) -> None:
        with patch("navi_agent.bootstrap.SQLiteSessionStore"):
            with patch("navi_agent.bootstrap.setup_logging"):
                with patch(
                    "navi_agent.bootstrap.LangfuseSettings.from_sources",
                    return_value=LangfuseSettings(enabled=True, public_key="pk", secret_key="sk"),
                ):
                    with patch(
                        "navi_agent.bootstrap.LangfuseTraceExporter.from_settings",
                        side_effect=RuntimeError("boom"),
                    ):
                        runtime = build_runtime(
                            model_settings=ModelSettings(model="demo", api_key="x"),
                            runtime_settings=RuntimeSettings(max_iterations=3),
                        )

        self.assertIsInstance(runtime._trace_store, JsonlTraceStore)

    def test_build_application_wires_evolution_stores(self) -> None:
        with patch("navi_agent.bootstrap.build_runtime") as build_runtime_mock:
            app = build_application(
                model_settings=ModelSettings(model="demo", api_key="x"),
                runtime_settings=RuntimeSettings(max_iterations=3),
            )

        build_runtime_mock.assert_called_once()
        self.assertIsInstance(app._candidate_store, JsonlCandidateStore)
        self.assertIsInstance(app._eval_case_store, JsonlEvalCaseStore)
        self.assertIsInstance(app._prompt_overlay_store, PromptOverlayStore)

    def test_build_application_merges_prompt_overlay_into_default_prompt(self) -> None:
        with patch("navi_agent.bootstrap.build_runtime") as build_runtime_mock:
            with patch("navi_agent.bootstrap.PromptOverlayStore") as overlay_cls:
                overlay_cls.return_value.get.return_value = "overlay prompt"
                app = build_application(
                    model_settings=ModelSettings(model="demo", api_key="x"),
                    runtime_settings=RuntimeSettings(max_iterations=3),
                    default_system_prompt="base prompt",
                )

        self.assertEqual(app._default_system_prompt, "base prompt\n\noverlay prompt")
        build_runtime_mock.assert_called_once()


if __name__ == "__main__":
    unittest.main()
