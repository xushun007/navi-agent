from __future__ import annotations

import argparse
from uuid import uuid4

from navi_agent.app import AppRequest
from navi_agent.bootstrap import build_application
from navi_agent.doctor import run_doctor
from navi_agent.evolution import EvolutionReportStore, EvolutionReportWriter, ReviewLoopService
from navi_agent.paths import get_evolution_reports_dir
from navi_agent.runtime import CliApprovalProvider
from navi_agent.smoke import (
    compare_smoke_workflow_results,
    list_smoke_tasks,
    list_smoke_workflows,
    replay_smoke_workflow,
    run_smoke_task,
    run_smoke_workflow,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="navi-agent")
    parser.add_argument("message", nargs="?")
    parser.add_argument("--user-id", default="local-user")
    parser.add_argument("--session-id")
    parser.add_argument("--system-prompt")
    parser.add_argument("--interactive", action="store_true")
    parser.add_argument("--doctor", action="store_true")
    parser.add_argument("--smoke")
    parser.add_argument("--workflow")
    parser.add_argument("--compare-workflow")
    parser.add_argument("--evolution-run")
    parser.add_argument("--evolution-status", action="store_true")
    parser.add_argument("--list-candidates", action="store_true")
    parser.add_argument("--list-workflow-samples", action="store_true")
    parser.add_argument("--review-loop", action="store_true")
    parser.add_argument("--list-smoke-tasks", action="store_true")
    parser.add_argument("--list-smoke-workflows", action="store_true")
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    if args.doctor:
        return run_doctor()
    if args.list_smoke_tasks:
        for task in list_smoke_tasks():
            print(f"{task.name}: {task.description}")
        return 0
    if args.list_smoke_workflows:
        for workflow in list_smoke_workflows():
            print(f"{workflow.name}: {workflow.description}")
        return 0
    if args.list_candidates:
        app = build_application(
            default_system_prompt=args.system_prompt,
            approval_provider=CliApprovalProvider(),
        )
        for candidate in app.list_candidates(limit=10):
            print(f"{candidate.target}: {candidate.summary}")
        return 0
    if args.list_workflow_samples:
        app = build_application(
            default_system_prompt=args.system_prompt,
            approval_provider=CliApprovalProvider(),
        )
        for sample in app.list_workflow_samples(limit=10):
            print(
                f"{sample.workflow_name}: {sample.status} "
                f"(source={sample.source_average_score}, replay={sample.replay_average_score}, delta={sample.score_delta})"
            )
        return 0
    if args.evolution_status:
        app = build_application(
            default_system_prompt=args.system_prompt,
            approval_provider=CliApprovalProvider(),
        )
        summary = ReviewLoopService().summarize(
            candidates=app.list_candidates(limit=50),
            workflow_samples=app.list_workflow_samples(limit=50),
        )
        print(f"evolution_reports_dir: {get_evolution_reports_dir()}")
        print(f"candidate_count: {summary.candidate_count}")
        print(f"workflow_sample_count: {summary.workflow_sample_count}")
        print(f"regressed_count: {summary.regressed_count}")
        print(f"improved_count: {summary.improved_count}")
        print(f"unchanged_count: {summary.unchanged_count}")
        latest_report = EvolutionReportStore(get_evolution_reports_dir()).get_latest()
        if latest_report is not None:
            print(f"latest_report: {latest_report.report_path}")
            print(f"latest_workflow: {latest_report.workflow_name}")
            print(f"latest_status: {latest_report.status}")
            print(f"latest_score_delta: {latest_report.score_delta}")
            if latest_report.candidate_target:
                print(f"latest_candidate_target: {latest_report.candidate_target}")
        print(f"recommendation: {summary.recommendation}")
        return 0
    if args.review_loop:
        app = build_application(
            default_system_prompt=args.system_prompt,
            approval_provider=CliApprovalProvider(),
        )
        summary = ReviewLoopService().summarize(
            candidates=app.list_candidates(limit=50),
            workflow_samples=app.list_workflow_samples(limit=50),
        )
        print(f"candidate_count: {summary.candidate_count}")
        print(f"workflow_sample_count: {summary.workflow_sample_count}")
        print(f"regressed_count: {summary.regressed_count}")
        print(f"improved_count: {summary.improved_count}")
        print(f"unchanged_count: {summary.unchanged_count}")
        if summary.top_candidate_targets:
            print("top_candidate_targets:")
            for target, count in summary.top_candidate_targets:
                print(f"- {target}: {count}")
        if summary.top_regressed_workflows:
            print("top_regressed_workflows:")
            for workflow, count in summary.top_regressed_workflows:
                print(f"- {workflow}: {count}")
        print(f"recommendation: {summary.recommendation}")
        return 0
    if (
        not args.interactive
        and not args.smoke
        and not args.workflow
        and not args.compare_workflow
        and not args.evolution_run
        and not args.evolution_status
        and not args.review_loop
        and not args.message
    ):
        parser.error("message is required unless --interactive is set")

    app = build_application(
        default_system_prompt=args.system_prompt,
        approval_provider=CliApprovalProvider(),
    )
    if args.smoke:
        result = run_smoke_task(
            app=app,
            task_name=args.smoke,
            user_id=args.user_id,
            session_id=args.session_id,
            system_prompt=args.system_prompt,
        )
        print(result.final_response)
        return 0
    if args.workflow:
        workflow_result = run_smoke_workflow(
            app=app,
            workflow_name=args.workflow,
            user_id=args.user_id,
            session_id=args.session_id,
            system_prompt=args.system_prompt,
        )
        print(f"workflow: {workflow_result.workflow.name}")
        print(f"session_id: {workflow_result.session_id}")
        for index, step in enumerate(workflow_result.steps, start=1):
            print(f"[{index}] {step.task_name}")
            if step.trace_id:
                print(f"trace_id: {step.trace_id}")
            print(step.runtime_result.final_response)
        return 0
    if args.compare_workflow or args.evolution_run:
        workflow_name = args.compare_workflow or args.evolution_run
        return _run_evolution_workflow(
            app=app,
            workflow_name=workflow_name,
            user_id=args.user_id,
            session_id=args.session_id,
            system_prompt=args.system_prompt,
        )
    if args.interactive:
        return _run_interactive(
            app=app,
            user_id=args.user_id,
            session_id=args.session_id or uuid4().hex,
            system_prompt=args.system_prompt,
            first_message=args.message,
        )
    result = app.handle(
        AppRequest(
            user_id=args.user_id,
            session_id=args.session_id,
            message=args.message,
            system_prompt=args.system_prompt,
        )
    )
    print(result.final_response)
    return 0


def _run_evolution_workflow(
    *,
    app,
    workflow_name: str,
    user_id: str,
    session_id: str | None,
    system_prompt: str | None,
) -> int:
    source = run_smoke_workflow(
        app=app,
        workflow_name=workflow_name,
        user_id=user_id,
        session_id=session_id,
        system_prompt=system_prompt,
    )
    replay = replay_smoke_workflow(
        app=app,
        workflow_result=source,
        system_prompt=system_prompt,
    )
    comparison = compare_smoke_workflow_results(source, replay)
    app.add_workflow_sample(comparison.sample)
    if comparison.candidate is not None:
        app.add_candidate(comparison.candidate)
    review_summary = ReviewLoopService().summarize(
        candidates=app.list_candidates(limit=50),
        workflow_samples=app.list_workflow_samples(limit=50),
    )
    report_dir = EvolutionReportWriter(get_evolution_reports_dir()).write_workflow_comparison_report(
        comparison=comparison,
        review_summary=review_summary,
    )
    print(f"workflow: {comparison.workflow_name}")
    print(f"source_session_id: {comparison.source_session_id}")
    print(f"replay_session_id: {comparison.replay_session_id}")
    print(f"workflow_status: {comparison.sample.status}")
    print(f"source_average_score: {comparison.source_average_score}")
    print(f"replay_average_score: {comparison.replay_average_score}")
    print(f"score_delta: {comparison.score_delta}")
    print(f"report_path: {report_dir}")
    if comparison.candidate is not None:
        print(f"candidate_target: {comparison.candidate.target}")
        print(f"candidate_summary: {comparison.candidate.summary}")
    for index, step in enumerate(comparison.step_comparisons, start=1):
        print(f"[{index}] {step.task_name}")
        if step.source_step.trace_id:
            print(f"source_trace_id: {step.source_step.trace_id}")
        if step.replay_step.trace_id:
            print(f"replay_trace_id: {step.replay_step.trace_id}")
        print(f"step_score_delta: {step.score_delta}")
    return 0


def _run_interactive(
    *,
    app,
    user_id: str,
    session_id: str,
    system_prompt: str | None,
    first_message: str | None = None,
) -> int:
    print(f"Interactive session: {session_id}")
    print("Type 'exit' or 'quit' to stop.")

    pending_message = first_message
    while True:
        message = pending_message
        pending_message = None
        if message is None:
            try:
                message = input("> ").strip()
            except EOFError:
                print()
                return 0
        if not message:
            continue
        if message.lower() in {"exit", "quit"}:
            return 0
        result = app.handle(
            AppRequest(
                user_id=user_id,
                session_id=session_id,
                message=message,
                system_prompt=system_prompt,
            )
        )
        print(result.final_response)


if __name__ == "__main__":
    raise SystemExit(main())
