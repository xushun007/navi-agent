from __future__ import annotations

import argparse
from uuid import uuid4

from navi_agent.app import AppRequest
from navi_agent.bootstrap import build_application
from navi_agent.doctor import run_doctor
from navi_agent.runtime import CliApprovalProvider
from navi_agent.smoke import list_smoke_tasks, run_smoke_task


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="navi-agent")
    parser.add_argument("message", nargs="?")
    parser.add_argument("--user-id", default="local-user")
    parser.add_argument("--session-id")
    parser.add_argument("--system-prompt")
    parser.add_argument("--interactive", action="store_true")
    parser.add_argument("--doctor", action="store_true")
    parser.add_argument("--smoke")
    parser.add_argument("--list-smoke-tasks", action="store_true")
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
    if not args.interactive and not args.smoke and not args.message:
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
