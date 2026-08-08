from __future__ import annotations

from html import escape


def render_ab_review(payload: dict) -> str:
    """Render one self-contained Evolution A/B review with local feedback export."""
    workflow = _text(payload.get("workflow_name"), "unknown workflow")
    eval_case = payload.get("eval_case") if isinstance(payload.get("eval_case"), dict) else {}
    status = _text(eval_case.get("status"), "unknown")
    candidate = payload.get("candidate") if isinstance(payload.get("candidate"), dict) else {}
    steps = payload.get("step_comparisons")
    step_cards = (
        "".join(
            _render_step(step, index)
            for index, step in enumerate(steps)
            if isinstance(step, dict)
        )
        if isinstance(steps, list)
        else ""
    )
    candidate_summary = _text(candidate.get("summary"), "No candidate attached")
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{escape(workflow)} · Navi A/B Review</title>
<style>
:root {{ color-scheme: light dark; --bg:#f6f7fb; --panel:#fff; --text:#172033; --muted:#667085; --line:#d8dee9; --a:#3157d5; --b:#087f5b; }}
* {{ box-sizing:border-box }}
body {{ margin:0; background:var(--bg); color:var(--text); font:14px/1.5 ui-sans-serif,system-ui,sans-serif }}
main {{ width:min(1440px,96vw); margin:28px auto 60px }}
h1,h2,h3,p {{ margin-top:0 }}
.summary,.step {{ background:var(--panel); border:1px solid var(--line); border-radius:14px; box-shadow:0 8px 24px #1018280d }}
.summary {{ padding:22px; margin-bottom:18px }}
.review-actions {{ display:flex; align-items:center; flex-wrap:wrap; gap:12px; margin-top:18px }}
button {{ border:0; border-radius:9px; padding:9px 14px; background:var(--a); color:#fff; font:inherit; font-weight:700; cursor:pointer }}
.meta {{ display:flex; flex-wrap:wrap; gap:9px; color:var(--muted) }}
.pill {{ border:1px solid var(--line); border-radius:999px; padding:4px 9px }}
.step {{ margin:16px 0; overflow:hidden }}
.step-head {{ display:flex; justify-content:space-between; gap:16px; padding:16px 18px; border-bottom:1px solid var(--line) }}
.delta {{ font-weight:700 }}
.columns {{ display:grid; grid-template-columns:1fr 1fr }}
.run {{ min-width:0; padding:18px }}
.run + .run {{ border-left:1px solid var(--line) }}
.run-a h3 {{ color:var(--a) }} .run-b h3 {{ color:var(--b) }}
.facts {{ color:var(--muted); margin-bottom:12px }}
.feedback {{ padding:16px 18px; border-top:1px solid var(--line) }}
.feedback-grid {{ display:grid; grid-template-columns:auto minmax(160px,240px) 1fr; align-items:start; gap:14px }}
.choice {{ display:flex; flex-wrap:wrap; gap:10px }}
.choice label {{ white-space:nowrap }}
select,textarea {{ width:100%; border:1px solid var(--line); border-radius:8px; padding:8px; background:var(--panel); color:var(--text); font:inherit }}
textarea {{ min-height:64px; resize:vertical }}
pre {{ margin:0; padding:14px; max-height:65vh; overflow:auto; white-space:pre-wrap; overflow-wrap:anywhere; background:#111827; color:#e5e7eb; border-radius:9px; font:13px/1.55 ui-monospace,SFMono-Regular,monospace }}
@media (prefers-color-scheme:dark) {{ :root {{--bg:#0e1420;--panel:#151d2c;--text:#e7ecf4;--muted:#9aa7ba;--line:#2c374a}} }}
@media (max-width:800px) {{ .columns,.feedback-grid {{ grid-template-columns:1fr }} .run + .run {{ border-left:0; border-top:1px solid var(--line) }} }}
</style>
</head>
<body><main>
<section class="summary">
  <h1>Navi Evolution A/B Review</h1>
  <h2>{escape(workflow)}</h2>
  <p>{escape(candidate_summary)}</p>
  <div class="meta">
    <span class="pill">status: {escape(status)}</span>
    <span class="pill">baseline score: {escape(_text(payload.get("source_average_score")))}</span>
    <span class="pill">variant score: {escape(_text(payload.get("replay_average_score")))}</span>
    <span class="pill">delta: {escape(_signed(payload.get("score_delta")))}</span>
  </div>
  <div class="review-actions">
    <button type="button" id="download-feedback">Download feedback.json</button>
    <span class="facts">Feedback stays in this page until exported.</span>
  </div>
</section>
{step_cards or '<p>No step comparisons recorded.</p>'}
</main>
<script>
document.getElementById("download-feedback").addEventListener("click", () => {{
  const reviews = [...document.querySelectorAll(".step")].map((step) => ({{
    task_name: step.dataset.taskName,
    preference: step.querySelector('input[type="radio"]:checked')?.value || "",
    attribution: step.querySelector("select").value,
    notes: step.querySelector("textarea").value.trim()
  }}));
  const feedback = {{
    schema_version: 1,
    workflow_name: document.querySelector(".summary h2").textContent,
    exported_at: new Date().toISOString(),
    reviews
  }};
  const blob = new Blob([JSON.stringify(feedback, null, 2)], {{type:"application/json"}});
  const link = document.createElement("a");
  link.href = URL.createObjectURL(blob);
  link.download = "feedback.json";
  link.click();
  URL.revokeObjectURL(link.href);
}});
</script>
</body></html>"""


def _render_step(step: dict, index: int) -> str:
    name = escape(_text(step.get("task_name"), "unnamed step"))
    correctness = step.get("correctness")
    correctness_badge = ""
    if isinstance(correctness, dict) and isinstance(correctness.get("correctness_passed"), bool):
        verdict = "pass" if correctness["correctness_passed"] else "fail"
        missing = correctness.get("missing_terms")
        detail = f" · missing: {', '.join(map(str, missing))}" if isinstance(missing, list) and missing else ""
        correctness_badge = f'<span class="pill">correctness: {verdict}{escape(detail)}</span>'
    return f"""<section class="step" data-task-name="{name}">
  <div class="step-head"><h2>{name}</h2><div>{correctness_badge} <span class="delta">Δ {escape(_signed(step.get("score_delta")))}</span></div></div>
  <div class="columns">
    {_render_run("Baseline", "run-a", step, "source")}
    {_render_run("Variant", "run-b", step, "replay")}
  </div>
  {_render_feedback(index)}
</section>"""


def _render_feedback(index: int) -> str:
    field_name = f"preference-{index}"
    return f"""<div class="feedback">
  <div class="feedback-grid">
    <div class="choice" aria-label="Preferred result">
      <label><input type="radio" name="{field_name}" value="baseline"> Baseline</label>
      <label><input type="radio" name="{field_name}" value="variant"> Variant</label>
      <label><input type="radio" name="{field_name}" value="tie"> Tie</label>
    </div>
    <label>Problem attribution
      <select>
        <option value="">Not selected</option>
        <option value="skill_selection">Skill selection</option>
        <option value="instruction_quality">Instruction quality</option>
        <option value="tool_use">Tool use</option>
        <option value="factuality">Factuality</option>
        <option value="completeness">Completeness</option>
        <option value="other">Other</option>
      </select>
    </label>
    <label>Notes<textarea placeholder="Evidence, regression, or suggested change"></textarea></label>
  </div>
</div>"""


def _render_run(label: str, css_class: str, step: dict, prefix: str) -> str:
    score = _text(step.get(f"{prefix}_score"), "n/a")
    status = _text(step.get(f"{prefix}_status"), "unknown")
    trace_id = _text(step.get(f"{prefix}_trace_id"), "n/a")
    failure = step.get(f"{prefix}_failure_attribution")
    primary_failure = (
        _text(failure.get("primary_failure"), "none")
        if isinstance(failure, dict)
        else "none"
    )
    metrics = step.get(f"{prefix}_metrics")
    metrics_text = _metrics_text(metrics if isinstance(metrics, dict) else {})
    output = escape(_text(step.get(f"{prefix}_output")))
    return f"""<article class="run {css_class}">
  <h3>{label}</h3>
  <div class="facts">score: {escape(score)} · status: {escape(status)} · failure: {escape(primary_failure)}<br>{escape(metrics_text)}<br>trace: {escape(trace_id)}</div>
  <pre>{output}</pre>
</article>"""


def _text(value: object, default: str = "") -> str:
    return str(value) if value is not None else default


def _signed(value: object) -> str:
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return f"{value:+g}"
    return _text(value, "n/a")


def _metrics_text(metrics: dict) -> str:
    if not metrics:
        return "metrics: unavailable"
    return (
        f"tokens: {metrics.get('input_tokens', 0)} in / {metrics.get('output_tokens', 0)} out"
        f" · duration: {metrics.get('duration_ms', 0)} ms"
        f" · tools: {metrics.get('tool_calls', 0)}"
        f" · errors: {metrics.get('tool_errors', 0)}"
    )
