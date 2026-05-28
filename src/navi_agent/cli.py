from __future__ import annotations

import argparse

from navi_agent.app import AppRequest
from navi_agent.bootstrap import build_application
from navi_agent.runtime import CliApprovalProvider


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="navi-agent")
    parser.add_argument("message", help="User message to send to the agent")
    parser.add_argument("--user-id", default="local-user")
    parser.add_argument("--session-id")
    parser.add_argument("--system-prompt")
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    app = build_application(
        default_system_prompt=args.system_prompt,
        approval_provider=CliApprovalProvider(),
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


if __name__ == "__main__":
    raise SystemExit(main())
