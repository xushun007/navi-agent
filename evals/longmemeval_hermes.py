"""Isolated Hermes worker for LongMemEval historical-session comparisons.

Run as ``python -m evals.longmemeval_hermes`` with the Hermes Python
environment and an isolated HERMES_HOME. Dataset times have no timezone;
UTC preserves their wall-clock values consistently.
"""
from __future__ import annotations

import json
import os
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path


def history_timestamp(value: str) -> float:
    normalized = re.sub(r"\s+\([A-Za-z]{3}\)", "", value.strip())
    return datetime.strptime(normalized, "%Y/%m/%d %H:%M").replace(tzinfo=timezone.utc).timestamp()


def seed_history(db, sample: dict) -> None:
    ids = sample["haystack_session_ids"]
    dates = sample["haystack_dates"]
    sessions = sample["haystack_sessions"]
    if not (len(ids) == len(dates) == len(sessions)):
        raise ValueError("Session IDs, dates and histories must have matching lengths")
    for index, (date, messages) in enumerate(zip(dates, sessions, strict=True)):
        timestamp = history_timestamp(date)
        session_id = f"history:{index}"
        db.create_session(session_id=session_id, source="cli", user_id="longmemeval-pilot")
        rows = [{"role": "system", "content": f"Conversation date: {date}", "timestamp": timestamp}]
        for message in messages:
            if message["role"] not in {"user", "assistant"}:
                raise ValueError(f"Unexpected history role: {message['role']}")
            rows.append({"role": message["role"], "content": str(message["content"]), "timestamp": timestamp})
        db.append_messages_batch(session_id, rows)
        # Hermes creates session rows with the current time; update the isolated
        # eval database so discovery and chronological browsing use the source time.
        db._execute_write(lambda conn: conn.execute(
            "UPDATE sessions SET started_at = ?, last_activity_at = ? WHERE id = ?",
            (timestamp, timestamp, session_id),
        ))


def main() -> int:
    os.environ["TZ"] = "UTC"
    if hasattr(time, "tzset"):
        time.tzset()
    if datetime.fromtimestamp(0) != datetime(1970, 1, 1):
        raise RuntimeError("Start the worker with TZ=UTC to preserve dataset wall times")
    from hermes_state import SessionDB
    from run_agent import AIAgent

    sample_path, output_dir = map(Path, sys.argv[1:3])
    sample = json.loads(sample_path.read_text(encoding="utf-8"))
    output_dir.mkdir(parents=True, exist_ok=True)
    db = SessionDB(db_path=output_dir / "state.db")
    try:
        seed_history(db, sample)
        agent = AIAgent(
            base_url=os.environ["PILOT_BASE_URL"], api_key=os.environ["PILOT_API_KEY"],
            provider="custom", model=os.environ["PILOT_MODEL"], max_iterations=int(os.environ.get("PILOT_MAX_ITERATIONS", "20")),
            enabled_toolsets=["session_search"], quiet_mode=True, session_id="question",
            session_db=db, skip_context_files=True, skip_memory=True, skip_background_review=True,
        )
        prompt = (f"Today is {sample['question_date']}. Answer using my past conversations; "
                  f"search them for evidence. If the answer is unknown, say so.\n\n{sample['question']}")
        start = time.perf_counter()
        result = agent.run_conversation(prompt)
        messages = result.get("messages", [])
        report = {
            "question_id": sample["question_id"], "question_type": sample["question_type"],
            "question": sample["question"], "reference_answer": sample["answer"],
            "hypothesis": result.get("final_response"), "completed": result.get("completed"),
            "error": result.get("error"), "api_calls": result.get("api_calls"),
            "input_tokens": getattr(agent, "session_prompt_tokens", None),
            "output_tokens": getattr(agent, "session_output_tokens", None),
            "seconds": round(time.perf_counter() - start, 2),
            "tool_calls": [call for message in messages for call in (message.get("tool_calls") or [])],
        }
        (output_dir / "result.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        (output_dir / "messages.json").write_text(json.dumps(messages, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
        return 0 if report["completed"] is True else 1
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
