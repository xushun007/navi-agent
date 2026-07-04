from __future__ import annotations

import argparse
import json
from uuid import uuid4

from navi_agent.app import AppRequest
from navi_agent.banner import render_banner
from navi_agent.bootstrap import build_application
from navi_agent.config import WeixinGatewaySettings, load_config
from navi_agent.doctor import run_doctor
from navi_agent.evolution import (
    EvalSeedStore,
    EvalSeed,
    EvalSeedReportStore,
    EvalSeedReportWriter,
    IfevalEvaluator,
    IfevalRunStore,
    IfevalRunWriter,
    EvolutionReportStore,
    EvolutionReportWriter,
    PromptOverlayStore,
    ReviewLoopService,
)
from navi_agent.gateway.weixin import (
    ILinkClient,
    ILinkGateway,
    WeixinPairingStore,
)
from navi_agent.paths import get_evolution_reports_dir
from navi_agent.paths import get_eval_seed_reports_dir
from navi_agent.paths import get_eval_seed_path
from navi_agent.paths import get_ifeval_drafts_path
from navi_agent.paths import get_ifeval_reports_dir
from navi_agent.paths import get_prompt_overlay_path
from navi_agent.paths import get_prompt_overlay_snapshots_dir
from navi_agent.paths import get_state_db_path
from navi_agent.runtime import CliApprovalProvider
from navi_agent.runtime import ConversationState
from navi_agent.runtime import SQLiteSessionStore
from navi_agent.healthcheck import (
    compare_healthcheck_workflow_results,
    list_healthcheck_tasks,
    list_healthcheck_workflows,
    replay_healthcheck_workflow,
    run_healthcheck_task,
    run_healthcheck_workflow,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="navi-agent")
    parser.add_argument("message", nargs="?")
    parser.add_argument("--user-id", default="local-user")
    parser.add_argument("--session-id")
    parser.add_argument("--system-prompt")
    parser.add_argument("--banner", action="store_true")
    parser.add_argument("--interactive", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--doctor", action="store_true")
    parser.add_argument("--gateway", choices=["weixin"])
    parser.add_argument("--gateway-pairings", choices=["weixin"])
    parser.add_argument("--approve-gateway-pairing")
    parser.add_argument("--healthcheck")
    parser.add_argument("--workflow")
    parser.add_argument("--compare-workflow")
    parser.add_argument("--evolution-run")
    parser.add_argument("--confirm-eval-case", action="store_true")
    parser.add_argument("--evolution-status", action="store_true")
    parser.add_argument("--curator-status", action="store_true")
    parser.add_argument("--curator-run", action="store_true")
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
    parser.add_argument("--list-eval-cases", action="store_true")
    parser.add_argument("--eval-seed-status", action="store_true")
    parser.add_argument("--list-eval-seeds", action="store_true")
    parser.add_argument("--eval-seed-report", action="store_true")
    parser.add_argument("--ifeval-run", action="store_true")
    parser.add_argument("--ifeval-status", action="store_true")
    parser.add_argument("--ifeval-drafts-status", action="store_true")
    parser.add_argument("--list-ifeval-drafts", action="store_true")
    parser.add_argument("--ifeval-import-session")
    parser.add_argument("--ifeval-import-key", type=int)
    parser.add_argument("--ifeval-import-instruction-id", action="append")
    parser.add_argument("--ifeval-import-kwargs", action="append")
    parser.add_argument("--review-ifeval-draft", action="store_true")
    parser.add_argument("--prompt-overlay-status", action="store_true")
    parser.add_argument("--show-prompt-overlay", action="store_true")
    parser.add_argument("--list-prompt-overlay-entries", action="store_true")
    parser.add_argument("--list-prompt-overlay-snapshots", action="store_true")
    parser.add_argument("--rollback-prompt-overlay")
    parser.add_argument("--review-loop", action="store_true")
    parser.add_argument("--candidate-triage", action="store_true")
    parser.add_argument("--candidate-queue", action="store_true")
    parser.add_argument("--candidate-work-items", action="store_true")
    parser.add_argument("--review-eval-case", action="store_true")
    parser.add_argument("--list-healthcheck-tasks", action="store_true")
    parser.add_argument("--list-healthcheck-workflows", action="store_true")
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    if args.banner:
        print(render_banner())
        return 0
    if args.doctor:
        return run_doctor()
    if args.gateway_pairings:
        return _list_gateway_pairings(args.gateway_pairings)
    if args.approve_gateway_pairing:
        return _approve_gateway_pairing(args.approve_gateway_pairing)
    if args.gateway:
        return _run_gateway(args)
    if args.review_eval_case:
        return _review_eval_case(system_prompt=args.system_prompt)
    if args.list_healthcheck_tasks:
        for task in list_healthcheck_tasks():
            print(f"{task.name}: {task.description}")
        return 0
    if args.list_healthcheck_workflows:
        for workflow in list_healthcheck_workflows():
            print(f"{workflow.name}: {workflow.description}")
        return 0
    if args.curator_run:
        return _run_curator(
            user_id=args.user_id,
            session_id=args.session_id,
            system_prompt=args.system_prompt,
            review_note=args.candidate_note,
            dry_run=args.dry_run,
            confirm_eval_case=args.confirm_eval_case,
        )
    if args.apply_candidate_run:
        if not args.candidate_id:
            parser.error("--candidate-id is required for --apply-candidate-run")
        return _run_candidate_apply_workflow(
            candidate_id=args.candidate_id,
            user_id=args.user_id,
            session_id=args.session_id,
            system_prompt=args.system_prompt,
            review_note=args.candidate_note,
            confirm_eval_case=args.confirm_eval_case,
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
    if args.list_eval_cases:
        app = build_application(
            default_system_prompt=args.system_prompt,
            approval_provider=CliApprovalProvider(),
        )
        for eval_case in app.list_eval_cases(limit=10):
            print(
                f"{eval_case.workflow_name}: {eval_case.status} "
                f"(source={eval_case.source_average_score}, replay={eval_case.replay_average_score}, delta={eval_case.score_delta})"
            )
        return 0
    if args.eval_seed_status:
        return _print_eval_seed_status()
    if args.list_eval_seeds:
        return _list_eval_seeds()
    if args.eval_seed_report:
        return _write_eval_seed_report()
    if args.ifeval_run:
        return _run_ifeval()
    if args.ifeval_status:
        return _print_ifeval_status()
    if args.ifeval_drafts_status:
        return _print_ifeval_drafts_status()
    if args.list_ifeval_drafts:
        return _list_ifeval_drafts()
    if args.ifeval_import_session:
        return _import_ifeval_seed(
            session_id=args.ifeval_import_session,
            seed_key=args.ifeval_import_key,
            instruction_ids=args.ifeval_import_instruction_id or [],
            kwargs_json=args.ifeval_import_kwargs or [],
        )
    if args.review_ifeval_draft:
        return _review_ifeval_draft()
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
    if args.evolution_status or args.curator_status:
        app = build_application(
            default_system_prompt=args.system_prompt,
            approval_provider=CliApprovalProvider(),
        )
        summary = ReviewLoopService().summarize(
            candidates=app.list_candidates(limit=50),
            eval_cases=app.list_eval_cases(limit=50),
        )
        latest_report = EvolutionReportStore(get_evolution_reports_dir()).get_latest()
        overlay_info = PromptOverlayStore(get_prompt_overlay_path()).describe()
        _print_curator_status(
            summary=summary,
            latest_report=latest_report,
            overlay_info=overlay_info,
        )
        return 0
    if args.review_loop:
        app = build_application(
            default_system_prompt=args.system_prompt,
            approval_provider=CliApprovalProvider(),
        )
        summary = ReviewLoopService().summarize(
            candidates=app.list_candidates(limit=50),
            eval_cases=app.list_eval_cases(limit=50),
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
        print(f"eval_case_count: {summary.eval_case_count}")
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
            eval_cases=app.list_eval_cases(limit=50),
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
            eval_cases=app.list_eval_cases(limit=50),
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
            eval_cases=app.list_eval_cases(limit=50),
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
        and not args.healthcheck
        and not args.gateway
        and not args.gateway_pairings
        and not args.approve_gateway_pairing
        and not args.workflow
        and not args.compare_workflow
        and not args.evolution_run
        and not args.evolution_status
        and not args.curator_status
        and not args.curator_run
        and not args.prompt_overlay_status
        and not args.show_prompt_overlay
        and not args.list_prompt_overlay_entries
        and not args.list_prompt_overlay_snapshots
        and not args.rollback_prompt_overlay
        and not args.review_loop
        and not args.candidate_triage
        and not args.candidate_queue
        and not args.candidate_work_items
        and not args.eval_seed_status
        and not args.list_eval_seeds
        and not args.eval_seed_report
        and not args.ifeval_run
        and not args.ifeval_status
        and not args.ifeval_drafts_status
        and not args.list_ifeval_drafts
        and not args.ifeval_import_session
        and not args.review_ifeval_draft
        and not args.apply_candidate_run
        and not args.message
    ):
        parser.error("message is required unless --interactive is set")

    app = build_application(
        default_system_prompt=args.system_prompt,
        approval_provider=CliApprovalProvider(),
    )
    if args.healthcheck:
        result = run_healthcheck_task(
            app=app,
            task_name=args.healthcheck,
            user_id=args.user_id,
            session_id=args.session_id,
            system_prompt=args.system_prompt,
        )
        print(result.final_response)
        return 0
    if args.workflow:
        workflow_result = run_healthcheck_workflow(
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
            confirm_eval_case=args.confirm_eval_case,
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


def _run_gateway(args) -> int:
    if args.gateway == "weixin":
        return _run_weixin_gateway(args)
    print(f"unsupported gateway: {args.gateway}")
    return 1


def _run_weixin_gateway(args) -> int:
    settings = WeixinGatewaySettings.from_sources(load_config())
    token = settings.token
    if not token:
        print("weixin token is required: set gateway.weixin.token")
        return 1
    app = build_application(
        default_system_prompt=args.system_prompt,
        approval_provider=CliApprovalProvider(),
    )
    account_id = settings.account_id
    if not account_id:
        print("weixin account_id is required: set gateway.weixin.account_id")
        return 1
    base_url = settings.base_url
    print(f"weixin_ilink_polling: account_id={account_id} base_url={base_url}")
    ILinkGateway(
        app=app,
        client=ILinkClient(
            token=token,
            account_id=account_id,
            base_url=base_url,
        ),
        account_id=account_id,
        poll_interval_seconds=settings.poll_interval_seconds,
        dm_policy=settings.dm_policy,
        allowed_users=set(settings.allowed_users),
        pairing_store=WeixinPairingStore(),
    ).run_forever()
    return 0


def _list_gateway_pairings(gateway_name: str) -> int:
    if gateway_name == "weixin":
        return _list_weixin_pairings()
    print(f"unsupported gateway: {gateway_name}")
    return 1


def _list_weixin_pairings() -> int:
    store = WeixinPairingStore()
    pending = store.list_pending()
    approved = store.list_approved()
    print(f"pending_weixin_pairings: {len(pending)}")
    for request in pending:
        print(f"- {request.code}: {request.user_id} created_at={request.created_at}")
    print(f"approved_weixin_users: {len(approved)}")
    for user_id in approved:
        print(f"- {user_id}")
    return 0


def _approve_gateway_pairing(code: str) -> int:
    return _approve_weixin_pairing(code)


def _approve_weixin_pairing(code: str) -> int:
    user_id = WeixinPairingStore().approve(code)
    if user_id is None:
        print(f"weixin pairing code not found: {code}")
        return 1
    print(f"approved_weixin_user: {user_id}")
    return 0


def _print_eval_seed_status() -> int:
    store = EvalSeedStore(get_eval_seed_path())
    info = store.describe()
    issues = store.validate()
    print(f"eval_seed_path: {info['path']}")
    print(f"eval_seed_exists: {info['exists']}")
    print(f"eval_seed_count: {info['count']}")
    print(f"eval_seed_passed_count: {info['passed_count']}")
    print(f"eval_seed_failed_count: {info['failed_count']}")
    print(f"eval_seed_pending_count: {info['pending_count']}")
    if info["keys"]:
        print("eval_seed_keys:")
        for key in info["keys"]:
            print(f"- {key}")
    if issues:
        print("eval_seed_issues:")
        for issue in issues:
            print(f"- {issue}")
    return 0


def _list_eval_seeds() -> int:
    store = EvalSeedStore(get_eval_seed_path())
    seeds = store.list_recent(limit=None)
    if not seeds:
        print("no eval seeds found")
        return 0
    for seed in seeds:
        status = "pending" if seed.pass_fail is None else ("pass" if seed.pass_fail else "fail")
        print(f"{seed.key} [{status}] {seed.session_id}: {seed.prompt}")
    return 0


def _write_eval_seed_report() -> int:
    seed_store = EvalSeedStore(get_eval_seed_path())
    report_dir = EvalSeedReportWriter(get_eval_seed_reports_dir()).write_report(seed_store=seed_store)
    record = EvalSeedReportStore(get_eval_seed_reports_dir()).get_latest()
    print(f"eval_seed_report_path: {report_dir}")
    if record is not None:
        print(f"eval_seed_count: {record.count}")
        print(f"eval_seed_pass_rate: {record.pass_rate}")
    return 0


def _run_ifeval() -> int:
    seed_store = EvalSeedStore(get_eval_seed_path())
    seeds = seed_store.list_recent(limit=None)
    if not seeds:
        print("no ifeval seeds found")
        return 0

    app = build_application(approval_provider=CliApprovalProvider())
    evaluator = IfevalEvaluator()
    results = []
    for seed in seeds:
        runtime_result = app.handle(
            AppRequest(
                user_id="ifeval",
                session_id=seed.session_id,
                message=seed.prompt,
                auto_propose_eval_case=False,
            )
        )
        result = evaluator.evaluate(
            key=seed.key,
            session_id=runtime_result.session_id,
            prompt=seed.prompt,
            output=runtime_result.final_response,
            instruction_id_list=seed.instruction_id_list,
            kwargs_list=seed.kwargs,
        )
        results.append(result)
        status = "pass" if result.overall_pass else "fail"
        print(f"{seed.key} [{status}] {seed.session_id}: score={result.score} {result.summary}")

    report_dir = IfevalRunWriter(get_ifeval_reports_dir()).write_run_report(
        seed_store=seed_store,
        results=results,
    )
    passed_count = sum(1 for result in results if result.overall_pass)
    failed_count = len(results) - passed_count
    pass_rate = round(passed_count / len(results), 3) if results else 0.0
    print(f"ifeval_report_path: {report_dir}")
    print(f"ifeval_count: {len(results)}")
    print(f"ifeval_passed_count: {passed_count}")
    print(f"ifeval_failed_count: {failed_count}")
    print(f"ifeval_pass_rate: {pass_rate}")
    return 0


def _print_ifeval_status() -> int:
    report_root = get_ifeval_reports_dir()
    latest = IfevalRunStore(report_root).get_latest()
    print(f"ifeval_report_root: {report_root}")
    if latest is None:
        print("ifeval_latest_report: none")
        return 0
    print(f"ifeval_latest_report_path: {latest.report_path}")
    print(f"ifeval_latest_seed_path: {latest.seed_path}")
    print(f"ifeval_latest_count: {latest.count}")
    print(f"ifeval_latest_passed_count: {latest.passed_count}")
    print(f"ifeval_latest_failed_count: {latest.failed_count}")
    print(f"ifeval_latest_pass_rate: {latest.pass_rate}")
    print(f"ifeval_latest_created_at: {latest.created_at}")
    return 0


def _print_ifeval_drafts_status() -> int:
    store = EvalSeedStore(get_ifeval_drafts_path())
    info = store.describe()
    print(f"ifeval_drafts_path: {info['path']}")
    print(f"ifeval_drafts_exists: {info['exists']}")
    print(f"ifeval_drafts_count: {info['count']}")
    print(f"ifeval_drafts_pending_count: {info['pending_count']}")
    return 0


def _list_ifeval_drafts() -> int:
    store = EvalSeedStore(get_ifeval_drafts_path())
    seeds = store.list_recent(limit=None)
    if not seeds:
        print("no ifeval drafts found")
        return 0
    for seed in seeds:
        print(f"{seed.key}: {seed.session_id}")
        print(f"  prompt: {seed.prompt}")
        print(f"  instructions: {', '.join(seed.instruction_id_list) or 'none'}")
    return 0


def _import_ifeval_seed(
    *,
    session_id: str,
    seed_key: int | None,
    instruction_ids: list[str],
    kwargs_json: list[str],
) -> int:
    if seed_key is None:
        print("--ifeval-import-key is required")
        return 1
    if not instruction_ids:
        print("--ifeval-import-instruction-id is required")
        return 1

    session_store = SQLiteSessionStore(get_state_db_path())
    messages = session_store.snapshot(
        ConversationState(session_id=session_id, user_id="draft-import")
    )
    prompt = next(
        (message.content for message in messages if message.role == "user" and message.content.strip()),
        None,
    )
    output = next(
        (message.content for message in reversed(messages) if message.role == "assistant"),
        None,
    )
    if prompt is None:
        print(f"user prompt not found for session: {session_id}")
        return 1
    if output is None:
        print(f"assistant output not found for session: {session_id}")
        return 1

    kwargs_list: list[dict[str, object]] = []
    for index, instruction_id in enumerate(instruction_ids):
        raw_kwargs = kwargs_json[index] if index < len(kwargs_json) else "{}"
        try:
            parsed_kwargs = json.loads(raw_kwargs)
        except json.JSONDecodeError:
            print(f"invalid kwargs JSON for {instruction_id}: {raw_kwargs}")
            return 1
        if not isinstance(parsed_kwargs, dict):
            print(f"kwargs must be an object for {instruction_id}")
            return 1
        kwargs_list.append(parsed_kwargs)

    seed = EvalSeed(
        key=seed_key,
        prompt=prompt,
        instruction_id_list=list(instruction_ids),
        kwargs=kwargs_list,
        session_id=session_id,
        output=output,
        pass_fail=None,
        notes=f"imported from session {session_id}",
    )
    draft_store = EvalSeedStore(get_ifeval_drafts_path())
    draft_store.append(seed)
    print(f"ifeval_draft_written: {draft_store.path}")
    print(f"ifeval_draft_key: {seed.key}")
    print(f"ifeval_draft_session_id: {seed.session_id}")
    return 0


def _review_ifeval_draft() -> int:
    draft_store = EvalSeedStore(get_ifeval_drafts_path())
    seeds = draft_store.list_recent(limit=None)
    if not seeds:
        print("no ifeval drafts found")
        return 1

    draft = seeds[-1]
    print("ifeval draft review:")
    print(f"draft_key: {draft.key}")
    print(f"draft_session_id: {draft.session_id}")
    print(f"draft_prompt: {draft.prompt}")
    print(f"draft_instructions: {', '.join(draft.instruction_id_list) or 'none'}")
    print(f"draft_output: {draft.output}")
    while True:
        try:
            answer = input("promote draft to data/eval? [y/N]: ").strip().lower()
        except EOFError:
            print("ifeval draft review cancelled")
            return 1
        if answer in {"y", "yes"}:
            published_store = EvalSeedStore(get_eval_seed_path())
            published_store.append(draft)
            removed = draft_store.remove_by_key(draft.key)
            if removed is None:
                print(f"ifeval draft not found: {draft.key}")
                return 1
            print(f"ifeval_draft_promoted: {draft.key}")
            print(f"ifeval_seed_path: {published_store.path}")
            return 0
        if answer in {"", "n", "no"}:
            print("ifeval draft review cancelled")
            return 0
        print("please answer y or n")


def _candidate_action_from_args(args) -> str | None:
    if args.apply_candidate_run and (
        args.accept_candidate or args.reject_candidate or args.apply_candidate or args.supersede_candidate or args.archive_candidate
    ):
        raise SystemExit(
            "--apply-candidate-run cannot be combined with candidate status mutation flags"
        )
    if args.curator_run and (
        args.accept_candidate
        or args.reject_candidate
        or args.apply_candidate
        or args.apply_candidate_run
        or args.supersede_candidate
        or args.archive_candidate
    ):
        raise SystemExit(
            "--curator-run cannot be combined with candidate status mutation flags or --apply-candidate-run"
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


def _review_eval_case(
    *,
    system_prompt: str | None,
) -> int:
    app = build_application(
        default_system_prompt=system_prompt,
        approval_provider=CliApprovalProvider(),
    )
    pending_candidates = [
        candidate
        for candidate in app.list_candidates(limit=50, status="pending")
        if getattr(candidate, "target", None) == "eval_case"
    ]
    if not pending_candidates:
        print("no pending eval_case candidate found")
        return 1
    candidate = pending_candidates[0]
    metadata = getattr(candidate, "metadata", {}) or {}
    print("eval_case review:")
    print(f"candidate_id: {candidate.candidate_id}")
    print(f"candidate_target: {candidate.target}")
    print(f"candidate_summary: {candidate.summary}")
    if getattr(candidate, "rationale", ""):
        print(f"candidate_rationale: {candidate.rationale}")
    if metadata.get("session_id"):
        print(f"candidate_session_id: {metadata['session_id']}")
    if metadata.get("trace_id"):
        print(f"candidate_trace_id: {metadata['trace_id']}")
    if metadata.get("user_id"):
        print(f"candidate_user_id: {metadata['user_id']}")
    if metadata.get("status"):
        print(f"candidate_status_hint: {metadata['status']}")
    if metadata.get("signals"):
        print(f"candidate_signals: {','.join(metadata['signals'])}")
    while True:
        try:
            answer = input("accept candidate? [y/N]: ").strip().lower()
        except EOFError:
            print("candidate review cancelled")
            return 1
        if answer in {"y", "yes"}:
            updated = app.update_candidate_status(
                candidate.candidate_id,
                "accepted",
                review_note="interactive review accepted",
            )
            if updated is None:
                print(f"candidate not found: {candidate.candidate_id}")
                return 1
            print(f"candidate_status: {updated.status}")
            return 0
        if answer in {"", "n", "no"}:
            updated = app.update_candidate_status(
                candidate.candidate_id,
                "rejected",
                review_note="interactive review rejected",
            )
            if updated is None:
                print(f"candidate not found: {candidate.candidate_id}")
                return 1
            print(f"candidate_status: {updated.status}")
            return 0
        print("please answer y or n")


def _run_curator(
    *,
    user_id: str,
    session_id: str | None,
    system_prompt: str | None,
    review_note: str | None,
    dry_run: bool,
    confirm_eval_case: bool,
) -> int:
    app = build_application(
        default_system_prompt=system_prompt,
        approval_provider=CliApprovalProvider(),
    )
    summary = ReviewLoopService().summarize(
        candidates=app.list_candidates(limit=50),
        eval_cases=app.list_eval_cases(limit=50),
    )
    candidate, selection_reason = _select_curator_candidate(summary.pending_queue)
    if candidate is None:
        print("no applicable prompt candidate found in curator queue")
        return 1
    metadata = getattr(candidate, "metadata", {}) or {}
    print(f"curator_candidate_id: {candidate.candidate_id}")
    print(f"curator_target: {candidate.target}")
    print(f"curator_workflow: {metadata.get('workflow_name', 'unknown-workflow')}")
    print(f"curator_step: {metadata.get('task_name', 'unknown-step')}")
    print(f"curator_selection_reason: {selection_reason}")
    if dry_run:
        print("curator_dry_run: yes")
        print("curator_action: apply-candidate-run")
        return 0
    return _run_candidate_apply_workflow(
        candidate_id=candidate.candidate_id,
        user_id=user_id,
        session_id=session_id,
        system_prompt=system_prompt,
        review_note=review_note or "curator-run applied top pending prompt candidate",
        confirm_eval_case=confirm_eval_case,
    )


def _select_curator_candidate(pending_queue) -> tuple[object | None, str]:
    prompt_candidates = [
        candidate
        for candidate in pending_queue
        if getattr(candidate, "target", None) == "prompt"
    ]
    if not prompt_candidates:
        return None, "no prompt candidate"
    candidate = min(
        prompt_candidates,
        key=lambda candidate: (
            0 if _curator_metadata(candidate).get("workflow_status") == "regressed" else 1,
            _curator_score(candidate, "workflow_score_delta"),
            _curator_score(candidate, "step_score_delta"),
            getattr(candidate, "candidate_id", ""),
        ),
    )
    metadata = _curator_metadata(candidate)
    workflow_status = metadata.get("workflow_status", "unknown")
    workflow_score_delta = _curator_score(candidate, "workflow_score_delta")
    step_score_delta = _curator_score(candidate, "step_score_delta")
    return (
        candidate,
        (
            "prompt candidate prioritized by "
            f"workflow_status={workflow_status}, "
            f"workflow_score_delta={workflow_score_delta}, "
            f"step_score_delta={step_score_delta}"
        ),
    )


def _curator_score(candidate, field_name: str) -> float:
    value = _curator_metadata(candidate).get(field_name)
    if isinstance(value, (int, float)):
        return float(value)
    return 0.0


def _curator_metadata(candidate) -> dict:
    metadata = getattr(candidate, "metadata", None)
    if isinstance(metadata, dict):
        return metadata
    return {}


def _print_curator_status(*, summary, latest_report, overlay_info) -> None:
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
    print(f"eval_case_count: {summary.eval_case_count}")
    print(f"regressed_count: {summary.regressed_count}")
    print(f"improved_count: {summary.improved_count}")
    print(f"unchanged_count: {summary.unchanged_count}")
    if latest_report is not None:
        print(f"latest_report: {latest_report.report_path}")
        print(f"latest_workflow: {latest_report.workflow_name}")
        print(f"latest_status: {latest_report.status}")
        print(f"latest_score_delta: {latest_report.score_delta}")
        if latest_report.candidate_target:
            print(f"latest_candidate_target: {latest_report.candidate_target}")
        if latest_report.candidate_status:
            print(f"latest_candidate_status: {latest_report.candidate_status}")
    print(f"prompt_overlay_candidate_count: {overlay_info['candidate_count']}")
    if summary.pending_targets:
        print("pending_targets:")
        for target, count in summary.pending_targets:
            print(f"- {target}: {count}")
    if summary.top_regressed_workflows:
        print("top_regressed_workflows:")
        for workflow, count in summary.top_regressed_workflows:
            print(f"- {workflow}: {count}")
    if summary.pending_queue:
        print("top_pending_queue:")
        for candidate in summary.pending_queue[:3]:
            metadata = getattr(candidate, "metadata", {}) or {}
            workflow_name = metadata.get("workflow_name", "unknown-workflow")
            task_name = metadata.get("task_name", "unknown-step")
            print(
                f"- {candidate.candidate_id} [{candidate.target}] {candidate.summary} "
                f"(workflow={workflow_name} step={task_name})"
            )
    print(f"recommendation: {summary.recommendation}")


def _run_candidate_apply_workflow(
    *,
    candidate_id: str,
    user_id: str,
    session_id: str | None,
    system_prompt: str | None,
    review_note: str | None,
    confirm_eval_case: bool,
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
    source_result = run_healthcheck_workflow(
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
    replay_result = run_healthcheck_workflow(
        app=rerun_app,
        workflow_name=workflow_name,
        user_id=user_id,
        session_id=(session_id or source_result.session_id) + f":candidate:{candidate_id[:8]}",
        system_prompt=system_prompt,
    )
    comparison, report_dir, eval_case_saved = _finalize_evolution_comparison(
        app=rerun_app,
        source=source_result,
        replay=replay_result,
        confirm_eval_case=confirm_eval_case,
    )
    outcome_status = _candidate_outcome_status(comparison.eval_case.status)
    updated = rerun_app.update_candidate_status(
        candidate_id,
        outcome_status,
        review_note=f"workflow={workflow_name} score_delta={comparison.score_delta} report={report_dir}",
    )
    print(f"candidate_id: {applied.candidate_id}")
    print(f"candidate_status: {updated.status if updated is not None else applied.status}")
    print(f"workflow: {workflow_name}")
    print(f"candidate_outcome: {comparison.eval_case.status}")
    print(f"candidate_report_path: {report_dir}")
    _print_evolution_comparison(
        comparison=comparison,
        report_dir=report_dir,
        eval_case_saved=eval_case_saved,
    )
    return 0


def _run_evolution_workflow(
    *,
    app,
    workflow_name: str,
    user_id: str,
    session_id: str | None,
    system_prompt: str | None,
    confirm_eval_case: bool,
) -> int:
    source = run_healthcheck_workflow(
        app=app,
        workflow_name=workflow_name,
        user_id=user_id,
        session_id=session_id,
        system_prompt=system_prompt,
    )
    replay = replay_healthcheck_workflow(
        app=app,
        workflow_result=source,
        system_prompt=system_prompt,
    )
    comparison, report_dir, eval_case_saved = _finalize_evolution_comparison(
        app=app,
        source=source,
        replay=replay,
        confirm_eval_case=confirm_eval_case,
    )
    _print_evolution_comparison(
        comparison=comparison,
        report_dir=report_dir,
        eval_case_saved=eval_case_saved,
    )
    return 0


def _finalize_evolution_comparison(
    *,
    app,
    source,
    replay,
    confirm_eval_case: bool,
):
    comparison = compare_healthcheck_workflow_results(source, replay)
    save_eval_case = True
    if confirm_eval_case:
        save_eval_case = _confirm_eval_case(comparison)
    if save_eval_case:
        app.add_eval_case(comparison.eval_case)
    if comparison.candidate is not None:
        app.add_candidate(comparison.candidate)
    review_summary = ReviewLoopService().summarize(
        candidates=app.list_candidates(limit=50),
        eval_cases=app.list_eval_cases(limit=50),
    )
    report_dir = EvolutionReportWriter(get_evolution_reports_dir()).write_workflow_comparison_report(
        comparison=comparison,
        review_summary=review_summary,
    )
    return comparison, report_dir, save_eval_case


def _confirm_eval_case(comparison) -> bool:
    print("eval case candidate:")
    print(f"workflow: {comparison.workflow_name}")
    print(f"status: {comparison.eval_case.status}")
    print(f"source_average_score: {comparison.source_average_score}")
    print(f"replay_average_score: {comparison.replay_average_score}")
    print(f"score_delta: {comparison.score_delta}")
    while True:
        try:
            answer = input("save eval case? [y/N]: ").strip().lower()
        except EOFError:
            return False
        if answer in {"y", "yes"}:
            return True
        if answer in {"", "n", "no"}:
            return False
        print("please answer y or n")


def _print_evolution_comparison(*, comparison, report_dir, eval_case_saved: bool) -> None:
    print(f"workflow: {comparison.workflow_name}")
    print(f"source_session_id: {comparison.source_session_id}")
    print(f"replay_session_id: {comparison.replay_session_id}")
    print(f"workflow_status: {comparison.eval_case.status}")
    print(f"source_average_score: {comparison.source_average_score}")
    print(f"replay_average_score: {comparison.replay_average_score}")
    print(f"score_delta: {comparison.score_delta}")
    print(f"eval_case_saved: {'yes' if eval_case_saved else 'no'}")
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


def _candidate_outcome_status(eval_case_status: str) -> str:
    if eval_case_status == "improved":
        return "verified"
    if eval_case_status == "unchanged":
        return "no_improvement"
    if eval_case_status == "regressed":
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
