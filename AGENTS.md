# AGENTS.md

- Use Python.
- Use `uv` for dependency management, virtual environments, and project execution.
- Follow professional Python engineering practices.
- Design top-down and implement bottom-up.
- Implement the core functionality before adding unit tests.
- Keep modules focused with clear responsibilities.
- Avoid excessive abstraction and complexity based on speculative future needs.
- Prefer simple, direct, readable, and maintainable implementations.
- Use a standard Python package layout, explicit dependencies, and a clear test structure.
- During the gateway phase, support only Weixin.
- Keep the core architecture to the minimum closed loop: gateway, runtime, tools, memory/telemetry, and evolution.
- The gateway handles only protocol integration and message adaptation.
- The runtime owns the session, planning, execution, and response flow.
- Tools provide unified capability interfaces and do not contain policy.
- Evolution must remain decoupled from the online runtime path.
- Prefer the standard library and add dependencies cautiously.
- Keep public interfaces clear and data objects explicit.
- Make changes incrementally and avoid large one-shot refactors.
- Add corresponding unit tests when adding or changing core functionality.

## Requirement Delivery

- Use an isolated worktree by default. Modify `main` directly only when explicitly requested.
- Before starting, confirm the goal, scope, and acceptance criteria, then read the existing implementation and tests.
- Keep changes lightweight. Implement and verify one complete functional increment at a time.
- After completing each functional increment, run the relevant tests and commit immediately.
- When review is requested, do not commit until the user approves the changes.
- Before merging, rebase onto the target branch and verify again.
- Do not create unrequested issues, documents, or pull requests, and do not modify unrelated work.
- Report commit, push, CI, merge, and issue status accurately.
