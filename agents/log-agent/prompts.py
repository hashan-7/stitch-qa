import json
import os


SYSTEM_PROMPT = """You are Stitch QA's Runtime Quality Intelligence Analyst, a senior evidence-based software QA specialist. Analyze only the supplied validated runtime and test evidence. Return exactly one valid JSON object and nothing else. Never invent or alter test counts, test names, exception types, file paths, line numbers, commands, exit codes, execution outcomes, confidence values, or release gates. Never claim that passing tests prove complete correctness. Never propose automatic source modification. Do not include markdown, code fences, headings, hidden reasoning, or unsupported assumptions. Keep the assessment concise, technically precise, auditable, and suitable for a professional pre-deployment QA report."""


def build_case_instruction(test_result, release_gate):
    if test_result == "PASS":
        return (
            "Write a senior QA assurance note for a passing test run. State what the validated evidence confirms, "
            "explain the meaning of the release gate, identify residual coverage limitations, and mention supplied "
            "warnings when present. Do not invent defects or remediation work. Return an empty group_insights list."
        )

    if test_result == "FAIL":
        return (
            "Write a senior QA failure assessment. Explain the confirmed failure pattern, runtime impact, release "
            "risk, and prioritized manual remediation. Improve only the wording of existing root-cause groups. "
            "Do not add new groups, tests, files, lines, exceptions, or facts."
        )

    if test_result == "NOT_RUN":
        return (
            "Write a senior QA evidence-gap assessment. Explain why no test result was established, what this means "
            "for release confidence, and the exact manual step required to obtain conclusive evidence. Do not describe "
            "the application as passed or failed unless the supplied facts explicitly establish that result."
        )

    if test_result == "INCONCLUSIVE":
        return (
            "Write a senior QA inconclusive-run assessment. Explain the execution limitation, its release impact, "
            "and the next verification step. Do not claim that the tests passed or failed."
        )

    return (
        "Write a senior QA assessment grounded only in the supplied evidence. Preserve the deterministic release "
        f"gate {release_gate} and do not introduce unsupported conclusions."
    )


def build_analysis_messages(base_analysis):
    max_groups = max(1, int(os.getenv("LLM_MAX_GROUPS", "4")))
    source_groups = base_analysis.get("root_cause_groups", [])
    groups = []

    for group in source_groups[:max_groups]:
        groups.append(
            {
                "group_id": group.get("group_id"),
                "category": group.get("category"),
                "affected_tests": group.get("affected_tests", []),
                "evidence": group.get("evidence", [])[:10],
                "deterministic_root_cause": group.get("root_cause"),
                "deterministic_runtime_impact": group.get("runtime_impact"),
                "deterministic_required_action": group.get("required_action"),
            }
        )

    test_result = base_analysis.get("test_result")
    release_gate = base_analysis.get("release_gate")

    payload = {
        "case_instruction": build_case_instruction(test_result, release_gate),
        "locked_facts": {
            "execution_status": base_analysis.get("execution_status"),
            "test_result": test_result,
            "release_gate": release_gate,
            "diagnosis_confidence": base_analysis.get("diagnosis_confidence"),
            "run_summary": base_analysis.get("run_summary", {}),
            "warnings": base_analysis.get("warnings", []),
            "limitations": base_analysis.get("limitations", []),
        },
        "deterministic_summary": base_analysis.get("summary"),
        "root_cause_groups": groups,
        "root_cause_groups_total": len(source_groups),
        "root_cause_groups_submitted": len(groups),
        "output_contract": {
            "overall_note": (
                "One concise professional QA assessment paragraph based only on locked_facts and supplied evidence"
            ),
            "group_insights": [
                {
                    "group_id": "An existing submitted group_id only",
                    "root_cause": "A precise evidence-grounded explanation",
                    "runtime_impact": "A realistic impact derived only from supplied evidence",
                    "required_action": "A prioritized manual remediation and verification action",
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
                "Apply the case instruction and improve the QA wording without changing any locked fact. "
                "Return valid JSON matching output_contract. "
                "For a PASS result, group_insights must be an empty list.\n\n"
                + json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
            ),
        },
    ]