from __future__ import annotations

import argparse
from uuid import uuid4

from navi_agent.app import AppRequest
from navi_agent.banner import render_banner
from navi_agent.bootstrap import build_application
from navi_agent.doctor import run_doctor
from navi_agent.evolution import (
    EvolutionReportStore,
    EvolutionReportWriter,
    PromptOverlayStore,
    ReviewLoopService,
)
from navi_agent.paths import get_evolution_reports_dir
from navi_agent.paths import get_prompt_overlay_path
from navi_agent.paths import get_prompt_overlay_snapshots_dir
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
    parser.add_argument("--banner", action="store_true")
    parser.add_argument("--interactive", action="store_true")
    parser.add_argument("--doctor", action="store_true")
    parser.add_argument("--smoke")
    parser.add_argument("--workflow")
    parser.add_argument("--compare-workflow")
    parser.add_argument("--evolution-run")
    parser.add_argument("--evolution-status", action="store_true")
    parser.add_argument("--candidate-id")
    parser.add_argument(
        "--candidate-status",
        choices=[
            "pending",
            "accepted",
            "rejected",
            "applied",
            "verified",
            "no_improvement",
            "regressed_after_apply",
            "superseded",
            "archived",
            "all",
        ],
        default="all",
    )
    parser.add_argument("--accept-candidate", action="store_true")
    parser.add_argument("--reject-candidate", action="store_true")
    parser.add_argument("--apply-candidate", action="store_true")
    parser.add_argument("--apply-candidate-run", action="store_true")
    parser.add_argument("--supersede-candidate", action="store_true")
    parser.add_argument("--archive-candidate", action="store_true")
    parser.add_argument("--candidate-note")
    parser.add_argument("--list-candidates", action="store_true")
    parser.add_argument("--list-workflow-samples", action="store_true")
    parser.add_argument("--prompt-overlay-status", action="store_true")
    parser.add_argument("--show-prompt-overlay", action="store_true")
    parser.add_argument("--list-prompt-overlay-entries", action="store_true")
    parser.add_argument("--list-prompt-overlay-snapshots", action="store_true")
    parser.add_argument("--rollback-prompt-overlay")
    parser.add_argument("--review-loop", action="store_true")
    parser.add_argument("--candidate-triage", action="store_true")
    parser.add_argument("--candidate-queue", action="store_true")
    parser.add_argument("--candidate-work-items", action="store_true")
    parser.add_argument("--list-smoke-tasks", action="store_true")
    parser.add_argument("--list-smoke-workflows", action="store_true")
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    if args.banner:
        print(render_banner())
        return 0
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
    if args.apply_candidate_run:
        if not args.candidate_id:
            parser.error("--candidate-id is required for --apply-candidate-run")
        return _run_candidate_apply_workflow(
            candidate_id=args.candidate_id,
            user_id=args.user_id,
            session_id=args.session_id,
            system_prompt=args.system_prompt,
            review_note=args.candidate_note,
        )
    candidate_action = _candidate_action_from_args(args)
    if candidate_action is not None:
        app = build_application(
            default_system_prompt=args.system_prompt,
            approval_provider=CliApprovalProvider(),
        )
        if not args.candidate_id:
            parser.error("--candidate-id is required for candidate status updates")
        if candidate_action == "applied":
            updated = app.apply_candidate(
                args.candidate_id,
                review_note=args.candidate_note,
            )
        else:
            updated = app.update_candidate_status(
                args.candidate_id,
                candidate_action,
                review_note=args.candidate_note,
            )
        if updated is None:
            if candidate_action == "applied":
                print(f"candidate cannot be applied: {args.candidate_id}")
            else:
                print(f"candidate not found: {args.candidate_id}")
            return 1
        print(f"candidate_id: {updated.candidate_id}")
        print(f"candidate_status: {updated.status}")
        print(f"candidate_target: {updated.target}")
        if updated.review_note:
            print(f"candidate_note: {updated.review_note}")
        return 0
    if args.list_candidates:
        app = build_application(
            default_system_prompt=args.system_prompt,
            approval_provider=CliApprovalProvider(),
        )
        candidates = app.list_candidates(
            limit=10,
            status=None if args.candidate_status == "all" else args.candidate_status,
        )
        for candidate in candidates:
            print(
                f"{candidate.candidate_id} [{candidate.status}] "
                f"{candidate.target}: {candidate.summary}"
            )
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
    if args.prompt_overlay_status:
        overlay = PromptOverlayStore(get_prompt_overlay_path())
        info = overlay.describe()
        print(f"prompt_overlay_path: {info['path']}")
        print(f"prompt_overlay_exists: {info['exists']}")
        print(f"prompt_overlay_candidate_count: {info['candidate_count']}")
        if info["candidate_ids"]:
            print("prompt_overlay_candidate_ids:")
            for candidate_id in info["candidate_ids"]:
                print(f"- {candidate_id}")
        if info["workflow_names"]:
            print("prompt_overlay_workflow_names:")
            for workflow_name in info["workflow_names"]:
                print(f"- {workflow_name}")
        if info["source_session_ids"]:
            print("prompt_overlay_source_session_ids:")
            for session_id in info["source_session_ids"]:
                print(f"- {session_id}")
        if info["replay_session_ids"]:
            print("prompt_overlay_replay_session_ids:")
            for session_id in info["replay_session_ids"]:
                print(f"- {session_id}")
        return 0
    if args.show_prompt_overlay:
        overlay = PromptOverlayStore(get_prompt_overlay_path())
        text = overlay.get()
        if text is None:
            print("prompt overlay is empty")
            return 0
        print(text)
        return 0
    if args.list_prompt_overlay_entries:
        overlay = PromptOverlayStore(get_prompt_overlay_path())
        grouped = overlay.list_entries_by_workflow()
        if not grouped:
            print("no prompt overlay entries")
            return 0
        for workflow_name in sorted(grouped):
            print(f"workflow: {workflow_name}")
            for entry in grouped[workflow_name]:
                print(
                    f"- {entry.candidate_id} [{entry.status or 'unknown'}] "
                    f"{entry.target or 'unknown'}: {entry.summary or ''}".rstrip()
                )
                if entry.step_name:
                    print(f"  step: {entry.step_name}")
                if entry.source_session_id:
                    print(f"  source_session_id: {entry.source_session_id}")
                if entry.replay_session_id:
                    print(f"  replay_session_id: {entry.replay_session_id}")
        return 0
    if args.list_prompt_overlay_snapshots:
        overlay = PromptOverlayStore(
            get_prompt_overlay_path(),
            get_prompt_overlay_snapshots_dir(),
        )
        snapshots = overlay.list_snapshots()
        if not snapshots:
            print("no prompt overlay snapshots")
            return 0
        for snapshot in snapshots:
            suffix = f" candidate={snapshot.candidate_id}" if snapshot.candidate_id else ""
            print(f"{snapshot.snapshot_id}: {snapshot.path}{suffix}")
        return 0
    if args.rollback_prompt_overlay:
        overlay = PromptOverlayStore(
            get_prompt_overlay_path(),
            get_prompt_overlay_snapshots_dir(),
        )
        text = overlay.rollback(args.rollback_prompt_overlay)
        if text is None:
            print(f"prompt overlay snapshot not found: {args.rollback_prompt_overlay}")
            return 1
        print(f"rolled back prompt overlay to {args.rollback_prompt_overlay}")
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
        print(f"active_candidate_count: {summary.active_candidate_count}")
        print(f"pending_candidate_count: {summary.pending_candidate_count}")
        print(f"accepted_candidate_count: {summary.accepted_candidate_count}")
        print(f"rejected_candidate_count: {summary.rejected_candidate_count}")
        print(f"applied_candidate_count: {summary.applied_candidate_count}")
        print(f"verified_candidate_count: {summary.verified_candidate_count}")
        print(f"no_improvement_candidate_count: {summary.no_improvement_candidate_count}")
        print(f"regressed_after_apply_candidate_count: {summary.regressed_after_apply_candidate_count}")
        print(f"superseded_candidate_count: {summary.superseded_candidate_count}")
        print(f"archived_candidate_count: {summary.archived_candidate_count}")
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
            if latest_report.candidate_status:
                print(f"latest_candidate_status: {latest_report.candidate_status}")
        overlay_info = PromptOverlayStore(get_prompt_overlay_path()).describe()
        print(f"prompt_overlay_candidate_count: {overlay_info['candidate_count']}")
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
        print(f"active_candidate_count: {summary.active_candidate_count}")
        print(f"pending_candidate_count: {summary.pending_candidate_count}")
        print(f"accepted_candidate_count: {summary.accepted_candidate_count}")
        print(f"rejected_candidate_count: {summary.rejected_candidate_count}")
        print(f"applied_candidate_count: {summary.applied_candidate_count}")
        print(f"verified_candidate_count: {summary.verified_candidate_count}")
        print(f"no_improvement_candidate_count: {summary.no_improvement_candidate_count}")
        print(f"regressed_after_apply_candidate_count: {summary.regressed_after_apply_candidate_count}")
        print(f"superseded_candidate_count: {summary.superseded_candidate_count}")
        print(f"archived_candidate_count: {summary.archived_candidate_count}")
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
    if args.candidate_triage:
        app = build_application(
            default_system_prompt=args.system_prompt,
            approval_provider=CliApprovalProvider(),
        )
        summary = ReviewLoopService().summarize(
            candidates=app.list_candidates(limit=50),
            workflow_samples=app.list_workflow_samples(limit=50),
        )
        print(f"candidate_count: {summary.candidate_count}")
        print(f"pending_candidate_count: {summary.pending_candidate_count}")
        if summary.pending_targets:
            print("pending_targets:")
            for target, count in summary.pending_targets:
                print(f"- {target}: {count}")
        if summary.candidates_by_target:
            print("candidate_buckets:")
            for target in sorted(summary.candidates_by_target):
                print(f"{target}:")
                for candidate in summary.candidates_by_target[target][:5]:
                    print(
                        f"- {candidate.candidate_id} [{candidate.status}] {candidate.summary}"
                    )
        print(f"recommendation: {summary.recommendation}")
        return 0
    if args.candidate_queue:
        app = build_application(
            default_system_prompt=args.system_prompt,
            approval_provider=CliApprovalProvider(),
        )
        summary = ReviewLoopService().summarize(
            candidates=app.list_candidates(limit=50),
            workflow_samples=app.list_workflow_samples(limit=50),
        )
        print(f"pending_candidate_count: {summary.pending_candidate_count}")
        if not summary.pending_queue:
            print("candidate queue is empty")
            return 0
        print("candidate_queue:")
        for candidate in summary.pending_queue[:10]:
            metadata = candidate.metadata or {}
            workflow_name = metadata.get("workflow_name", "unknown-workflow")
            workflow_status = metadata.get("workflow_status", "unknown")
            workflow_score_delta = metadata.get("workflow_score_delta", 0.0)
            task_name = metadata.get("task_name", "unknown-step")
            print(
                f"- {candidate.candidate_id} [{candidate.target}] {candidate.summary}"
            )
            print(
                f"  workflow={workflow_name} status={workflow_status} "
                f"workflow_score_delta={workflow_score_delta} step={task_name}"
            )
        print(f"recommendation: {summary.recommendation}")
        return 0
    if args.candidate_work_items:
        app = build_application(
            default_system_prompt=args.system_prompt,
            approval_provider=CliApprovalProvider(),
        )
        summary = ReviewLoopService().summarize(
            candidates=app.list_candidates(limit=50),
            workflow_samples=app.list_workflow_samples(limit=50),
        )
        print(f"pending_candidate_count: {summary.pending_candidate_count}")
        if not summary.pending_work_items:
            print("candidate work items are empty")
            return 0
        print("candidate_work_items:")
        for item in summary.pending_work_items[:10]:
            print(f"- {item['candidate_id']} [{item['target']}] {item['summary']}")
            print(
                "  "
                f"workflow={item['workflow_name'] or 'unknown-workflow'} "
                f"status={item['workflow_status'] or 'unknown'} "
                f"workflow_score_delta={item['workflow_score_delta']}"
            )
            print(
                "  "
                f"step={item['task_name'] or 'unknown-step'} "
                f"step_score_delta={item['step_score_delta']}"
            )
            if item["source_trace_id"] or item["replay_trace_id"]:
                print(
                    "  "
                    f"source_trace_id={item['source_trace_id'] or '-'} "
                    f"replay_trace_id={item['replay_trace_id'] or '-'}"
                )
            if item["source_session_id"] or item["replay_session_id"]:
                print(
                    "  "
                    f"source_session_id={item['source_session_id'] or '-'} "
                    f"replay_session_id={item['replay_session_id'] or '-'}"
                )
            if item["signals"]:
                print(f"  signals={','.join(item['signals'])}")
            print(f"  rationale={item['rationale']}")
        print(f"recommendation: {summary.recommendation}")
        return 0
    if (
        not args.interactive
        and not args.smoke
        and not args.workflow
        and not args.compare_workflow
        and not args.evolution_run
        and not args.evolution_status
        and not args.prompt_overlay_status
        and not args.show_prompt_overlay
        and not args.list_prompt_overlay_entries
        and not args.list_prompt_overlay_snapshots
        and not args.rollback_prompt_overlay
        and not args.review_loop
        and not args.candidate_triage
        and not args.candidate_queue
        and not args.candidate_work_items
        and not args.apply_candidate_run
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


def _candidate_action_from_args(args) -> str | None:
    if args.apply_candidate_run and (
        args.accept_candidate or args.reject_candidate or args.apply_candidate or args.supersede_candidate or args.archive_candidate
    ):
        raise SystemExit(
            "--apply-candidate-run cannot be combined with candidate status mutation flags"
        )
    actions = [
        ("accepted", bool(args.accept_candidate)),
        ("rejected", bool(args.reject_candidate)),
        ("applied", bool(args.apply_candidate)),
        ("superseded", bool(args.supersede_candidate)),
        ("archived", bool(args.archive_candidate)),
    ]
    selected = [status for status, enabled in actions if enabled]
    if not selected:
        return None
    if len(selected) > 1:
        raise SystemExit("Only one candidate status mutation flag may be set")
    return selected[0]


def _run_candidate_apply_workflow(
    *,
    candidate_id: str,
    user_id: str,
    session_id: str | None,
    system_prompt: str | None,
    review_note: str | None,
) -> int:
    source_app = build_application(
        default_system_prompt=system_prompt,
        approval_provider=CliApprovalProvider(),
    )
    candidate = source_app.get_candidate(candidate_id)
    if candidate is None:
        print(f"candidate not found: {candidate_id}")
        return 1
    if candidate.target != "prompt":
        print(f"candidate cannot be applied as a workflow run: {candidate_id}")
        return 1
    workflow_name = (candidate.metadata or {}).get("workflow_name")
    if not workflow_name:
        print(f"candidate has no workflow context: {candidate_id}")
        return 1
    source_result = run_smoke_workflow(
        app=source_app,
        workflow_name=workflow_name,
        user_id=user_id,
        session_id=session_id,
        system_prompt=system_prompt,
    )
    applied = source_app.apply_candidate(
        candidate_id,
        review_note=review_note or "applied prompt overlay and ran workflow validation",
    )
    if applied is None:
        print(f"candidate cannot be applied: {candidate_id}")
        return 1
    rerun_app = build_application(
        default_system_prompt=system_prompt,
        approval_provider=CliApprovalProvider(),
    )
    replay_result = run_smoke_workflow(
        app=rerun_app,
        workflow_name=workflow_name,
        user_id=user_id,
        session_id=(session_id or source_result.session_id) + f":candidate:{candidate_id[:8]}",
        system_prompt=system_prompt,
    )
    comparison, report_dir = _finalize_evolution_comparison(
        app=rerun_app,
        source=source_result,
        replay=replay_result,
    )
    outcome_status = _candidate_outcome_status(comparison.sample.status)
    updated = rerun_app.update_candidate_status(
        candidate_id,
        outcome_status,
        review_note=f"workflow={workflow_name} score_delta={comparison.score_delta} report={report_dir}",
    )
    print(f"candidate_id: {applied.candidate_id}")
    print(f"candidate_status: {updated.status if updated is not None else applied.status}")
    print(f"workflow: {workflow_name}")
    print(f"candidate_outcome: {comparison.sample.status}")
    print(f"candidate_report_path: {report_dir}")
    _print_evolution_comparison(comparison=comparison, report_dir=report_dir)
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
    comparison, report_dir = _finalize_evolution_comparison(
        app=app,
        source=source,
        replay=replay,
    )
    _print_evolution_comparison(comparison=comparison, report_dir=report_dir)
    return 0


def _finalize_evolution_comparison(
    *,
    app,
    source,
    replay,
):
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
    return comparison, report_dir


def _print_evolution_comparison(*, comparison, report_dir) -> None:
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


def _candidate_outcome_status(sample_status: str) -> str:
    if sample_status == "improved":
        return "verified"
    if sample_status == "unchanged":
        return "no_improvement"
    if sample_status == "regressed":
        return "regressed_after_apply"
    return "applied"


def _run_interactive(
    *,
    app,
    user_id: str,
    session_id: str,
    system_prompt: str | None,
    first_message: str | None = None,
) -> int:
    print(render_banner())
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
