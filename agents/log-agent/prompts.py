import json
import os


SYSTEM_PROMPT = """You are Stitch QA's Runtime Quality Intelligence Analyst, a senior evidence-based runtime QA specialist. Your duty is limited to interpreting supplied runtime execution and automated test evidence. Return exactly one valid JSON object and nothing else.

Locked facts are authoritative. Never invent, modify, reinterpret, or contradict test counts, test names, exception types, exception messages, expected-versus-actual values, file paths, line numbers, commands, exit codes, execution outcomes, evidence quality, confidence levels, runtime risk levels, failure origins, or runtime release gates.

Do not assess source-code quality, static-analysis findings, architecture, code smells, security posture, business-logic correctness, product requirements, user experience, or whole-application deployment readiness. Those areas belong to other QA evidence and other specialist agents.

Do not claim that an application, product, system, or release is production-ready, deployment-ready, fully validated, defect-free, secure, or safe to release. Do not describe the whole application, product, or system as failed when only a validated runtime workflow or tested path failed. Describe only the validated runtime workflow, tested paths, or supplied evidence.

Do not write release advice, release permission, release approval, or deployment readiness. The deterministic system will add the runtime gate sentence.

Do not repeat the complete deterministic test summary. Interpret what the evidence means, state the tested-scope assurance, identify residual runtime risk, and provide the next verification action.

If no submitted root-cause groups are provided, group_insights must be exactly an empty JSON array. Do not create placeholder group objects.

Do not generate patches, code, automatic modifications, or hidden reasoning. Do not include markdown, code fences, headings, commentary, or fields outside the required JSON contract. Keep every field concise, technically precise, auditable, and suitable for a professional pre-deployment QA report."""


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
        "exception_message": 360,
        "expected": 240,
        "actual": 240,
        "application_file": 320,
        "failure_type": 160,
        "help_message": 360,
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
        "command": compact_text(source.get("command"), 400),
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
            "Interpret the successful runtime outcome without repeating all test metrics. "
            "Explain the assurance provided for the exercised runtime paths, state the residual "
            "risk created by untested paths or unavailable coverage evidence, and provide one "
            "evidence-retention or follow-up verification action. Do not write release advice, "
            "deployment readiness, source findings, failures, defects, root causes, remediation, "
            "or group insights. group_insights must be exactly []."
        )

    if test_result == "FAIL":
        if has_groups:
            return (
                "Interpret the confirmed failing runtime outcome using the supplied exception types, "
                "exception messages, expected-versus-actual behavior, affected tests, and mapped locations "
                "when available. Explain the evidence-supported failure pattern, tested-scope impact, "
                "residual regression risk, and prioritized manual verification. Improve only supplied "
                "root-cause groups. Do not describe the whole application or system as failed. Do not write "
                "release advice or add new failures, groups, tests, files, lines, exceptions, or unsupported causes."
            )

        return (
            "Interpret the confirmed failing runtime outcome using only the locked facts. Explain that detailed "
            "root-cause grouping was not supplied and provide manual verification guidance. Describe only the "
            "validated runtime workflow or tested scope as failed. Do not write release advice. "
            "group_insights must be exactly []."
        )

    if test_result == "NOT_RUN":
        if has_groups:
            return (
                "Explain that no test outcome was established, identify the supplied execution or discovery barrier, "
                "state why runtime confidence remains incomplete, and provide the exact action needed to obtain "
                "executed test evidence. Do not write release advice."
            )

        return (
            "Explain that no test outcome was established and runtime confidence remains incomplete. Provide the "
            "exact action needed to obtain executed test evidence. Do not describe the application as passed or "
            "failed. Do not write release advice. group_insights must be exactly []."
        )

    if test_result == "INCONCLUSIVE":
        if has_groups:
            return (
                "Explain why the runtime outcome is inconclusive, state the effect on runtime assurance, and "
                "provide the required rerun or evidence-collection action. Do not invent a passing or failing "
                "result. Do not write release advice."
            )

        return (
            "Explain why the runtime outcome is inconclusive, state the effect on runtime assurance, and provide "
            "the required rerun or evidence-collection action. Do not invent a passing or failing result. Do not "
            "write release advice. group_insights must be exactly []."
        )

    return (
        "Produce a scope-limited runtime QA interpretation grounded only in supplied evidence. Do not write release "
        "advice. If no root-cause groups are submitted, group_insights must be exactly []."
    )


def build_required_output_contract(test_result, has_groups):
    contract = {
        "outcome_interpretation": "One concise sentence explaining what the validated runtime outcome means",
        "scope_assurance": "One concise sentence defining assurance only for the tested runtime scope",
        "residual_runtime_risk": "One concise sentence describing runtime risk not eliminated by the supplied evidence",
        "next_verification": "One concise sentence giving the next manual verification or evidence-retention action",
    }

    if test_result == "PASS" or not has_groups:
        contract["group_insights"] = []
        return contract

    contract["group_insights"] = [
        {
            "group_id": "An existing submitted group_id only",
            "root_cause": "One concise evidence-grounded root-cause sentence using supplied failure evidence",
            "runtime_impact": "One concise tested-scope impact sentence",
            "required_action": "One concise manual remediation and verification sentence",
        }
    ]
    return contract


def build_group_instruction(test_result, has_groups):
    if test_result == "PASS" or not has_groups:
        return (
            "Return group_insights exactly as an empty array: []. "
            "Do not include any object inside group_insights."
        )

    return (
        "Return group_insights only for submitted root-cause groups. "
        "Use existing submitted group_id values only. "
        "Do not add new group IDs or placeholder group objects."
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
                        max_items=20,
                    ),
                    "evidence": evidence,
                    "validated_root_cause": compact_text(
                        group.get("root_cause"),
                        900,
                    ),
                    "validated_runtime_impact": compact_text(
                        group.get("runtime_impact"),
                        700,
                    ),
                    "validated_required_action": compact_text(
                        group.get("required_action"),
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
                item_limit=280,
                max_items=8,
            ),
            "limitations": compact_list(
                base_analysis.get("limitations", []),
                item_limit=320,
                max_items=6,
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
                "Apply the case instruction and return valid JSON matching required_output exactly. "
                "Each assessment field must add professional interpretation rather than repeat the raw metrics. "
                "Use supplied exception messages and expected-versus-actual evidence when they materially improve "
                "the precision of a failure explanation. Do not output release_advice or any release/deployment "
                "approval field. "
                f"{build_group_instruction(test_result, has_groups)}\n\n"
                + json.dumps(
                    payload,
                    ensure_ascii=False,
                    separators=(",", ":"),
                )
            ),
        },
    ]
