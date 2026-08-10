import json
import os


SYSTEM_PROMPT = """You are Stitch QA's Runtime Quality Intelligence Analyst. Act like a senior runtime QA investigator, not a template engine.

The supplied facts are immutable evidence. You may interpret them, connect them, group failures, diagnose causes, assess tested-scope risk, and recommend verification. Never invent or change test counts, commands, exit codes, test names, exception data, expected/actual values, file paths, line numbers, execution status, test result, or evidence quality.

Reason dynamically from the evidence. Do not copy the fallback diagnosis. Group failures by the most plausible shared cause, even when their exception text differs, but every group must reference only supplied failure IDs. Prefer one shared group when evidence supports a common cause and separate groups when causes materially differ.

Stay inside runtime/test QA. Do not assess architecture, static source quality, security posture, UX, business requirements, or whole-product readiness. Do not generate patches or automatically modify code. Do not put release-gate wording in s; the backend appends the locked runtime gate.

Use /no_think behavior. Return exactly one compact JSON object using only these short keys:
s = concise developer summary
o = overall failure origin
r = runtime risk
c = diagnosis confidence
v = next verification action
x = reasoning groups
Each group uses f=failure IDs, k=category, o=failure origin, c=root cause, i=runtime impact, a=required action.

Keep s to at most 22 words. Keep v to at most 18 words. Keep each group c to at most 26 words, i to at most 18 words, and a to at most 18 words. No markdown or extra fields."""


def compact_text(value, limit):
    text = " ".join(str(value or "").split()).strip()
    if len(text) <= limit:
        return text
    return text[: limit - 3].rstrip() + "..."


def compact_failure(item):
    if not isinstance(item, dict):
        return {}

    result = {
        "id": item.get("failure_id") or item.get("id"),
        "status": item.get("status"),
        "test": compact_text(item.get("test_name"), 180),
        "exception": compact_text(item.get("exception_type"), 100),
        "message": compact_text(item.get("exception_message"), 180),
        "expected": compact_text(item.get("expected"), 120),
        "actual": compact_text(item.get("actual"), 120),
        "app": compact_text(item.get("application_file"), 180),
        "app_line": item.get("application_line"),
        "test_file": compact_text(item.get("test_file"), 180),
        "test_line": item.get("test_line"),
    }
    return {
        key: value
        for key, value in result.items()
        if value not in (None, "")
    }


def flatten_failure_evidence(base_analysis):
    seen = set()
    failures = []

    for group in base_analysis.get("root_cause_groups", []):
        for item in group.get("evidence", []):
            failure_id = item.get("failure_id") or item.get("id")
            if not failure_id or failure_id in seen:
                continue
            seen.add(failure_id)
            failures.append(compact_failure(item))

    return failures


def build_analysis_messages(base_analysis):
    configured = int(os.getenv("LLM_MAX_FAILURES", "8"))
    max_failures = min(max(configured, 1), 16)
    failures = flatten_failure_evidence(base_analysis)[:max_failures]
    run = base_analysis.get("run_summary", {})

    payload = {
        "facts": {
            "execution": base_analysis.get("execution_status"),
            "result": base_analysis.get("test_result"),
            "framework": run.get("framework"),
            "total": run.get("total", 0),
            "passed": run.get("passed", 0),
            "failed": run.get("failed", 0),
            "errors": run.get("errors", 0),
            "skipped": run.get("skipped", 0),
            "exit": run.get("exit_code"),
            "evidence": base_analysis.get("evidence_quality"),
            "gate": base_analysis.get("release_gate"),
        },
        "failures": failures,
        "failure_records_total": run.get("failure_records_total", len(failures)),
        "failure_records_submitted": len(failures),
    }

    user_instruction = (
        "Analyze the evidence as a runtime QA investigator. The gate in facts is a locked safety boundary; do not contradict it. "
        "For FAIL, cover every submitted failure ID exactly once across x. For PASS or cases with no failure IDs, return x as []. "
        "Allowed o values: APPLICATION_DEFECT, ENVIRONMENT, TEST_DISCOVERY, EXECUTION, NOT_ESTABLISHED. "
        "Allowed r values: LOW, MEDIUM, HIGH, CRITICAL, UNKNOWN. Allowed c values: HIGH, MEDIUM, LOW. "
        "Return compact JSON only. Evidence:\n"
        + json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    )

    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": user_instruction},
    ]
