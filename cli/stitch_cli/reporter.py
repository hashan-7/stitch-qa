from pathlib import Path
from datetime import datetime
import json

RISK_ORDER = {
    "UNKNOWN": -1,
    "NONE": 0,
    "INFO": 1,
    "LOW": 2,
    "MEDIUM": 3,
    "HIGH": 4,
    "CRITICAL": 5,
}

FAILED_STATUSES = {"FAIL", "FAILED", "ERROR", "BLOCK_RELEASE"}
UNAVAILABLE_STATUSES = {"UNAVAILABLE", "NOT_AVAILABLE", "ERROR"}
SOURCE_COMPLETE_STATUSES = {"COMPLETED", "PARTIAL"}
REPORT_SCHEMA_VERSION = "2.1"
TOOL_VERSION = "v2.1-development"
SEVERITY_DISPLAY_ORDER = ["CRITICAL", "HIGH", "MEDIUM", "LOW", "INFO", "UNKNOWN"]


def format_list(items):
    if not items:
        return []

    return items


def format_markdown_list(items):
    if not items:
        return "- None"

    return "\n".join(f"- {item}" for item in items)


def format_inline_list(items, default="None"):
    if not items:
        return default

    return ", ".join(str(item) for item in items)


def safe_value(value, default=None):
    if value is None or value == "":
        return default

    return value


def normalize_status(value, default="NOT_AVAILABLE"):
    if value is None or value == "":
        return default

    return str(value).strip().upper()


def normalize_risk(value):
    normalized = normalize_status(value, "UNKNOWN")
    return normalized if normalized in RISK_ORDER else "UNKNOWN"


def highest_risk(*risk_values):
    normalized = [normalize_risk(value) for value in risk_values]
    return max(normalized, key=lambda value: RISK_ORDER[value], default="UNKNOWN")


def is_failed_status(value):
    return normalize_status(value) in FAILED_STATUSES


def is_unavailable_status(value):
    return normalize_status(value) in UNAVAILABLE_STATUSES


def build_execution_status(execution_result):
    if execution_result.get("status"):
        return execution_result["status"]

    if execution_result.get("skipped"):
        return "SKIPPED"

    return "PASSED" if execution_result.get("success") else "FAILED"


def build_execution_summary(project_type, execution_result, source_review_data=None):
    command = safe_value(execution_result.get("command"), "Not available")
    command_profile = safe_value(execution_result.get("command_profile"), "Not available")
    execution_strategy = safe_value(execution_result.get("execution_strategy"), "Not available")

    if execution_result.get("skipped"):
        reason = safe_value(execution_result.get("skip_reason"), "Test execution was not required.")
        source_status = safe_value(
            source_review_data.get("status") if source_review_data else None,
            "NOT_RUN",
        )
        return (
            f"The {project_type} was scanned successfully. Test execution was skipped. "
            f"Reason: {reason} The built-in command `{command}` was not run. "
            f"The built-in execution profile `{command_profile}` was selected but not executed. "
            f"Agent 3 source review status was `{source_status}`."
        )

    outcome = "completed successfully" if execution_result.get("success") else "failed"
    return (
        f"The {project_type} was scanned and executed using the built-in profile "
        f"`{command_profile}` with the `{execution_strategy}` strategy. "
        f"The command `{command}` {outcome} with exit code {execution_result.get('exit_code')}."
    )


def build_static_mapping_json(static_map):
    mapping = {
        "build_file": static_map.get("build_file"),
        "main_source_dir": static_map.get("main_source_dir"),
        "test_source_dir": static_map.get("test_source_dir"),
        "test_source_dirs": format_list(static_map.get("test_source_dirs", [])),
        "main_file": static_map.get("main_file"),
        "suggested_command": static_map.get("suggested_command"),
        "execution_profile": static_map.get("execution_profile"),
        "execution_policy": static_map.get("execution_policy"),
        "execution_strategy": static_map.get("execution_strategy"),
        "has_tests": bool(static_map.get("has_tests")),
        "test_files_count": int(static_map.get("test_files_count", 0)),
        "test_files": format_list(static_map.get("test_files", [])),
        "test_framework": static_map.get("test_framework"),
        "test_detection_source": static_map.get("test_detection_source"),
        "test_file_patterns": format_list(static_map.get("test_file_patterns", [])),
        "configured_test_paths": format_list(static_map.get("configured_test_paths", [])),
        "test_detection_warning": static_map.get("test_detection_warning"),
    }

    if static_map.get("has_maven_wrapper") is not None:
        mapping["has_maven_wrapper"] = static_map.get("has_maven_wrapper")

    if static_map.get("wrapper_command"):
        mapping["wrapper_command"] = static_map.get("wrapper_command")

    if static_map.get("wrapper_recommendation"):
        mapping["wrapper_recommendation"] = static_map.get("wrapper_recommendation")

    return mapping


def build_static_mapping_markdown(static_map):
    lines = [
        f"- Build File: {safe_value(static_map.get('build_file'), 'Not available')}",
        f"- Main Source Directory: {safe_value(static_map.get('main_source_dir'), 'Not available')}",
        f"- Test Source Directory: {safe_value(static_map.get('test_source_dir'), 'Not available')}",
        f"- Test Source Directories: {format_inline_list(static_map.get('test_source_dirs', []))}",
        f"- Main File: {safe_value(static_map.get('main_file'), 'Not available')}",
        f"- Suggested Command: {safe_value(static_map.get('suggested_command'), 'Not available')}",
        f"- Execution Profile: {safe_value(static_map.get('execution_profile'), 'Not available')}",
        f"- Execution Policy: {safe_value(static_map.get('execution_policy'), 'Not available')}",
        f"- Execution Strategy: {safe_value(static_map.get('execution_strategy'), 'Not available')}",
        f"- Tests Found: {'Yes' if static_map.get('has_tests') else 'No'}",
        f"- Test Files Count: {static_map.get('test_files_count', 0)}",
        f"- Test Framework: {safe_value(static_map.get('test_framework'), 'Not available')}",
        f"- Test Detection Source: {safe_value(static_map.get('test_detection_source'), 'Not available')}",
        f"- Test File Patterns: {format_inline_list(static_map.get('test_file_patterns', []))}",
        f"- Configured Test Paths: {format_inline_list(static_map.get('configured_test_paths', []))}",
    ]

    if static_map.get("test_detection_warning"):
        lines.append(f"- Test Detection Warning: {static_map.get('test_detection_warning')}")

    if static_map.get("has_maven_wrapper"):
        lines.append(f"- Maven Wrapper: {static_map.get('has_maven_wrapper')}")
        lines.append(
            f"- Wrapper Command: {safe_value(static_map.get('wrapper_command'), 'Not available')}"
        )

    if static_map.get("wrapper_recommendation"):
        lines.append(f"- Wrapper Recommendation: {static_map.get('wrapper_recommendation')}")

    return "\n".join(lines)


def build_source_discovery_json(source_review):
    return {
        "supported": bool(source_review.get("supported")),
        "source_files_count": int(source_review.get("source_files_count", 0)),
        "source_files": format_list(source_review.get("source_files", [])),
        "file_extensions": format_list(source_review.get("file_extensions", [])),
        "excluded_test_files_count": int(source_review.get("excluded_test_files_count", 0)),
        "excluded_sensitive_files_count": int(source_review.get("excluded_sensitive_files_count", 0)),
        "unreadable_files_count": int(source_review.get("unreadable_files_count", 0)),
        "warning": source_review.get("warning"),
    }


def build_source_review_json(source_review_data):
    if not source_review_data:
        return {
            "status": "NOT_RUN",
            "agent": None,
            "mode": None,
            "summary": None,
            "risk_level": "UNKNOWN",
            "release_recommendation": "QA_INCOMPLETE",
            "reviewed_files_count": 0,
            "findings_count": 0,
            "severity_summary": {},
            "category_summary": {},
            "findings": [],
            "warnings": [],
            "limitations": [],
            "verification": None,
            "llm_error": None,
            "coverage": {},
        }

    return {
        "status": source_review_data.get("status"),
        "agent": source_review_data.get("agent"),
        "mode": source_review_data.get("mode"),
        "summary": source_review_data.get("summary"),
        "risk_level": source_review_data.get("risk_level"),
        "release_recommendation": source_review_data.get("release_recommendation"),
        "reviewed_files_count": int(source_review_data.get("reviewed_files_count", 0)),
        "findings_count": int(source_review_data.get("findings_count", 0)),
        "severity_summary": source_review_data.get("severity_summary", {}),
        "category_summary": source_review_data.get("category_summary", {}),
        "findings": format_list(source_review_data.get("findings", [])),
        "warnings": format_list(source_review_data.get("warnings", [])),
        "limitations": format_list(source_review_data.get("limitations", [])),
        "verification": source_review_data.get("verification"),
        "llm_error": source_review_data.get("llm_error"),
        "coverage": source_review_data.get("coverage", {}),
    }


def build_log_agent_json(agent_data):
    return {
        "agent": safe_value(agent_data.get("agent") if agent_data else None),
        "mode": safe_value(agent_data.get("mode") if agent_data else None),
        "final_status": safe_value(agent_data.get("final_status") if agent_data else None),
        "summary": safe_value(agent_data.get("summary") if agent_data else None),
        "root_cause": safe_value(agent_data.get("root_cause") if agent_data else None),
        "recommendation": safe_value(agent_data.get("recommendation") if agent_data else None),
        "issues": format_list(agent_data.get("issues") if agent_data else []),
        "warnings": format_list(agent_data.get("warnings") if agent_data else []),
        "llm_error": safe_value(agent_data.get("llm_error") if agent_data else None),
    }


def build_repair_agent_json(repair_data):
    return {
        "agent": safe_value(repair_data.get("agent") if repair_data else None),
        "mode": safe_value(repair_data.get("mode") if repair_data else None),
        "status": safe_value(repair_data.get("status") if repair_data else None),
        "risk_level": safe_value(repair_data.get("risk_level") if repair_data else None),
        "auto_apply": safe_value(repair_data.get("auto_apply") if repair_data else None),
        "summary": safe_value(repair_data.get("summary") if repair_data else None),
        "suggestions": format_list(repair_data.get("suggestions") if repair_data else []),
        "next_action": safe_value(repair_data.get("next_action") if repair_data else None),
        "warnings": format_list(repair_data.get("warnings") if repair_data else []),
        "llm_error": safe_value(repair_data.get("llm_error") if repair_data else None),
    }


def build_code_agent_json(code_data):
    return {
        "agent": safe_value(code_data.get("agent") if code_data else None),
        "mode": safe_value(code_data.get("mode") if code_data else None),
        "status": safe_value(code_data.get("status") if code_data else None),
        "risk_level": safe_value(code_data.get("risk_level") if code_data else None),
        "auto_apply": safe_value(code_data.get("auto_apply") if code_data else None),
        "summary": safe_value(code_data.get("summary") if code_data else None),
        "suggested_patch": safe_value(code_data.get("suggested_patch") if code_data else None),
        "verification": safe_value(code_data.get("verification") if code_data else None),
        "warnings": format_list(code_data.get("warnings") if code_data else []),
        "llm_error": safe_value(code_data.get("llm_error") if code_data else None),
    }


def build_agent_workflow_status(
    execution_result,
    source_review_data=None,
    agent_data=None,
    repair_data=None,
    code_data=None,
    workflow_context=None,
):
    workflow_context = workflow_context or {}
    tests_executed = bool(execution_result.get("executed"))

    if workflow_context.get("analyze_requested"):
        log_status = normalize_status(
            agent_data.get("final_status") if agent_data else None,
            "UNAVAILABLE" if tests_executed else "NOT_RUN",
        )
    else:
        log_status = "NOT_REQUESTED"

    if workflow_context.get("repair_requested"):
        repair_status = normalize_status(
            repair_data.get("status") if repair_data else None,
            "UNAVAILABLE" if tests_executed else "NOT_RUN",
        )
    else:
        repair_status = "NOT_REQUESTED"

    if workflow_context.get("code_fix_requested"):
        code_status = normalize_status(
            code_data.get("status") if code_data else None,
            "UNAVAILABLE" if tests_executed else "NOT_RUN",
        )
    else:
        code_status = "NOT_REQUESTED"

    return {
        "source_review": normalize_status(
            source_review_data.get("status") if source_review_data else None,
            "NOT_RUN",
        ),
        "test_execution": normalize_status(build_execution_status(execution_result)),
        "log_analysis": log_status,
        "repair_guidance": repair_status,
        "code_repair_guidance": code_status,
    }


def build_qa_decision(
    execution_result,
    source_review_data=None,
    agent_data=None,
    repair_data=None,
    code_data=None,
    workflow_context=None,
):
    workflow_context = workflow_context or {}
    workflow_status = build_agent_workflow_status(
        execution_result,
        source_review_data,
        agent_data,
        repair_data,
        code_data,
        workflow_context,
    )
    source_status = workflow_status["source_review"]
    source_review_data = source_review_data or {}
    source_coverage = source_review_data.get("coverage", {})
    discovered_source_files = int(source_coverage.get("discovered_files_count", 0))
    source_available = source_status in SOURCE_COMPLETE_STATUSES
    no_source_files = source_status == "NO_SOURCE_FILES"
    source_unavailable = source_status == "UNAVAILABLE" and discovered_source_files > 0
    tests_executed = bool(execution_result.get("executed"))
    tests_skipped = bool(execution_result.get("skipped"))
    execution_failed = tests_executed and not bool(execution_result.get("success"))
    execution_passed = tests_executed and bool(execution_result.get("success"))
    log_status = workflow_status["log_analysis"]
    repair_status = workflow_status["repair_guidance"]
    code_status = workflow_status["code_repair_guidance"]
    requested_agent_unavailable = (
        workflow_context.get("analyze_requested") and is_unavailable_status(log_status)
    ) or (
        workflow_context.get("repair_requested") and is_unavailable_status(repair_status)
    ) or (
        workflow_context.get("code_fix_requested") and is_unavailable_status(code_status)
    )
    log_failed = agent_data and is_failed_status(agent_data.get("final_status"))
    source_risk = normalize_risk(source_review_data.get("risk_level"))
    repair_risk = normalize_risk(repair_data.get("risk_level") if repair_data else None)
    code_risk = normalize_risk(code_data.get("risk_level") if code_data else None)
    execution_risk = "HIGH" if execution_failed else "NONE"
    log_risk = "HIGH" if log_failed else "NONE"
    combined_risk = highest_risk(
        source_risk,
        repair_risk,
        code_risk,
        execution_risk,
        log_risk,
    )
    reasons = []

    if source_available:
        reasons.append(
            f"Agent 3 source review completed with risk level {source_risk}."
        )
    elif no_source_files:
        reasons.append("No eligible application source files were available for Agent 3 review.")
    elif source_unavailable:
        reasons.append("Agent 3 source review was unavailable for discovered application source files.")
    else:
        reasons.append(f"Agent 3 source review status was {source_status}.")

    if tests_skipped:
        reasons.append("Test execution was skipped because no compatible tests were detected.")
    elif execution_passed:
        reasons.append("The validated built-in test command completed successfully.")
    elif execution_failed:
        reasons.append(
            f"The validated built-in test command failed with exit code {execution_result.get('exit_code')}."
        )

    if workflow_context.get("analyze_requested"):
        reasons.append(f"Agent 1 runtime log analysis status was {log_status}.")

    if workflow_context.get("repair_requested"):
        reasons.append(f"Agent 2 repair guidance status was {repair_status}.")

    if workflow_context.get("code_fix_requested"):
        reasons.append(f"Agent 3 code-repair guidance status was {code_status}.")

    source_release = normalize_status(
        source_review_data.get("release_recommendation"),
        "UNKNOWN",
    )

    if execution_failed:
        status = "FAIL"
        release_recommendation = "BLOCK_RELEASE"
        ci_exit_code = 1
    elif source_unavailable or requested_agent_unavailable:
        status = "QA_INCOMPLETE"
        release_recommendation = "QA_INCOMPLETE"
        ci_exit_code = 1
    elif source_release == "QA_INCOMPLETE":
        status = "QA_INCOMPLETE"
        release_recommendation = "QA_INCOMPLETE"
        ci_exit_code = 1
    elif source_release == "BLOCK_RELEASE" or RISK_ORDER[combined_risk] >= RISK_ORDER["HIGH"]:
        status = "BLOCK_RELEASE"
        release_recommendation = "BLOCK_RELEASE"
        ci_exit_code = 1
    elif tests_skipped:
        if source_available:
            status = "REVIEW_COMPLETED_WITHOUT_TESTS"
            release_recommendation = "REVIEW_REQUIRED"
            ci_exit_code = 0
        else:
            status = "QA_INCOMPLETE"
            release_recommendation = "QA_INCOMPLETE"
            ci_exit_code = 1
    elif execution_passed and no_source_files:
        status = "TESTS_PASSED_WITHOUT_SOURCE_REVIEW"
        release_recommendation = "REVIEW_REQUIRED"
        ci_exit_code = 0
    elif RISK_ORDER[combined_risk] >= RISK_ORDER["MEDIUM"]:
        status = "REVIEW_REQUIRED"
        release_recommendation = "REVIEW_REQUIRED"
        ci_exit_code = 0
    elif RISK_ORDER[combined_risk] >= RISK_ORDER["LOW"]:
        status = "PASS_WITH_WARNINGS"
        release_recommendation = "ALLOW_WITH_WARNINGS"
        ci_exit_code = 0
    else:
        status = "PASS"
        release_recommendation = "READY_FOR_RELEASE"
        ci_exit_code = 0

    if source_status == "PARTIAL" or requested_agent_unavailable:
        completeness = "PARTIAL"
    elif tests_skipped and source_available:
        completeness = "SOURCE_ONLY"
    elif tests_executed and no_source_files:
        completeness = "TEST_ONLY"
    elif tests_executed and source_available:
        completeness = "COMPLETE"
    else:
        completeness = "INCOMPLETE"

    return {
        "status": status,
        "risk_level": combined_risk,
        "release_recommendation": release_recommendation,
        "completeness": completeness,
        "ci_exit_code": ci_exit_code,
        "reasons": reasons,
        "workflow_status": workflow_status,
    }


def format_summary_mapping(mapping):
    if not mapping:
        return "None"

    return ", ".join(f"{key}: {value}" for key, value in mapping.items())


def finding_line_sort_value(value):
    if value is None or value == "":
        return 0

    try:
        return int(str(value).split("-")[0].split(":")[0].strip())
    except (TypeError, ValueError):
        return 0


def normalize_findings(findings):
    normalized_findings = []

    for finding in findings or []:
        normalized_finding = dict(finding)
        normalized_finding["severity"] = normalize_risk(finding.get("severity"))
        normalized_findings.append(normalized_finding)

    return sorted(
        normalized_findings,
        key=lambda finding: (
            -RISK_ORDER.get(finding.get("severity", "UNKNOWN"), -1),
            str(finding.get("file_path") or ""),
            finding_line_sort_value(finding.get("line")),
            str(finding.get("title") or ""),
        ),
    )


def build_findings_summary(findings):
    summary = {severity.lower(): 0 for severity in SEVERITY_DISPLAY_ORDER}

    for finding in normalize_findings(findings):
        severity = finding.get("severity", "UNKNOWN").lower()
        summary[severity] = summary.get(severity, 0) + 1

    summary["total"] = sum(
        count for severity, count in summary.items() if severity != "total"
    )
    return summary


def format_markdown_table(headers, rows):
    if not rows:
        return "No data available."

    header_row = "| " + " | ".join(str(header) for header in headers) + " |"
    separator_row = "| " + " | ".join("---" for _ in headers) + " |"
    data_rows = [
        "| "
        + " | ".join(
            str(value).replace("\n", " ").replace("|", "\\|")
            for value in row
        )
        + " |"
        for row in rows
    ]
    return "\n".join([header_row, separator_row, *data_rows])


def format_source_findings(findings):
    normalized_findings = normalize_findings(findings)

    if not normalized_findings:
        return "No source-code findings were reported."

    sections = []

    for severity in SEVERITY_DISPLAY_ORDER:
        severity_findings = [
            finding
            for finding in normalized_findings
            if finding.get("severity") == severity
        ]

        if not severity_findings:
            continue

        sections.append(f"#### {severity} Findings")

        for finding in severity_findings:
            title = safe_value(finding.get("title"), "Source-code finding")
            file_path = safe_value(finding.get("file_path"), "Project-level")
            line = finding.get("line")
            location = f"{file_path}:{line}" if line else file_path
            sections.append(
                f"##### [{severity}] {title}\n\n"
                f"- Finding ID: {safe_value(finding.get('id'), 'Not available')}\n"
                f"- Location: `{location}`\n"
                f"- Category: {safe_value(finding.get('category'), 'Not available')}\n"
                f"- Confidence: {safe_value(finding.get('confidence'), 'Not available')}\n\n"
                f"**Evidence**\n\n"
                f"{safe_value(finding.get('evidence'), 'Not available')}\n\n"
                f"**Potential Impact**\n\n"
                f"{safe_value(finding.get('impact'), 'Not available')}\n\n"
                f"**Recommended Action**\n\n"
                f"{safe_value(finding.get('recommendation'), 'Not available')}"
            )

    return "\n\n".join(sections)


def build_scope_summary(
    static_map,
    source_discovery,
    source_review_json,
    execution_result,
    qa_decision,
):
    workflow_status = qa_decision.get("workflow_status", {})
    return {
        "source_review_supported": bool(source_discovery.get("supported")),
        "source_files_discovered": int(source_discovery.get("source_files_count", 0)),
        "source_files_reviewed": int(source_review_json.get("reviewed_files_count", 0)),
        "source_review_status": normalize_status(
            source_review_json.get("status"),
            "NOT_RUN",
        ),
        "tests_detected": bool(static_map.get("has_tests")),
        "test_files_detected": int(static_map.get("test_files_count", 0)),
        "test_framework": safe_value(static_map.get("test_framework")),
        "test_execution_status": normalize_status(
            build_execution_status(execution_result),
            "NOT_RUN",
        ),
        "test_execution_performed": bool(execution_result.get("executed")),
        "evidence_completeness": qa_decision.get("completeness"),
        "workflow_status": workflow_status,
    }


def build_report_limitations(
    static_map,
    source_review_json,
    execution_result,
    qa_decision,
    log_agent_json,
    repair_agent_json,
    code_agent_json,
):
    limitations = []
    source_status = normalize_status(source_review_json.get("status"), "NOT_RUN")
    workflow_status = qa_decision.get("workflow_status", {})

    if source_status == "UNAVAILABLE":
        limitations.append(
            "Agent 3 source-code review was unavailable, so source-review evidence is incomplete."
        )
    elif source_status == "NO_SOURCE_FILES":
        limitations.append(
            "No eligible application source files were available for source-code review."
        )
    elif source_status == "PARTIAL":
        limitations.append(
            "Agent 3 completed only a partial source review; review coverage is incomplete."
        )

    if execution_result.get("skipped"):
        limitations.append(
            safe_value(
                execution_result.get("skip_reason"),
                "Automated test execution was skipped.",
            )
        )
    elif not execution_result.get("executed"):
        limitations.append("Automated test execution was not performed.")

    if not static_map.get("has_tests") and not execution_result.get("skipped"):
        limitations.append(
            "No compatible automated tests were detected, so runtime behavior was not verified by the built-in test runner."
        )

    status_labels = {
        "log_analysis": "Agent 1 runtime log analysis",
        "repair_guidance": "Agent 2 repair guidance",
        "code_repair_guidance": "Agent 3 runtime code-repair guidance",
    }

    for key, label in status_labels.items():
        status = normalize_status(workflow_status.get(key), "NOT_REQUESTED")
        if status == "UNAVAILABLE":
            limitations.append(f"{label} was requested but unavailable.")
        elif status == "NOT_RUN":
            limitations.append(f"{label} was requested but could not run in this workflow.")

    for item in source_review_json.get("limitations", []):
        if item and item not in limitations:
            limitations.append(str(item))

    llm_errors = [
        log_agent_json.get("llm_error"),
        repair_agent_json.get("llm_error"),
        code_agent_json.get("llm_error"),
        source_review_json.get("llm_error"),
    ]
    if any(llm_errors):
        limitations.append(
            "One or more AI-agent responses used fallback or incomplete output because an LLM request failed."
        )

    return list(dict.fromkeys(limitations))


def build_next_actions(
    qa_decision,
    static_map,
    source_review_json,
    execution_result,
):
    actions = []
    status = normalize_status(qa_decision.get("status"), "QA_INCOMPLETE")
    source_status = normalize_status(source_review_json.get("status"), "NOT_RUN")

    if execution_result.get("executed") and not execution_result.get("success"):
        actions.append(
            {
                "priority": "P1",
                "action": "Resolve the validated test-execution failure and rerun Stitch QA before release.",
            }
        )

    if status in {"BLOCK_RELEASE", "FAIL"}:
        actions.append(
            {
                "priority": "P1",
                "action": "Keep the release blocked until all confirmed release-blocking conditions are resolved.",
            }
        )

    if source_status == "UNAVAILABLE":
        actions.append(
            {
                "priority": "P1",
                "action": "Restore Agent 3 availability and rerun the source-code review to complete QA evidence.",
            }
        )

    if not static_map.get("has_tests"):
        actions.append(
            {
                "priority": "P2",
                "action": "Add compatible automated tests for critical behavior and rerun the validated test workflow.",
            }
        )

    for finding in normalize_findings(source_review_json.get("findings", [])):
        recommendation = safe_value(finding.get("recommendation"))
        if not recommendation:
            continue

        severity = finding.get("severity", "UNKNOWN")
        if severity in {"CRITICAL", "HIGH"}:
            priority = "P1"
        elif severity == "MEDIUM":
            priority = "P2"
        else:
            priority = "P3"

        action = {
            "priority": priority,
            "action": str(recommendation),
            "finding_id": safe_value(finding.get("id")),
            "severity": severity,
        }
        if action not in actions:
            actions.append(action)

    if not actions:
        actions.append(
            {
                "priority": "P3",
                "action": "Keep the current QA baseline and rerun Stitch QA after future project changes.",
            }
        )

    unique_actions = []
    seen_actions = set()
    for action in actions:
        action_key = str(action.get("action", "")).strip().lower()
        if not action_key or action_key in seen_actions:
            continue
        seen_actions.add(action_key)
        unique_actions.append(action)

    priority_order = {"P1": 1, "P2": 2, "P3": 3}
    return sorted(
        unique_actions,
        key=lambda item: (
            priority_order.get(item.get("priority"), 9),
            item.get("action", ""),
        ),
    )


def format_next_actions(actions):
    if not actions:
        return "- None"

    lines = []
    for action in actions:
        finding_reference = ""
        if action.get("finding_id"):
            finding_reference = f" (Finding: {action.get('finding_id')})"
        lines.append(
            f"- **{action.get('priority', 'P3')}** — {action.get('action')}{finding_reference}"
        )
    return "\n".join(lines)


def build_source_review_markdown(source_review_data):
    data = build_source_review_json(source_review_data)
    findings = normalize_findings(data["findings"])
    findings_summary = build_findings_summary(findings)
    findings_text = format_source_findings(findings)
    warnings_text = format_markdown_list(data["warnings"])
    limitations_text = format_markdown_list(data["limitations"])
    coverage = data.get("coverage", {})
    findings_table = format_markdown_table(
        ["Severity", "Count"],
        [
            [severity, findings_summary.get(severity.lower(), 0)]
            for severity in SEVERITY_DISPLAY_ORDER
        ],
    )

    return (
        "## Source Code QA Review\n\n"
        "### Review Summary\n\n"
        f"- Status: **{safe_value(data.get('status'), 'NOT_RUN')}**\n"
        f"- Agent: {safe_value(data.get('agent'), 'Not available')}\n"
        f"- Mode: {safe_value(data.get('mode'), 'Not available')}\n"
        f"- Reviewed Files: {data.get('reviewed_files_count', 0)}\n"
        f"- Total Findings: {findings_summary.get('total', 0)}\n"
        f"- Risk Level: **{safe_value(data.get('risk_level'), 'UNKNOWN')}**\n"
        f"- Release Recommendation: **{safe_value(data.get('release_recommendation'), 'QA_INCOMPLETE')}**\n\n"
        f"{safe_value(data.get('summary'), 'Source review was not run.')}\n\n"
        "### Findings Overview\n\n"
        f"{findings_table}\n\n"
        f"- Category Summary: {format_summary_mapping(data.get('category_summary'))}\n\n"
        "### Review Coverage\n\n"
        f"- Discovered Files: {coverage.get('discovered_files_count', 0)}\n"
        f"- Submitted Files: {coverage.get('submitted_files_count', 0)}\n"
        f"- Submitted Characters: {coverage.get('submitted_chars', 0)}\n"
        f"- Truncated Files: {coverage.get('truncated_files_count', 0)}\n"
        f"- Omitted Files: {coverage.get('omitted_files_count', 0)}\n"
        f"- Read Errors: {coverage.get('read_error_files_count', 0)}\n\n"
        "### Prioritized Findings\n\n"
        f"{findings_text}\n\n"
        "### Source Review Warnings\n\n"
        f"{warnings_text}\n\n"
        "### Source Review Limitations\n\n"
        f"{limitations_text}\n\n"
        "### Verification Guidance\n\n"
        f"{safe_value(data.get('verification'), 'Rerun Stitch QA after addressing confirmed findings.')}\n\n"
    )


def build_qa_decision_markdown(qa_decision):
    workflow_status = qa_decision.get("workflow_status", {})
    decision_table = format_markdown_table(
        ["Decision Field", "Result"],
        [
            ["Final QA Status", f"**{qa_decision.get('status')}**"],
            ["Combined Risk Level", f"**{qa_decision.get('risk_level')}**"],
            [
                "Release Recommendation",
                f"**{qa_decision.get('release_recommendation')}**",
            ],
            ["QA Evidence Completeness", f"**{qa_decision.get('completeness')}**"],
            ["CI Exit Code", qa_decision.get("ci_exit_code")],
        ],
    )
    workflow_table = format_markdown_table(
        ["Workflow Component", "Status"],
        [
            ["Agent 3 Source Review", workflow_status.get("source_review", "NOT_RUN")],
            ["Validated Test Execution", workflow_status.get("test_execution", "NOT_RUN")],
            ["Agent 1 Log Analysis", workflow_status.get("log_analysis", "NOT_REQUESTED")],
            ["Agent 2 Repair Guidance", workflow_status.get("repair_guidance", "NOT_REQUESTED")],
            [
                "Agent 3 Code Repair Guidance",
                workflow_status.get("code_repair_guidance", "NOT_REQUESTED"),
            ],
        ],
    )
    return (
        "## Combined QA Decision\n\n"
        f"{decision_table}\n\n"
        "### Decision Reasons\n\n"
        f"{format_markdown_list(qa_decision.get('reasons', []))}\n\n"
        "### Agent Workflow Status\n\n"
        f"{workflow_table}\n\n"
    )


def build_agent_details_markdown(
    log_agent_json,
    repair_agent_json,
    code_agent_json,
):
    log_section = (
        "### Agent 1 Runtime Log Analysis\n\n"
        f"- Agent: {safe_value(log_agent_json.get('agent'), 'Not available')}\n"
        f"- Mode: {safe_value(log_agent_json.get('mode'), 'Not available')}\n"
        f"- Final Status: {safe_value(log_agent_json.get('final_status'), 'Not requested')}\n\n"
        "**Summary**\n\n"
        f"{safe_value(log_agent_json.get('summary'), 'Not requested')}\n\n"
        "**Root Cause**\n\n"
        f"{safe_value(log_agent_json.get('root_cause'), 'Not available')}\n\n"
        "**Recommendation**\n\n"
        f"{safe_value(log_agent_json.get('recommendation'), 'Not available')}\n\n"
        "**Issues**\n\n"
        f"{format_markdown_list(log_agent_json.get('issues', []))}\n\n"
        "**Warnings**\n\n"
        f"{format_markdown_list(log_agent_json.get('warnings', []))}\n\n"
    )

    if log_agent_json.get("llm_error"):
        log_section += (
            "**LLM Error**\n\n"
            f"{log_agent_json.get('llm_error')}\n\n"
        )

    repair_section = (
        "### Agent 2 Repair Guidance\n\n"
        f"- Agent: {safe_value(repair_agent_json.get('agent'), 'Not available')}\n"
        f"- Mode: {safe_value(repair_agent_json.get('mode'), 'Not available')}\n"
        f"- Status: {safe_value(repair_agent_json.get('status'), 'Not requested')}\n"
        f"- Risk Level: {safe_value(repair_agent_json.get('risk_level'), 'Not available')}\n"
        f"- Auto Apply: {safe_value(repair_agent_json.get('auto_apply'), 'Not available')}\n\n"
        "**Summary**\n\n"
        f"{safe_value(repair_agent_json.get('summary'), 'Not requested')}\n\n"
        "**Suggestions**\n\n"
        f"{format_markdown_list(repair_agent_json.get('suggestions', []))}\n\n"
        "**Next Action**\n\n"
        f"{safe_value(repair_agent_json.get('next_action'), 'Not available')}\n\n"
        "**Warnings**\n\n"
        f"{format_markdown_list(repair_agent_json.get('warnings', []))}\n\n"
    )

    if repair_agent_json.get("llm_error"):
        repair_section += (
            "**LLM Error**\n\n"
            f"{repair_agent_json.get('llm_error')}\n\n"
        )

    code_section = (
        "### Agent 3 Runtime Code Repair Guidance\n\n"
        f"- Agent: {safe_value(code_agent_json.get('agent'), 'Not available')}\n"
        f"- Mode: {safe_value(code_agent_json.get('mode'), 'Not available')}\n"
        f"- Status: {safe_value(code_agent_json.get('status'), 'Not requested')}\n"
        f"- Risk Level: {safe_value(code_agent_json.get('risk_level'), 'Not available')}\n"
        f"- Auto Apply: {safe_value(code_agent_json.get('auto_apply'), 'Not available')}\n\n"
        "**Summary**\n\n"
        f"{safe_value(code_agent_json.get('summary'), 'Not requested')}\n\n"
        "**Suggested Patch**\n\n"
        f"{safe_value(code_agent_json.get('suggested_patch'), 'No direct patch generated. Manual review required.')}\n\n"
        "**Verification**\n\n"
        f"{safe_value(code_agent_json.get('verification'), 'Rerun Stitch QA after applying any manual changes.')}\n\n"
        "**Warnings**\n\n"
        f"{format_markdown_list(code_agent_json.get('warnings', []))}\n\n"
    )

    if code_agent_json.get("llm_error"):
        code_section += (
            "**LLM Error**\n\n"
            f"{code_agent_json.get('llm_error')}\n\n"
        )

    return "## Agent Workflow Details\n\n" + log_section + repair_section + code_section


def generate_report(
    scan_result,
    execution_result,
    agent_data=None,
    repair_data=None,
    code_data=None,
    source_review_data=None,
    qa_decision=None,
    workflow_context=None,
):
    project_path = Path(scan_result["project_path"])
    project_type = scan_result.get("project_type", "Unknown")
    static_map = scan_result.get("static_map", {})
    source_discovery = scan_result.get("source_review", {})
    generated_at = datetime.now().astimezone().isoformat(timespec="seconds")

    md_report_path = project_path / "STITCH_QA_REPORT.md"
    json_report_path = project_path / "STITCH_QA_REPORT.json"

    if execution_result is None:
        coming_soon_message = static_map.get(
            "coming_soon_message",
            "Support for this project type is planned for a future release.",
        )
        executive_summary = {
            "final_status": "SKIPPED",
            "risk_level": "UNKNOWN",
            "release_recommendation": "NOT_APPLICABLE",
            "evidence_completeness": "NOT_STARTED",
            "ci_exit_code": 0,
        }
        json_content = {
            "report_metadata": {
                "schema_version": REPORT_SCHEMA_VERSION,
                "tool_version": TOOL_VERSION,
                "generated_at": generated_at,
            },
            "executive_summary": executive_summary,
            "final_status": "SKIPPED",
            "project_type": project_type,
            "coming_soon_message": coming_soon_message,
            "skip_reason": "Unsupported or unrecognized project type.",
            "exit_code": 0,
            "generated_at": generated_at,
        }
        md_content = (
            "# Stitch QA Report\n\n"
            "## Executive QA Summary\n\n"
            + format_markdown_table(
                ["Field", "Result"],
                [
                    ["Final QA Status", "**SKIPPED**"],
                    ["Detected Project Type", project_type],
                    ["Release Recommendation", "**NOT_APPLICABLE**"],
                    ["CI Exit Code", 0],
                ],
            )
            + "\n\n"
            "## Scope Decision\n\n"
            f"{coming_soon_message}\n\n"
            "Stitch QA V2 currently supports:\n\n"
            "- **Java Maven** (`pom.xml`)\n"
            "- **Python** (`requirements.txt` or `pyproject.toml`)\n\n"
            "## Action Taken\n\n"
            "QA execution was skipped. No tests or AI-agent workflows were run.\n\n"
            "## Report Metadata\n\n"
            f"- Report Schema Version: {REPORT_SCHEMA_VERSION}\n"
            f"- Tool Version: {TOOL_VERSION}\n"
            f"- Generated At: {generated_at}\n"
        )
        md_report_path.write_text(md_content, encoding="utf-8")
        json_report_path.write_text(json.dumps(json_content, indent=2), encoding="utf-8")
        return md_report_path

    qa_decision = qa_decision or build_qa_decision(
        execution_result,
        source_review_data,
        agent_data,
        repair_data,
        code_data,
        workflow_context,
    )
    final_status = qa_decision["status"]
    project_recommendations = scan_result.get("project_recommendations", [])
    execution_status = build_execution_status(execution_result)
    execution_summary = build_execution_summary(
        project_type,
        execution_result,
        source_review_data,
    )
    stdout_text = execution_result.get("stdout", "")[-2000:]
    stderr_text = execution_result.get("stderr", "")[-2000:]
    source_review_json = build_source_review_json(source_review_data)
    source_review_json["findings"] = normalize_findings(source_review_json.get("findings", []))
    source_review_json["findings_count"] = len(source_review_json["findings"])
    log_agent_json = build_log_agent_json(agent_data)
    repair_agent_json = build_repair_agent_json(repair_data)
    code_agent_json = build_code_agent_json(code_data)
    findings_summary = build_findings_summary(source_review_json["findings"])
    qa_scope = build_scope_summary(
        static_map,
        source_discovery,
        source_review_json,
        execution_result,
        qa_decision,
    )
    limitations = build_report_limitations(
        static_map,
        source_review_json,
        execution_result,
        qa_decision,
        log_agent_json,
        repair_agent_json,
        code_agent_json,
    )
    next_actions = build_next_actions(
        qa_decision,
        static_map,
        source_review_json,
        execution_result,
    )
    executive_summary = {
        "final_status": final_status,
        "risk_level": qa_decision.get("risk_level"),
        "release_recommendation": qa_decision.get("release_recommendation"),
        "evidence_completeness": qa_decision.get("completeness"),
        "ci_exit_code": qa_decision.get("ci_exit_code"),
        "source_review_status": source_review_json.get("status"),
        "test_execution_status": execution_status,
        "total_source_findings": findings_summary.get("total", 0),
    }

    json_content = {
        "report_metadata": {
            "schema_version": REPORT_SCHEMA_VERSION,
            "tool_version": TOOL_VERSION,
            "generated_at": generated_at,
        },
        "executive_summary": executive_summary,
        "project": {
            "path": scan_result["project_path"],
            "type": scan_result["project_type"],
            "total_files": scan_result["total_files"],
            "total_folders": scan_result["total_folders"],
            "ignored_items": scan_result["ignored_items"],
        },
        "qa_scope": qa_scope,
        "static_mapping": build_static_mapping_json(static_map),
        "source_review_discovery": build_source_discovery_json(source_discovery),
        "findings_summary": findings_summary,
        "source_review": source_review_json,
        "project_recommendations": format_list(project_recommendations),
        "execution": {
            "status": execution_status,
            "executed": bool(execution_result.get("executed", True)),
            "skipped": bool(execution_result.get("skipped", False)),
            "skip_reason": execution_result.get("skip_reason"),
            "command": execution_result.get("command"),
            "command_profile": execution_result.get("command_profile"),
            "execution_policy": execution_result.get("execution_policy"),
            "execution_strategy": execution_result.get("execution_strategy"),
            "shell_enabled": bool(execution_result.get("shell_enabled", False)),
            "command_args": format_list(execution_result.get("command_args", [])),
            "executable": execution_result.get("executable"),
            "validation_status": execution_result.get("validation_status"),
            "validation_error": execution_result.get("validation_error"),
            "timeout_seconds": execution_result.get("timeout_seconds"),
            "success": execution_result.get("success"),
            "exit_code": execution_result.get("exit_code"),
            "failure_type": execution_result.get("failure_type"),
            "help_message": execution_result.get("help_message"),
        },
        "agents": {
            "log_analysis": log_agent_json,
            "repair_guidance": repair_agent_json,
            "code_repair_guidance": code_agent_json,
        },
        "log_agent": log_agent_json,
        "repair_agent": repair_agent_json,
        "code_agent_repair": code_agent_json,
        "qa_decision": qa_decision,
        "limitations": limitations,
        "next_actions": next_actions,
        "evidence": {
            "stdout": stdout_text,
            "stderr": stderr_text,
        },
        "final_status": final_status,
        "generated_at": generated_at,
    }
    json_report_path.write_text(
        json.dumps(json_content, indent=2),
        encoding="utf-8",
    )

    command_text = safe_value(execution_result.get("command"), "Not available")
    command_profile_text = safe_value(execution_result.get("command_profile"), "Not available")
    execution_policy_text = safe_value(execution_result.get("execution_policy"), "Not available")
    execution_strategy_text = safe_value(execution_result.get("execution_strategy"), "Not available")
    command_args_text = format_inline_list(
        execution_result.get("command_args", []),
        "Not resolved because execution was skipped",
    )
    executable_text = safe_value(execution_result.get("executable"), "Not available")
    validation_status_text = safe_value(execution_result.get("validation_status"), "Not available")
    validation_error_text = safe_value(execution_result.get("validation_error"), "None")
    skip_reason_text = safe_value(execution_result.get("skip_reason"), "None")
    static_mapping_text = build_static_mapping_markdown(static_map)
    detected_test_files_text = format_markdown_list(static_map.get("test_files", []))
    project_recommendations_text = format_markdown_list(project_recommendations)
    source_review_section = build_source_review_markdown(source_review_data)
    qa_decision_section = build_qa_decision_markdown(qa_decision)
    agent_details_section = build_agent_details_markdown(
        log_agent_json,
        repair_agent_json,
        code_agent_json,
    )

    executive_table = format_markdown_table(
        ["Field", "Result"],
        [
            ["Final QA Status", f"**{final_status}**"],
            ["Combined Risk Level", f"**{qa_decision.get('risk_level')}**"],
            [
                "Release Recommendation",
                f"**{qa_decision.get('release_recommendation')}**",
            ],
            ["QA Evidence Completeness", f"**{qa_decision.get('completeness')}**"],
            ["CI Exit Code", qa_decision.get("ci_exit_code")],
            ["Project Type", scan_result["project_type"]],
            ["Source Review Status", source_review_json.get("status")],
            ["Test Execution Status", execution_status],
            ["Total Source Findings", findings_summary.get("total", 0)],
        ],
    )
    scope_table = format_markdown_table(
        ["Coverage Area", "Result"],
        [
            ["Source Review Supported", "Yes" if qa_scope["source_review_supported"] else "No"],
            ["Application Source Files Discovered", qa_scope["source_files_discovered"]],
            ["Application Source Files Reviewed", qa_scope["source_files_reviewed"]],
            ["Compatible Tests Detected", "Yes" if qa_scope["tests_detected"] else "No"],
            ["Test Files Detected", qa_scope["test_files_detected"]],
            ["Test Framework", safe_value(qa_scope["test_framework"], "Not available")],
            ["Automated Test Execution Performed", "Yes" if qa_scope["test_execution_performed"] else "No"],
            ["Evidence Completeness", qa_scope["evidence_completeness"]],
        ],
    )
    project_table = format_markdown_table(
        ["Project Field", "Value"],
        [
            ["Project Path", scan_result["project_path"]],
            ["Project Type", scan_result["project_type"]],
            ["Total Files", scan_result["total_files"]],
            ["Total Folders", scan_result["total_folders"]],
            ["Ignored Items", scan_result["ignored_items"]],
        ],
    )
    execution_table = format_markdown_table(
        ["Execution Field", "Result"],
        [
            ["Status", execution_status],
            ["Command Profile", command_profile_text],
            ["Execution Policy", execution_policy_text],
            ["Execution Strategy", execution_strategy_text],
            ["Shell Enabled", execution_result.get("shell_enabled", False)],
            ["Validation Status", validation_status_text],
            ["Validation Error", validation_error_text],
            ["Command", f"`{command_text}`"],
            ["Resolved Arguments", f"`{command_args_text}`"],
            ["Resolved Executable", f"`{executable_text}`"],
            ["Timeout Seconds", execution_result.get("timeout_seconds")],
            ["Executed", execution_result.get("executed", True)],
            ["Skipped", execution_result.get("skipped", False)],
            ["Skip Reason", skip_reason_text],
            ["Success", execution_result.get("success")],
            ["Exit Code", execution_result.get("exit_code")],
            ["Failure Type", safe_value(execution_result.get("failure_type"), "None")],
            ["Help Message", safe_value(execution_result.get("help_message"), "None")],
        ],
    )

    if execution_result.get("skipped"):
        evidence_section = (
            "## Technical Evidence\n\n"
            "No runtime evidence logs were generated because the validated test command was not executed.\n\n"
        )
    else:
        evidence_section = (
            "## Technical Evidence\n\n"
            "### STDOUT Snapshot\n\n"
            "```text\n"
            f"{stdout_text or 'No stdout output.'}\n"
            "```\n\n"
            "### STDERR and Warning Snapshot\n\n"
            "```text\n"
            f"{stderr_text or 'No stderr output.'}\n"
            "```\n\n"
        )

    md_content = (
        "# Stitch QA Report\n\n"
        "## Executive QA Summary\n\n"
        f"{executive_table}\n\n"
        "### Overall Assessment\n\n"
        f"{execution_summary}\n\n"
        + qa_decision_section
        + "## QA Scope and Coverage\n\n"
        f"{scope_table}\n\n"
        "### Coverage Notes and Limitations\n\n"
        f"{format_markdown_list(limitations)}\n\n"
        "## Project Overview\n\n"
        f"{project_table}\n\n"
        "### Static Mapping and Test Detection\n\n"
        f"{static_mapping_text}\n\n"
        "### Detected Test Files\n\n"
        f"{detected_test_files_text}\n\n"
        + source_review_section
        + "## Test Execution\n\n"
        f"{execution_table}\n\n"
        + agent_details_section
        + "## Recommendations and Next Actions\n\n"
        "### Prioritized Next Actions\n\n"
        f"{format_next_actions(next_actions)}\n\n"
        "### Project Recommendations\n\n"
        f"{project_recommendations_text}\n\n"
        + evidence_section
        + "## Report Metadata\n\n"
        f"- Report Schema Version: {REPORT_SCHEMA_VERSION}\n"
        f"- Tool Version: {TOOL_VERSION}\n"
        f"- Generated At: {generated_at}\n"
    )
    md_report_path.write_text(md_content, encoding="utf-8")
    return md_report_path
