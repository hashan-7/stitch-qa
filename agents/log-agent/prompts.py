import json
import os


SYSTEM_PROMPT = """You are Stitch QA's Runtime Quality Intelligence Analyst, a senior evidence-based runtime QA specialist. Your duty is limited to interpreting supplied runtime execution and automated test evidence. Return exactly one valid JSON object and nothing else.

Locked facts are authoritative. Never invent, modify, reinterpret, or contradict test counts, test names, exception types, exception messages, expected-versus-actual values, file paths, line numbers, commands, exit codes, execution outcomes, evidence quality, confidence levels, runtime risk levels, failure origins, or runtime release gates.

Do not assess source-code quality, static-analysis findings, architecture, code smells, security posture, business-logic correctness, product requirements, user experience, or whole-application deployment readiness. Those areas belong to other QA evidence and other specialist agents.

Do not claim that an application, product, system, or release is production-ready, deployment-ready, fully validated, defect-free, secure, or safe to release. Do not describe the whole application, product, or system as failed when only a validated runtime workflow or tested path failed. Describe only the validated runtime workflow, tested paths, or supplied evidence.

Do not write release advice, release permission, release approval, or deployment readiness. The deterministic system will add the runtime gate sentence.

The deterministic analyzer already owns test facts, runtime impact, remediation actions, verification baselines, and release gating. Your role is to add concise professional interpretation and refine only the evidence-backed root cause for submitted groups.

If no submitted root-cause groups are provided, group_insights must be exactly an empty JSON array. Do not create placeholder group objects.

Every top-level prose field must be one sentence and no more than 28 words. Every root_cause value must be one sentence and no more than 36 words. Do not repeat the complete deterministic test summary.

Do not generate patches, code, automatic modifications, hidden reasoning, markdown, code fences, headings, commentary, or fields outside the required JSON contract."""


def compact_text(value, limit):
    text = " ".join(str(value or "").split()).strip()

    if len(text) <= limit:
        return text

    return text[: limit - 3].rstrip() + "..."


def compact_list(values, item_limit=240, max_items=12):
    return [
        compact_text(item, item_limit)
        for item in list(values or [])[:max_items]
        if str(item or "").strip()
    ]


def compact_evidence_item(item):
    if not isinstance(item, dict):
        return {}

    limits = {
        "failure_id": 80,
        "status": 40,
        "test_name": 220,
        "test_file": 320,
        "exception_type": 160,
        "exception_message": 320,
        "expected": 220,
        "actual": 220,
        "application_file": 320,
        "failure_type": 160,
        "help_message": 320,
        "command": 320,
    }
    result = {}

    for key in (
        "failure_id",
        "status",
        "test_name",
        "test_file",
        "test_line",
        "exception_type",
        "exception_message",
        "expected",
        "actual",
        "application_file",
        "application_line",
        "failure_type",
        "help_message",
        "command",
        "exit_code",
    ):
        value = item.get(key)

        if value is None or value == "":
            continue

        if key in limits:
            result[key] = compact_text(value, limits[key])
        else:
            result[key] = value

    return result


def compact_run_summary(run_summary):
    source = run_summary if isinstance(run_summary, dict) else {}
    return {
        "framework": compact_text(source.get("framework"), 120),
        "command": compact_text(source.get("command"), 320),
        "total": source.get("total", 0),
        "passed": source.get("passed", 0),
        "failed": source.get("failed", 0),
        "skipped": source.get("skipped", 0),
        "errors": source.get("errors", 0),
        "exit_code": source.get("exit_code"),
        "duration_seconds": source.get("duration_seconds"),
        "report_source": compact_text(source.get("report_source"), 120),
        "failure_records_total": source.get("failure_records_total", 0),
        "failure_records_submitted": source.get("failure_records_submitted", 0),
        "evidence_truncated": bool(source.get("evidence_truncated")),
    }


def build_case_instruction(test_result, has_groups):
    if test_result == "PASS":
        return (
            "Interpret the successful tested runtime outcome, define assurance only for exercised paths, "
            "state residual runtime uncertainty, and give one evidence-retention or follow-up verification action. "
            "Do not introduce defects, causes, remediation, or group insights."
        )

    if test_result == "FAIL":
        if has_groups:
            return (
                "Interpret the confirmed failing tested runtime outcome, state tested-scope assurance and residual regression risk, "
                "give one prioritized verification action, and refine only the submitted evidence-backed root causes."
            )

        return (
            "Interpret the confirmed failing tested runtime outcome using only locked facts, state tested-scope assurance and residual risk, "
            "and give one verification action. Do not invent root-cause groups."
        )

    if test_result == "NOT_RUN":
        return (
            "Explain that no executed test outcome was established, define the resulting assurance gap and residual runtime risk, "
            "and state the exact action needed to obtain executed evidence."
        )

    if test_result == "INCONCLUSIVE":
        return (
            "Explain why the supplied runtime evidence is inconclusive, define the resulting assurance gap and residual risk, "
            "and state the required rerun or evidence-collection action."
        )

    return (
        "Produce a concise tested-scope runtime QA interpretation grounded only in supplied evidence and do not write release advice."
    )


def build_required_output_contract(test_result, has_groups):
    contract = {
        "outcome_interpretation": "One sentence, maximum 28 words",
        "scope_assurance": "One sentence, maximum 28 words",
        "residual_runtime_risk": "One sentence, maximum 28 words",
        "next_verification": "One sentence, maximum 28 words",
    }

    if test_result == "PASS" or not has_groups:
        contract["group_insights"] = []
        return contract

    contract["group_insights"] = [
        {
            "group_id": "Existing submitted group_id only",
            "root_cause": "One evidence-grounded sentence, maximum 36 words",
        }
    ]
    return contract


def build_group_instruction(test_result, has_groups):
    if test_result == "PASS" or not has_groups:
        return "Return group_insights exactly as []."

    return (
        "Return one group_insights object for each submitted group, in the same order, using only existing group_id values. "
        "Only refine root_cause; deterministic runtime impact and required actions are retained by the system."
    )


def build_analysis_messages(base_analysis):
    configured_groups = int(os.getenv("LLM_MAX_GROUPS", "2"))
    max_groups = min(max(configured_groups, 1), 4)
    test_result = str(base_analysis.get("test_result") or "INCONCLUSIVE").upper()
    release_gate = str(base_analysis.get("release_gate") or "REVIEW_REQUIRED").upper()
    source_groups = base_analysis.get("root_cause_groups", [])

    if test_result == "PASS":
        groups = []
    else:
        groups = []

        for group in source_groups[:max_groups]:
            evidence = [
                compact_evidence_item(item)
                for item in list(group.get("evidence", []))[:6]
            ]
            groups.append(
                {
                    "group_id": group.get("group_id"),
                    "category": group.get("category"),
                    "failure_origin": group.get("failure_origin"),
                    "affected_tests": compact_list(
                        group.get("affected_tests", []),
                        item_limit=220,
                        max_items=12,
                    ),
                    "evidence": evidence,
                    "validated_root_cause": compact_text(
                        group.get("root_cause"),
                        700,
                    ),
                }
            )

    has_groups = bool(groups)
    payload = {
        "case_instruction": build_case_instruction(test_result, has_groups),
        "locked_facts": {
            "execution_status": base_analysis.get("execution_status"),
            "test_result": test_result,
            "release_gate": release_gate,
            "runtime_risk_level": base_analysis.get("runtime_risk_level"),
            "failure_origin": base_analysis.get("failure_origin"),
            "diagnosis_confidence": base_analysis.get("diagnosis_confidence"),
            "evidence_quality": base_analysis.get("evidence_quality"),
            "run_summary": compact_run_summary(base_analysis.get("run_summary", {})),
            "warnings": compact_list(
                base_analysis.get("warnings", []),
                item_limit=240,
                max_items=6,
            ),
            "limitations": compact_list(
                base_analysis.get("limitations", []),
                item_limit=260,
                max_items=4,
            ),
        },
        "submitted_root_cause_groups": groups,
        "root_cause_groups_total": 0 if test_result == "PASS" else len(source_groups),
        "root_cause_groups_submitted": len(groups),
        "required_output": build_required_output_contract(test_result, has_groups),
    }

    return [
        {
            "role": "system",
            "content": SYSTEM_PROMPT,
        },
        {
            "role": "user",
            "content": (
                "Return the required JSON object only. Keep every prose value within the stated word limit. "
                "Use supplied exception and expected-versus-actual evidence only when it materially improves precision. "
                "Do not output release advice, deterministic runtime impact, deterministic required actions, or extra fields. "
                f"{build_group_instruction(test_result, has_groups)}\n\n"
                + json.dumps(
                    payload,
                    ensure_ascii=False,
                    separators=(",", ":"),
                )
            ),
        },
    ]
