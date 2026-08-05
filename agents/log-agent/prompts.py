import json
import os


SYSTEM_PROMPT = """You are Stitch QA's Runtime Quality Intelligence Analyst, a senior evidence-based runtime QA specialist. Your duty is limited to interpreting supplied runtime execution and automated test evidence. Return exactly one valid JSON object and nothing else.

Locked facts are authoritative. Never invent, modify, reinterpret, or contradict test counts, test names, exception types, file paths, line numbers, commands, exit codes, execution outcomes, evidence quality, confidence levels, or runtime release gates.

Do not assess source-code quality, static-analysis findings, architecture, code smells, security posture, business-logic correctness, product requirements, user experience, or whole-application deployment readiness. Those areas belong to other QA evidence and other specialist agents.

Do not claim that an application, product, system, or release is production-ready, deployment-ready, fully validated, defect-free, secure, or safe to release. Runtime release advice must be limited to the supplied tested scope.

Do not repeat the complete deterministic test summary. Interpret what the evidence means, state the tested-scope assurance, identify residual runtime risk, explain runtime release implications, and provide the next verification action.

Do not generate patches, code, automatic modifications, or hidden reasoning. Do not include markdown, code fences, headings, commentary, or fields outside the required JSON contract. Keep every field concise, technically precise, auditable, and suitable for a professional pre-deployment QA report."""


def build_case_instruction(test_result, release_gate):
    if test_result == "PASS":
        return (
            "Interpret the successful runtime outcome without repeating all test metrics. "
            "Explain the assurance provided for the exercised runtime paths, state the residual "
            "risk created by untested paths or unavailable coverage evidence, limit release advice "
            "to the tested runtime scope, and provide one evidence-retention or follow-up verification action. "
            "Do not invent failures, defects, root causes, or remediation. group_insights must be empty."
        )

    if test_result == "FAIL":
        return (
            "Interpret the confirmed failing runtime outcome. Explain the evidence-supported failure pattern, "
            "tested-scope impact, residual regression risk, BLOCK_RELEASE implication, and prioritized manual "
            "verification. Improve only supplied root-cause groups. Do not add new failures, groups, tests, "
            "files, lines, exceptions, or unsupported causes."
        )

    if test_result == "NOT_RUN":
        return (
            "Explain that no test outcome was established, identify the supplied execution or discovery barrier, "
            "state why runtime release confidence remains incomplete, preserve REVIEW_REQUIRED, and provide the "
            "exact action needed to obtain executed test evidence. Do not describe the application as passed or failed."
        )

    if test_result == "INCONCLUSIVE":
        return (
            "Explain why the runtime outcome is inconclusive, state the effect on runtime assurance and release "
            "confidence, preserve REVIEW_REQUIRED, and provide the required rerun or evidence-collection action. "
            "Do not invent a passing or failing result."
        )

    return (
        "Produce a scope-limited runtime QA interpretation grounded only in supplied evidence. "
        f"Preserve the deterministic runtime release gate {release_gate}."
    )


def build_analysis_messages(base_analysis):
    configured_groups = int(os.getenv("LLM_MAX_GROUPS", "4"))
    max_groups = min(max(configured_groups, 1), 2)
    source_groups = base_analysis.get("root_cause_groups", [])
    groups = []

    for group in source_groups[:max_groups]:
        groups.append(
            {
                "group_id": group.get("group_id"),
                "category": group.get("category"),
                "affected_tests": group.get("affected_tests", []),
                "evidence": group.get("evidence", [])[:8],
                "validated_root_cause": group.get("root_cause"),
                "validated_runtime_impact": group.get("runtime_impact"),
                "validated_required_action": group.get("required_action"),
            }
        )

    test_result = str(base_analysis.get("test_result") or "INCONCLUSIVE").upper()
    release_gate = str(
        base_analysis.get("release_gate") or "REVIEW_REQUIRED"
    ).upper()

    payload = {
        "case_instruction": build_case_instruction(
            test_result,
            release_gate,
        ),
        "locked_facts": {
            "execution_status": base_analysis.get("execution_status"),
            "test_result": test_result,
            "release_gate": release_gate,
            "diagnosis_confidence": base_analysis.get(
                "diagnosis_confidence"
            ),
            "evidence_quality": base_analysis.get("evidence_quality"),
            "run_summary": base_analysis.get("run_summary", {}),
            "warnings": base_analysis.get("warnings", []),
            "limitations": base_analysis.get("limitations", []),
        },
        "submitted_root_cause_groups": groups,
        "root_cause_groups_total": len(source_groups),
        "root_cause_groups_submitted": len(groups),
        "required_output": {
            "outcome_interpretation": (
                "One concise sentence explaining what the validated runtime outcome means"
            ),
            "scope_assurance": (
                "One concise sentence defining assurance only for the tested runtime scope"
            ),
            "residual_runtime_risk": (
                "One concise sentence describing runtime risk not eliminated by the supplied evidence"
            ),
            "release_advice": (
                "One concise sentence interpreting the locked runtime release gate without making a whole-application claim"
            ),
            "next_verification": (
                "One concise sentence giving the next manual verification or evidence-retention action"
            ),
            "group_insights": [
                {
                    "group_id": "An existing submitted group_id only",
                    "root_cause": "One concise evidence-grounded root-cause sentence",
                    "runtime_impact": "One concise tested-scope impact sentence",
                    "required_action": "One concise manual remediation and verification sentence",
                }
            ],
        },
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
                "For PASS, group_insights must be an empty list. Use only submitted group IDs.\n\n"
                + json.dumps(
                    payload,
                    ensure_ascii=False,
                    separators=(",", ":"),
                )
            ),
        },
    ]