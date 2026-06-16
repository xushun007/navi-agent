from __future__ import annotations

import os
from pathlib import Path


def get_navi_home() -> Path:
    raw_home = os.getenv("NAVI_HOME", "").strip()
    if raw_home:
        return Path(raw_home).expanduser()
    return Path.cwd() / ".navi-agent"


def get_state_db_path() -> Path:
    return get_navi_home() / "state.db"


def get_config_path() -> Path:
    return get_navi_home() / "config.yaml"


def get_logs_dir() -> Path:
    return get_navi_home() / "logs"


def get_app_log_path() -> Path:
    return get_logs_dir() / "navi-agent.log"


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


def get_workflow_sample_store_path() -> Path:
    return get_evolution_dir() / "workflow-samples.jsonl"
