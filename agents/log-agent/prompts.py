import json
import os


SYSTEM_PROMPT = """You are Stitch QA's Runtime Quality Intelligence Analyst. Analyze only the supplied validated runtime evidence. Return one JSON object and nothing else. Do not invent test counts, test names, exception types, files, line numbers, commands, exit codes, or outcomes. Do not propose automatic source modification. Keep each statement concise, specific, evidence-grounded, and suitable for a professional QA report."""


def build_analysis_messages(base_analysis):
    max_groups = max(1, int(os.getenv("LLM_MAX_GROUPS", "8")))
    groups = []
    for group in base_analysis.get("root_cause_groups", [])[:max_groups]:
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

    payload = {
        "execution_status": base_analysis.get("execution_status"),
        "test_result": base_analysis.get("test_result"),
        "release_gate": base_analysis.get("release_gate"),
        "diagnosis_confidence": base_analysis.get("diagnosis_confidence"),
        "run_summary": base_analysis.get("run_summary", {}),
        "root_cause_groups": groups,
        "warnings": base_analysis.get("warnings", []),
        "limitations": base_analysis.get("limitations", []),
        "root_cause_groups_total": len(base_analysis.get("root_cause_groups", [])),
        "root_cause_groups_submitted": len(groups),
        "required_output": {
            "overall_note": "A concise overall QA note grounded in the supplied facts",
            "group_insights": [
                {
                    "group_id": "An existing group_id only",
                    "root_cause": "A precise explanation based only on that group's evidence",
                    "runtime_impact": "A realistic impact statement based only on that group's evidence",
                    "required_action": "A prioritized manual remediation action without writing code",
                }
            ],
        },
    }

    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        {
            "role": "user",
            "content": (
                "Improve the deterministic QA wording without changing any fact. "
                "Return valid JSON matching required_output.\n\n"
                + json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
            ),
        },
    ]
