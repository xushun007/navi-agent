from __future__ import annotations

import os
from pathlib import Path


def get_navi_home() -> Path:
    raw_home = os.getenv("NAVI_HOME", "").strip()
    if raw_home:
        return Path(raw_home).expanduser()
    return Path.cwd() / ".navi-agent"


def get_repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def get_state_db_path() -> Path:
    return get_navi_home() / "state.db"


def get_config_path() -> Path:
    return get_navi_home() / "config.yaml"


def get_logs_dir() -> Path:
    return get_navi_home() / "logs"


def get_app_log_path() -> Path:
    return get_logs_dir() / "navi-agent.log"


def get_trace_store_path() -> Path:
    return get_logs_dir() / "traces.jsonl"


def get_evolution_dir() -> Path:
    return get_navi_home() / "evolution"


def get_evolution_reports_dir() -> Path:
    return get_logs_dir() / "evolution"


def get_prompt_overlay_path() -> Path:
    return get_evolution_dir() / "prompt-overlay.md"


def get_prompt_overlay_snapshots_dir() -> Path:
    return get_evolution_dir() / "prompt-overlay-snapshots"


def get_candidate_store_path() -> Path:
    return get_evolution_dir() / "candidates.jsonl"


def get_eval_case_store_path() -> Path:
    return get_evolution_dir() / "eval-cases.jsonl"


def get_eval_seed_dir() -> Path:
    return get_repo_root() / "data" / "eval"


def get_eval_seed_path(name: str = "ifeval_seed.jsonl") -> Path:
    return get_eval_seed_dir() / name


def get_eval_seed_reports_dir() -> Path:
    return get_navi_home() / "eval-seed-reports"


def get_ifeval_drafts_path() -> Path:
    return get_navi_home() / "ifeval-drafts.jsonl"


def get_ifeval_reports_dir() -> Path:
    return get_navi_home() / "ifeval-reports"


def get_tool_use_reports_dir() -> Path:
    return get_navi_home() / "tool-use-reports"


def get_tool_use_eval_reports_dir() -> Path:
    return get_navi_home() / "tool-use-eval-reports"


def get_smoke_reports_dir() -> Path:
    return get_navi_home() / "smoke-reports"


def get_skills_dir() -> Path:
    return get_navi_home() / "skills"
