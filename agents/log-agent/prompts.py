import json
import os


SYSTEM_PROMPT = """You are Stitch QA's Runtime Quality Intelligence Analyst. Facts are immutable; you make the QA reasoning decisions.

Group related failures and choose overall origin, risk, confidence, category, root cause, impact, and action. Never invent or alter counts, exceptions, expected/actual values, files, lines, execution status, test result, or release gate. Runtime/test QA only; no patches or whole-product claims.

Return compact JSON only: o=A/E/D/X/N origin, r=L/M/H/C/U risk, q=H/M/L confidence, g=groups. Group keys: f=evidence numbers, k=category, c=cause, i=impact, a=action. Every group f must contain at least one ev.n; never return an empty f. Cover every evidence number exactly once. c<=6 words, i<=4 words, a<=6 words and include verification when useful. /no_think"""


def compact_text(value, limit):
    text = " ".join(str(value or "").split()).strip()
    if len(text) <= limit:
        return text
    return text[: limit - 3].rstrip() + "..."


def join_location(path, line):
    if path and line:
        return f"{path}:{line}"
    return path or None


def flatten_failure_evidence(base_analysis):
    seen = set()
    failures = []

    for group in base_analysis.get("root_cause_groups", []):
        for item in group.get("evidence", []):
            failure_id = item.get("failure_id") or item.get("id")
            if not failure_id or failure_id in seen:
                continue
            seen.add(failure_id)
            failures.append(item)

    return failures


def compact_failure(item, number):
    result = {
        "n": number,
        "e": compact_text(item.get("exception_type"), 80),
        "m": compact_text(item.get("exception_message"), 120),
        "x": compact_text(item.get("expected"), 90),
        "y": compact_text(item.get("actual"), 90),
        "a": compact_text(
            join_location(item.get("application_file"), item.get("application_line")),
            150,
        ),
        "t": compact_text(
            join_location(item.get("test_file"), item.get("test_line")),
            150,
        ),
    }
    return {key: value for key, value in result.items() if value not in (None, "")}


def build_analysis_messages(base_analysis):
    configured = int(os.getenv("LLM_MAX_FAILURES", "8"))
    max_failures = min(max(configured, 1), 16)
    source_failures = flatten_failure_evidence(base_analysis)[:max_failures]
    failures = [
        compact_failure(item, index)
        for index, item in enumerate(source_failures, start=1)
    ]
    run = base_analysis.get("run_summary", {})

    payload = {
        "run": {
            "fw": run.get("framework"),
            "n": run.get("total", 0),
            "p": run.get("passed", 0),
            "f": run.get("failed", 0),
            "e": run.get("errors", 0),
            "s": run.get("skipped", 0),
            "x": run.get("exit_code"),
            "q": base_analysis.get("evidence_quality"),
            "gate": base_analysis.get("release_gate"),
        },
        "ev": failures,
    }

    risk_instruction = ""
    if str(base_analysis.get("test_result") or "").upper() == "FAIL":
        risk_instruction = " Confirmed FAIL: r must be H or C."

    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        {
            "role": "user",
            "content": (
                "Analyze ev. Group f values must use ev.n integers only."
                + risk_instruction
                + " JSON only.\n"
                + json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
            ),
        },
    ]
