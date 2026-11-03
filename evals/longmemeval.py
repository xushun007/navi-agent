"""Small, isolated LongMemEval session-retrieval pilot.

This deliberately measures session search, not Navi's full memory-writing pipeline.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from time import perf_counter

from navi_agent.config import ModelSettings, RuntimeSettings, load_config
from navi_agent.runtime import AgentRuntime, Message, SessionMetadata, SQLiteSessionStore, ToolRegistry
from navi_agent.runtime.agent.prompt import PromptBuilder
from navi_agent.runtime.transports.factory import build_transport
from navi_agent.telemetry import SQLiteRuntimeEventStore, SQLiteTraceStore
from navi_agent.tools.session_search_tool import SessionSearchTool


def load_samples(path: Path, *, allow_partial: bool = False) -> tuple[list[dict], bool]:
    raw = path.read_text(encoding="utf-8")
    try:
        data = json.loads(raw)
        if not isinstance(data, list):
            raise ValueError("Expected a JSON array")
        return data, False
    except json.JSONDecodeError:
        if not allow_partial:
            raise
    decoder = json.JSONDecoder()
    position = len(raw) - len(raw.lstrip())
    if raw[position:position + 1] != "[":
        raise ValueError("Expected a JSON array")
    position += 1
    samples = []
    while True:
        position += len(raw[position:]) - len(raw[position:].lstrip(" \n\r\t,"))
        try:
            sample, position = decoder.raw_decode(raw, position)
        except json.JSONDecodeError:
            break
        samples.append(sample)
    if not samples:
        raise ValueError("Partial file does not contain a complete sample")
    return samples, True


def seed_history(store: SQLiteSessionStore, sample: dict, user_id: str) -> dict[str, str]:
    ids, dates, sessions = (sample[key] for key in ("haystack_session_ids", "haystack_dates", "haystack_sessions"))
    if not (len(ids) == len(dates) == len(sessions)) or len(set(ids)) != len(ids):
        raise ValueError("Session IDs, dates and histories must have matching lengths and unique IDs")
    mapping = {}
    for index, (source_id, date, messages) in enumerate(zip(ids, dates, sessions, strict=True)):
        session_id = f"history:{index}"
        mapping[str(source_id)] = session_id
        session = store.load(session_id, user_id, metadata=SessionMetadata(source="longmemeval"))
        store.append(session, Message(role="system", content=f"Conversation date: {date}"))
        for message in messages:
            if message["role"] not in {"user", "assistant"}:
                raise ValueError(f"Unexpected history role: {message['role']}")
            store.append(session, Message(role=message["role"], content=str(message["content"])))
    return mapping


def run_sample(sample: dict, root: Path, settings: ModelSettings, runtime_settings: RuntimeSettings) -> dict:
    root.mkdir(parents=True, exist_ok=False)
    db_path = root / "state.db"
    store = SQLiteSessionStore(db_path)
    user_id = "longmemeval-pilot"
    started = perf_counter()
    session_map = seed_history(store, sample, user_id)
    expected = {session_map[str(item)] for item in sample["answer_session_ids"] if str(item) in session_map}
    if len(expected) != len(set(sample["answer_session_ids"])):
        raise ValueError("An evidence session is missing from the history")
    trace_store = SQLiteTraceStore(db_path)
    registry = ToolRegistry(registered_tools=[("session", SessionSearchTool(store))])
    runtime = AgentRuntime(
        transport=build_transport(settings), session_store=store,
        prompt_builder=PromptBuilder(), tool_registry=registry,
        trace_store=trace_store, event_store=SQLiteRuntimeEventStore(db_path),
        model=settings.model, max_iterations=runtime_settings.max_iterations,
    )
    question = str(sample["question"])
    result = runtime.run_conversation(
        session_id="question", user_id=user_id,
        user_message=(f"Today is {sample['question_date']}. Answer using my past conversations; "
                      f"search them for evidence. If the answer is unknown, say so.\n\n{question}"),
        source="longmemeval-pilot",
    )
    trace = trace_store.get_latest_trace(session_id="question", user_id=user_id)
    if trace is None:
        raise RuntimeError("Runtime did not persist a trace")
    retrieved = []
    for call in trace.tool_executions:
        if call.tool_name != "session_search" or call.status != "success":
            continue
        structured = call.structured_content
        retrieved.extend(str(item["session_id"]) for item in structured.get("sessions", []))
        if structured.get("found") and structured.get("session_id"):
            retrieved.append(str(structured["session_id"]))
    retrieved = list(dict.fromkeys(retrieved))
    return {
        "question_id": sample["question_id"], "question_type": sample["question_type"],
        "question": question, "reference_answer": sample["answer"], "hypothesis": result.final_response,
        "runtime_status": result.status, "run_id": result.run_id, "trace_id": trace.trace_id,
        "evidence_session_count": len(expected), "retrieved_evidence_count": len(expected.intersection(retrieved)),
        "retrieved_all_evidence": expected.issubset(retrieved) if expected else None,
        "retrieved_session_count": len(retrieved), "iterations": trace.total_iterations,
        "input_tokens": sum(call.input_tokens for call in trace.model_calls),
        "output_tokens": sum(call.output_tokens for call in trace.model_calls),
        "model_seconds": trace.duration_ms / 1000, "total_seconds": round(perf_counter() - started, 2),
        "tool_calls": [{"name": call.tool_name, "arguments": call.arguments, "status": call.status} for call in trace.tool_executions],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--sample-id", action="append", required=True)
    parser.add_argument("--allow-partial", action="store_true")
    parser.add_argument("--max-concurrency", type=int, default=2)
    args = parser.parse_args()
    if args.max_concurrency < 1:
        parser.error("--max-concurrency must be positive")
    samples, partial = load_samples(args.dataset, allow_partial=args.allow_partial)
    indexed = {str(sample["question_id"]): sample for sample in samples}
    missing = set(args.sample_id) - indexed.keys()
    if missing or len(set(args.sample_id)) != len(args.sample_id):
        parser.error(f"Missing or duplicate sample IDs: {sorted(missing)}")
    settings = ModelSettings.from_sources(load_config())
    runtime_settings = RuntimeSettings.from_sources(load_config())
    if not settings.api_key:
        parser.error("Configure a model API key before running the pilot")
    args.output_dir.mkdir(parents=True, exist_ok=False)
    metadata = {"dataset": "xiaowu0162/longmemeval-cleaned", "variant": "longmemeval_s_cleaned",
                "dataset_revision": "98d7416c24c778c2fee6e6f3006e7a073259d48f", "partial": partial,
                "input_sha256": hashlib.sha256(args.dataset.read_bytes()).hexdigest(),
                "mode": "historical_session_search_only", "model": settings.model,
                "max_iterations": runtime_settings.max_iterations, "sample_ids": args.sample_id,
                "max_concurrency": args.max_concurrency}
    (args.output_dir / "metadata.json").write_text(json.dumps(metadata, indent=2) + "\n", encoding="utf-8")
    with ThreadPoolExecutor(max_workers=args.max_concurrency) as pool:
        futures = {
            pool.submit(run_sample, indexed[sample_id], args.output_dir / sample_id, settings, runtime_settings): sample_id
            for sample_id in args.sample_id
        }
        for future in as_completed(futures):
            result = future.result()
            with (args.output_dir / "results.jsonl").open("a", encoding="utf-8") as out:
                out.write(json.dumps(result, ensure_ascii=False) + "\n")
            print(json.dumps(result, ensure_ascii=False), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
