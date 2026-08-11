from datetime import datetime
from pathlib import Path
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

FAILED_STATUSES = {
    "FAIL",
    "FAILED",
    "ERROR",
    "BLOCK_RELEASE",
}

UNAVAILABLE_STATUSES = {
    "UNAVAILABLE",
    "NOT_AVAILABLE",
    "ERROR",
}

SOURCE_COMPLETE_STATUSES = {
    "COMPLETED",
    "PARTIAL",
}

REPORT_SCHEMA_VERSION = "3.2"
TOOL_VERSION = "v2.2-development"

SEVERITY_DISPLAY_ORDER = [
    "CRITICAL",
    "HIGH",
    "MEDIUM",
    "LOW",
    "INFO",
    "UNKNOWN",
]


def format_list(items):
    if not items:
        return []

    return items


def format_markdown_list(items):
    if not items:
        return "- None"

    return "\n".join(
        f"- {item}"
        for item in items
    )


def format_inline_list(
    items,
    default="None",
):
    if not items:
        return default

    return ", ".join(
        str(item)
        for item in items
    )


def safe_value(
    value,
    default=None,
):
    if (
        value is None
        or value == ""
    ):
        return default

    return value


def normalize_status(
    value,
    default="NOT_AVAILABLE",
):
    if (
        value is None
        or value == ""
    ):
        return default

    return str(
        value
    ).strip().upper()


def normalize_risk(value):
    normalized = normalize_status(
        value,
        "UNKNOWN",
    )

    return (
        normalized
        if normalized
        in RISK_ORDER
        else "UNKNOWN"
    )


def highest_risk(
    *risk_values,
):
    normalized = [
        normalize_risk(
            value
        )
        for value in risk_values
    ]

    return max(
        normalized,
        key=lambda value: (
            RISK_ORDER[
                value
            ]
        ),
        default="UNKNOWN",
    )


def is_failed_status(value):
    return (
        normalize_status(
            value
        )
        in FAILED_STATUSES
    )


def is_unavailable_status(value):
    return (
        normalize_status(
            value
        )
        in UNAVAILABLE_STATUSES
    )


def build_execution_status(
    execution_result,
):
    if execution_result.get(
        "status"
    ):
        return execution_result[
            "status"
        ]

    runtime_evidence = execution_result.get("runtime_evidence") or {}
    runtime_test_result = normalize_status(
        runtime_evidence.get("test_result"),
        "INCONCLUSIVE",
    )

    if execution_result.get(
        "skipped"
    ):
        return "SKIPPED"

    return (
        "PASSED"
        if execution_result.get(
            "success"
        )
        else "FAILED"
    )


def build_execution_summary(
    project_type,
    execution_result,
    source_review_data=None,
):
    command = safe_value(
        execution_result.get(
            "command"
        ),
        "Not available",
    )
    command_profile = safe_value(
        execution_result.get(
            "command_profile"
        ),
        "Not available",
    )
    execution_strategy = safe_value(
        execution_result.get(
            "execution_strategy"
        ),
        "Not available",
    )
    runtime_evidence = (
        execution_result.get(
            "runtime_evidence"
        )
        or {}
    )
    test_summary = (
        runtime_evidence.get(
            "test_summary"
        )
        or {}
    )

    if execution_result.get(
        "skipped"
    ):
        reason = safe_value(
            execution_result.get(
                "skip_reason"
            ),
            "Test execution was not required.",
        )
        source_status = safe_value(
            source_review_data.get(
                "status"
            )
            if source_review_data
            else None,
            "NOT_RUN",
        )

        return (
            f"The {project_type} was scanned successfully. Test execution was skipped. "
            f"Reason: {reason} The built-in command `{command}` was not run. "
            f"The built-in execution profile `{command_profile}` was selected but not executed. "
            f"Agent 3 source review status was `{source_status}`."
        )

    execution_status = (
        runtime_evidence.get(
            "execution_status"
        )
        or build_execution_status(
            execution_result
        )
    )
    test_result = (
        runtime_evidence.get(
            "test_result"
        )
        or (
            "PASS"
            if execution_result.get(
                "success"
            )
            else "FAIL"
        )
    )

    return (
        f"The {project_type} was executed using the built-in profile `{command_profile}` with the "
        f"`{execution_strategy}` strategy. Execution status was `{execution_status}` and the test result was "
        f"`{test_result}`. Structured evidence reported {test_summary.get('total', 0)} total tests, "
        f"{test_summary.get('passed', 0)} passed, {test_summary.get('failed', 0)} failed, "
        f"{test_summary.get('errors', 0)} errors, and {test_summary.get('skipped', 0)} skipped. "
        f"The command `{command}` ended with exit code {execution_result.get('exit_code')}."
    )


def build_static_mapping_json(
    static_map,
):
    mapping = {
        "build_file": static_map.get(
            "build_file"
        ),
        "main_source_dir": static_map.get(
            "main_source_dir"
        ),
        "test_source_dir": static_map.get(
            "test_source_dir"
        ),
        "test_source_dirs": format_list(
            static_map.get(
                "test_source_dirs",
                [],
            )
        ),
        "main_file": static_map.get(
            "main_file"
        ),
        "suggested_command": static_map.get(
            "suggested_command"
        ),
        "execution_profile": static_map.get(
            "execution_profile"
        ),
        "execution_policy": static_map.get(
            "execution_policy"
        ),
        "execution_strategy": static_map.get(
            "execution_strategy"
        ),
        "has_tests": bool(
            static_map.get(
                "has_tests"
            )
        ),
        "test_files_count": int(
            static_map.get(
                "test_files_count",
                0,
            )
        ),
        "test_files": format_list(
            static_map.get(
                "test_files",
                [],
            )
        ),
        "test_framework": static_map.get(
            "test_framework"
        ),
        "test_detection_source": static_map.get(
            "test_detection_source"
        ),
        "test_file_patterns": format_list(
            static_map.get(
                "test_file_patterns",
                [],
            )
        ),
        "configured_test_paths": format_list(
            static_map.get(
                "configured_test_paths",
                [],
            )
        ),
        "test_detection_warning": static_map.get(
            "test_detection_warning"
        ),
    }

    if static_map.get(
        "has_maven_wrapper"
    ) is not None:
        mapping[
            "has_maven_wrapper"
        ] = bool(
            static_map.get(
                "has_maven_wrapper"
            )
        )

    if static_map.get(
        "wrapper_command"
    ):
        mapping[
            "wrapper_command"
        ] = static_map.get(
            "wrapper_command"
        )

    if static_map.get(
        "wrapper_recommendation"
    ):
        mapping[
            "wrapper_recommendation"
        ] = static_map.get(
            "wrapper_recommendation"
        )

    return mapping


def build_static_mapping_markdown(
    static_map,
):
    lines = [
        f"- Build File: {safe_value(static_map.get('build_file'), 'Not available')}",
        f"- Main Source Dir: {safe_value(static_map.get('main_source_dir'), 'Not available')}",
        f"- Test Source Dir: {safe_value(static_map.get('test_source_dir'), 'Not available')}",
        f"- Main File: {safe_value(static_map.get('main_file'), 'Not available')}",
        f"- Suggested Command: {safe_value(static_map.get('suggested_command'), 'Not available')}",
        f"- Execution Profile: {safe_value(static_map.get('execution_profile'), 'Not available')}",
        f"- Execution Policy: {safe_value(static_map.get('execution_policy'), 'Not available')}",
        f"- Execution Strategy: {safe_value(static_map.get('execution_strategy'), 'Not available')}",
        f"- Tests Detected: {'Yes' if static_map.get('has_tests') else 'No'}",
        f"- Test Files Count: {static_map.get('test_files_count', 0)}",
        f"- Test Framework: {safe_value(static_map.get('test_framework'), 'Not available')}",
        f"- Test Detection Source: {safe_value(static_map.get('test_detection_source'), 'Not available')}",
        f"- Test File Patterns: {format_inline_list(static_map.get('test_file_patterns', []))}",
        f"- Configured Test Paths: {format_inline_list(static_map.get('configured_test_paths', []))}",
    ]

    if static_map.get(
        "test_detection_warning"
    ):
        lines.append(
            f"- Test Detection Warning: {static_map.get('test_detection_warning')}"
        )

    if static_map.get(
        "has_maven_wrapper"
    ) is not None:
        lines.append(
            f"- Maven Wrapper: {static_map.get('has_maven_wrapper')}"
        )

    if static_map.get(
        "wrapper_command"
    ):
        lines.append(
            f"- Wrapper Command: {safe_value(static_map.get('wrapper_command'), 'Not available')}"
        )

    if static_map.get(
        "wrapper_recommendation"
    ):
        lines.append(
            f"- Wrapper Recommendation: {static_map.get('wrapper_recommendation')}"
        )

    return "\n".join(
        lines
    )


def build_source_discovery_json(
    source_review,
):
    return {
        "supported": bool(
            source_review.get(
                "supported"
            )
        ),
        "source_files_count": int(
            source_review.get(
                "source_files_count",
                0,
            )
        ),
        "source_files": format_list(
            source_review.get(
                "source_files",
                [],
            )
        ),
        "file_extensions": format_list(
            source_review.get(
                "file_extensions",
                [],
            )
        ),
        "excluded_test_files_count": int(
            source_review.get(
                "excluded_test_files_count",
                0,
            )
        ),
        "excluded_sensitive_files_count": int(
            source_review.get(
                "excluded_sensitive_files_count",
                0,
            )
        ),
        "unreadable_files_count": int(
            source_review.get(
                "unreadable_files_count",
                0,
            )
        ),
        "warning": source_review.get(
            "warning"
        ),
    }


def build_source_review_json(
    source_review_data,
):
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
        "status": source_review_data.get(
            "status"
        ),
        "agent": source_review_data.get(
            "agent"
        ),
        "mode": source_review_data.get(
            "mode"
        ),
        "summary": source_review_data.get(
            "summary"
        ),
        "risk_level": source_review_data.get(
            "risk_level"
        ),
        "release_recommendation": source_review_data.get(
            "release_recommendation"
        ),
        "reviewed_files_count": int(
            source_review_data.get(
                "reviewed_files_count",
                0,
            )
        ),
        "findings_count": int(
            source_review_data.get(
                "findings_count",
                0,
            )
        ),
        "severity_summary": source_review_data.get(
            "severity_summary",
            {},
        ),
        "category_summary": source_review_data.get(
            "category_summary",
            {},
        ),
        "findings": format_list(
            source_review_data.get(
                "findings",
                [],
            )
        ),
        "warnings": format_list(
            source_review_data.get(
                "warnings",
                [],
            )
        ),
        "limitations": format_list(
            source_review_data.get(
                "limitations",
                [],
            )
        ),
        "verification": source_review_data.get(
            "verification"
        ),
        "llm_error": source_review_data.get(
            "llm_error"
        ),
        "coverage": source_review_data.get(
            "coverage",
            {},
        ),
    }


def build_log_agent_json(
    agent_data,
):
    if not agent_data:
        return {
            "agent_id": "runtime-quality-analyst",
            "display_name": "Runtime Quality Intelligence Analyst",
            "agent_version": "2.0",
            "agent": "log-agent",
            "mode": None,
            "model": None,
            "execution_status": "NOT_RUN",
            "test_result": "NOT_RUN",
            "release_gate": "NOT_EVALUATED",
            "runtime_risk_level": "UNKNOWN",
            "failure_origin": "NOT_ESTABLISHED",
            "diagnosis_confidence": "LOW",
            "final_status": None,
            "summary": None,
            "run_summary": {},
            "root_cause_groups": [],
            "primary_root_cause": None,
            "root_cause": None,
            "runtime_impact": None,
            "required_actions": [],
            "recommendation": None,
            "verification_steps": [],
            "issues": [],
            "warnings": [],
            "limitations": [],
            "evidence_quality": "NONE",
            "llm_error": None,
        }

    groups = format_list(
        agent_data.get(
            "root_cause_groups",
            [],
        )
    )
    primary_root_cause = safe_value(
        agent_data.get(
            "primary_root_cause"
        ),
        agent_data.get(
            "root_cause"
        ),
    )

    if (
        not primary_root_cause
        and groups
        and isinstance(
            groups[0],
            dict,
        )
    ):
        primary_root_cause = (
            groups[0].get(
                "root_cause"
            )
        )

    return {
        "agent_id": safe_value(
            agent_data.get(
                "agent_id"
            ),
            "runtime-quality-analyst",
        ),
        "display_name": safe_value(
            agent_data.get(
                "display_name"
            ),
            "Runtime Quality Intelligence Analyst",
        ),
        "agent_version": safe_value(
            agent_data.get(
                "agent_version"
            ),
            "2.0",
        ),
        "agent": safe_value(
            agent_data.get(
                "agent"
            ),
            "log-agent",
        ),
        "mode": safe_value(
            agent_data.get(
                "mode"
            )
        ),
        "model": safe_value(
            agent_data.get(
                "model"
            )
        ),
        "execution_status": safe_value(
            agent_data.get(
                "execution_status"
            ),
            "UNKNOWN",
        ),
        "test_result": safe_value(
            agent_data.get(
                "test_result"
            ),
            "INCONCLUSIVE",
        ),
        "release_gate": safe_value(
            agent_data.get(
                "release_gate"
            ),
            "NOT_EVALUATED",
        ),
        "runtime_risk_level": safe_value(
            agent_data.get(
                "runtime_risk_level"
            ),
            "UNKNOWN",
        ),
        "failure_origin": safe_value(
            agent_data.get(
                "failure_origin"
            ),
            "NOT_ESTABLISHED",
        ),
        "diagnosis_confidence": safe_value(
            agent_data.get(
                "diagnosis_confidence"
            ),
            "LOW",
        ),
        "final_status": safe_value(
            agent_data.get(
                "final_status"
            )
        ),
        "summary": safe_value(
            agent_data.get(
                "summary"
            )
        ),
        "run_summary": (
            agent_data.get(
                "run_summary"
            )
            if isinstance(
                agent_data.get(
                    "run_summary"
                ),
                dict,
            )
            else {}
        ),
        "root_cause_groups": groups,
        "primary_root_cause": (
            primary_root_cause
        ),
        "root_cause": (
            primary_root_cause
        ),
        "runtime_impact": safe_value(
            agent_data.get(
                "runtime_impact"
            )
        ),
        "required_actions": format_list(
            agent_data.get(
                "required_actions",
                [],
            )
        ),
        "recommendation": safe_value(
            agent_data.get(
                "recommendation"
            )
        ),
        "verification_steps": format_list(
            agent_data.get(
                "verification_steps",
                [],
            )
        ),
        "issues": format_list(
            agent_data.get(
                "issues",
                [],
            )
        ),
        "warnings": format_list(
            agent_data.get(
                "warnings",
                [],
            )
        ),
        "limitations": format_list(
            agent_data.get(
                "limitations",
                [],
            )
        ),
        "evidence_quality": safe_value(
            agent_data.get(
                "evidence_quality"
            ),
            "NONE",
        ),
        "llm_error": safe_value(
            agent_data.get(
                "llm_error"
            )
        ),
    }


def build_repair_agent_json(repair_data):
    repair_data = repair_data or {}
    contracts = []

    for item in format_list(repair_data.get("stitch_repair_contracts", [])):
        if not isinstance(item, dict):
            continue
        contracts.append(
            {
                "contract_id": safe_value(item.get("contract_id")),
                "finding_refs": format_list(item.get("finding_refs", [])),
                "title": safe_value(item.get("title")),
                "priority": safe_value(item.get("priority"), "P3"),
                "priority_reason": safe_value(item.get("priority_reason")),
                "repair_objective": safe_value(item.get("repair_objective")),
                "repair_strategy": safe_value(item.get("repair_strategy")),
                "change_boundary": safe_value(item.get("change_boundary")),
                "protected_behavior": safe_value(item.get("protected_behavior")),
                "side_effect_risk": safe_value(item.get("side_effect_risk"), "UNKNOWN"),
                "verification": safe_value(item.get("verification")),
                "done_condition": safe_value(item.get("done_condition")),
                "status": safe_value(item.get("status"), "PENDING_VERIFICATION"),
            }
        )

    repair_risk = safe_value(
        repair_data.get("repair_risk_level") or repair_data.get("risk_level"),
        "UNKNOWN",
    )

    return {
        "agent_id": safe_value(repair_data.get("agent_id"), "defect-resolution-analyst"),
        "display_name": safe_value(
            repair_data.get("display_name"),
            "Defect Resolution Intelligence Analyst",
        ),
        "agent_version": safe_value(repair_data.get("agent_version"), "2.0"),
        "agent": safe_value(repair_data.get("agent"), "repair-agent"),
        "mode": safe_value(repair_data.get("mode")),
        "model": safe_value(repair_data.get("model")),
        "status": safe_value(repair_data.get("status")),
        "overall_priority": safe_value(repair_data.get("overall_priority"), "NONE"),
        "confidence": safe_value(repair_data.get("confidence"), "LOW"),
        "repair_risk_level": repair_risk,
        "risk_level": repair_risk,
        "auto_apply": bool(repair_data.get("auto_apply", False)),
        "summary": safe_value(repair_data.get("summary")),
        "stitch_repair_contracts": contracts,
        "current_knowledge_required": bool(
            repair_data.get("current_knowledge_required", False)
        ),
        "current_knowledge_reason": safe_value(
            repair_data.get("current_knowledge_reason")
        ),
        "suggestions": format_list(repair_data.get("suggestions", [])),
        "next_action": safe_value(repair_data.get("next_action")),
        "warnings": format_list(repair_data.get("warnings", [])),
        "limitations": format_list(repair_data.get("limitations", [])),
        "llm_metrics": (
            repair_data.get("llm_metrics")
            if isinstance(repair_data.get("llm_metrics"), dict)
            else None
        ),
        "llm_error": safe_value(repair_data.get("llm_error")),
    }


def build_code_agent_json(
    code_data,
):
    return {
        "agent": safe_value(
            code_data.get(
                "agent"
            )
            if code_data
            else None
        ),
        "mode": safe_value(
            code_data.get(
                "mode"
            )
            if code_data
            else None
        ),
        "status": safe_value(
            code_data.get(
                "status"
            )
            if code_data
            else None
        ),
        "risk_level": safe_value(
            code_data.get(
                "risk_level"
            )
            if code_data
            else None
        ),
        "auto_apply": safe_value(
            code_data.get(
                "auto_apply"
            )
            if code_data
            else None
        ),
        "summary": safe_value(
            code_data.get(
                "summary"
            )
            if code_data
            else None
        ),
        "suggested_patch": safe_value(
            code_data.get(
                "suggested_patch"
            )
            if code_data
            else None
        ),
        "verification": safe_value(
            code_data.get(
                "verification"
            )
            if code_data
            else None
        ),
        "warnings": format_list(
            code_data.get(
                "warnings"
            )
            if code_data
            else []
        ),
        "llm_error": safe_value(
            code_data.get(
                "llm_error"
            )
            if code_data
            else None
        ),
    }


def build_agent_workflow_status(
    execution_result,
    source_review_data=None,
    agent_data=None,
    repair_data=None,
    code_data=None,
    workflow_context=None,
):
    workflow_context = (
        workflow_context
        or {}
    )
    tests_executed = bool(
        execution_result.get(
            "executed"
        )
    )

    if workflow_context.get(
        "analyze_requested"
    ):
        log_status = normalize_status(
            agent_data.get(
                "final_status"
            )
            if agent_data
            else None,
            (
                "UNAVAILABLE"
                if tests_executed
                else "NOT_RUN"
            ),
        )
    else:
        log_status = "NOT_REQUESTED"

    if workflow_context.get(
        "repair_requested"
    ):
        repair_status = normalize_status(
            repair_data.get(
                "status"
            )
            if repair_data
            else None,
            (
                "UNAVAILABLE"
                if tests_executed
                else "NOT_RUN"
            ),
        )
    else:
        repair_status = "NOT_REQUESTED"

    if workflow_context.get(
        "code_fix_requested"
    ):
        code_status = normalize_status(
            code_data.get(
                "status"
            )
            if code_data
            else None,
            (
                "UNAVAILABLE"
                if tests_executed
                else "NOT_RUN"
            ),
        )
    else:
        code_status = "NOT_REQUESTED"

    return {
        "source_review": normalize_status(
            source_review_data.get(
                "status"
            )
            if source_review_data
            else None,
            "NOT_RUN",
        ),
        "test_execution": normalize_status(
            build_execution_status(
                execution_result
            )
        ),
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
    workflow_context = (
        workflow_context
        or {}
    )
    workflow_status = (
        build_agent_workflow_status(
            execution_result,
            source_review_data,
            agent_data,
            repair_data,
            code_data,
            workflow_context,
        )
    )
    source_status = workflow_status[
        "source_review"
    ]
    source_review_data = (
        source_review_data
        or {}
    )
    source_coverage = source_review_data.get(
        "coverage",
        {},
    )
    discovered_source_files = int(
        source_coverage.get(
            "discovered_files_count",
            0,
        )
    )
    source_available = (
        source_status
        in SOURCE_COMPLETE_STATUSES
    )
    no_source_files = (
        source_status
        == "NO_SOURCE_FILES"
    )
    source_unavailable = (
        source_status
        == "UNAVAILABLE"
        and discovered_source_files
        > 0
    )
    tests_executed = bool(
        execution_result.get(
            "executed"
        )
    )
    tests_skipped = bool(
        execution_result.get(
            "skipped"
        )
    )
    runtime_evidence = (
        execution_result.get(
            "runtime_evidence"
        )
        or {}
    )
    execution_status = normalize_status(
        runtime_evidence.get(
            "execution_status"
        ),
        build_execution_status(
            execution_result
        ),
    )
    test_result = normalize_status(
        runtime_evidence.get(
            "test_result"
        ),
        (
            "PASS"
            if execution_result.get(
                "success"
            )
            else "FAIL"
        ),
    )
    failure_type = normalize_status(
        execution_result.get(
            "failure_type"
        ),
        "NONE",
    )

    non_code_failures = {
        "MAVEN_NOT_AVAILABLE",
        "MAVEN_WRAPPER_NOT_AVAILABLE",
        "MAVEN_WRAPPER_NOT_EXECUTABLE",
        "PYTHON_NOT_AVAILABLE",
        "PYTEST_NOT_AVAILABLE",
        "PYTHON_TESTS_NOT_FOUND",
        "INVALID_PROJECT_PATH",
        "COMMAND_PROFILE_NOT_ALLOWED",
        "COMMAND_TIMEOUT",
        "EXECUTION_OS_ERROR",
        "EXECUTION_ERROR",
        "MAVEN_PLUGIN_RESOLUTION_FAILURE",
        "MAVEN_DEPENDENCY_RESOLUTION_FAILURE",
        "MAVEN_TEST_COMPILATION_FAILURE",
        "MAVEN_COMPILATION_FAILURE",
        "MAVEN_TEST_EXECUTION_BLOCKED",
    }

    execution_incomplete = (
        tests_skipped
        or test_result
        in {
            "NOT_RUN",
            "INCONCLUSIVE",
        }
        or execution_status
        in {
            "FAILED_TO_START",
            "TIMED_OUT",
            "SKIPPED",
            "UNKNOWN",
        }
        or failure_type
        in non_code_failures
    )
    execution_failed = (
        test_result
        == "FAIL"
    )
    execution_passed = (
        test_result
        == "PASS"
    )

    log_status = workflow_status[
        "log_analysis"
    ]
    repair_status = workflow_status[
        "repair_guidance"
    ]
    code_status = workflow_status[
        "code_repair_guidance"
    ]

    requested_evidence_agent_unavailable = (
        workflow_context.get("analyze_requested")
        and is_unavailable_status(log_status)
    )


    agent_release_gate = normalize_status(
        agent_data.get(
            "release_gate"
        )
        if agent_data
        else None,
        "NOT_EVALUATED",
    )
    agent_runtime_risk = normalize_status(
        agent_data.get(
            "runtime_risk_level"
        )
        if agent_data
        else None,
        "UNKNOWN",
    )
    agent_failure_origin = normalize_status(
        agent_data.get(
            "failure_origin"
        )
        if agent_data
        else None,
        "NOT_ESTABLISHED",
    )

    source_risk = normalize_risk(
        source_review_data.get(
            "risk_level"
        )
    )


    execution_risk = (
        "HIGH"
        if execution_failed
        else (
            "MEDIUM"
            if execution_incomplete
            else "NONE"
        )
    )
    release_gate_risk = (
        "HIGH"
        if agent_release_gate
        == "BLOCK_RELEASE"
        else (
            "MEDIUM"
            if agent_release_gate
            == "REVIEW_REQUIRED"
            else "NONE"
        )
    )
    log_risk = highest_risk(
        agent_runtime_risk,
        release_gate_risk,
    )

    combined_risk = highest_risk(
        source_risk,
        execution_risk,
        log_risk,
    )


    reasons = []

    if source_available:
        reasons.append(
            f"Agent 3 source review completed with risk level {source_risk}."
        )
    elif no_source_files:
        reasons.append(
            "No eligible application source files were available for Agent 3 review."
        )
    elif source_unavailable:
        reasons.append(
            "Agent 3 source review was unavailable for discovered application source files."
        )
    else:
        reasons.append(
            f"Agent 3 source review status was {source_status}."
        )

    if tests_skipped:
        reasons.append(
            "Test execution was skipped because no compatible tests were detected."
        )
    elif execution_passed:
        reasons.append(
            "Structured runtime evidence confirmed that the validated test workflow passed."
        )
    elif execution_failed:
        reasons.append(
            f"Structured runtime evidence confirmed a failing test result with exit code "
            f"{execution_result.get('exit_code')}."
        )
    elif execution_incomplete:
        reasons.append(
            f"Runtime QA evidence is incomplete because execution status was "
            f"{execution_status} and test result was {test_result}."
        )

    if workflow_context.get(
        "analyze_requested"
    ):
        reasons.append(
            f"Runtime Quality Intelligence Analyst release gate was {agent_release_gate} "
            f"with workflow status {log_status}."
        )

    if workflow_context.get(
        "repair_requested"
    ):
        reasons.append(
            f"Defect Resolution Intelligence Analyst status was {repair_status}."
        )

    if workflow_context.get(
        "code_fix_requested"
    ):
        reasons.append(
            f"Agent 3 code-repair guidance status was {code_status}."
        )

    source_release = normalize_status(
        source_review_data.get(
            "release_recommendation"
        ),
        "UNKNOWN",
    )

    if (
        execution_failed
        or agent_release_gate
        == "BLOCK_RELEASE"
    ):
        status = "BLOCK_RELEASE"
        release_recommendation = (
            "BLOCK_RELEASE"
        )
        ci_exit_code = 1
    elif (
        source_unavailable
        or requested_evidence_agent_unavailable
        or execution_incomplete
    ):
        status = "QA_INCOMPLETE"
        release_recommendation = (
            "QA_INCOMPLETE"
        )
        ci_exit_code = 1
    elif (
        source_release
        == "QA_INCOMPLETE"
    ):
        status = "QA_INCOMPLETE"
        release_recommendation = (
            "QA_INCOMPLETE"
        )
        ci_exit_code = 1
    elif (
        source_release
        == "BLOCK_RELEASE"
        or RISK_ORDER[
            combined_risk
        ]
        >= RISK_ORDER[
            "HIGH"
        ]
    ):
        status = "BLOCK_RELEASE"
        release_recommendation = (
            "BLOCK_RELEASE"
        )
        ci_exit_code = 1
    elif (
        agent_release_gate
        == "REVIEW_REQUIRED"
        or RISK_ORDER[
            combined_risk
        ]
        >= RISK_ORDER[
            "MEDIUM"
        ]
    ):
        status = "REVIEW_REQUIRED"
        release_recommendation = (
            "REVIEW_REQUIRED"
        )
        ci_exit_code = 0
    elif (
        agent_release_gate
        == "ALLOW_WITH_WARNINGS"
        or RISK_ORDER[
            combined_risk
        ]
        >= RISK_ORDER[
            "LOW"
        ]
    ):
        status = "PASS_WITH_WARNINGS"
        release_recommendation = (
            "ALLOW_WITH_WARNINGS"
        )
        ci_exit_code = 0
    elif (
        execution_passed
        and no_source_files
    ):
        status = (
            "TESTS_PASSED_WITHOUT_SOURCE_REVIEW"
        )
        release_recommendation = (
            "REVIEW_REQUIRED"
        )
        ci_exit_code = 0
    else:
        status = "PASS"
        release_recommendation = (
            "READY_FOR_RELEASE"
        )
        ci_exit_code = 0

    if (
        source_status
        == "PARTIAL"
        or requested_evidence_agent_unavailable
    ):
        completeness = "PARTIAL"
    elif (
        execution_incomplete
        and source_available
    ):
        completeness = "SOURCE_ONLY"
    elif (
        tests_executed
        and no_source_files
    ):
        completeness = "TEST_ONLY"
    elif (
        tests_executed
        and source_available
    ):
        completeness = "COMPLETE"
    else:
        completeness = "INCOMPLETE"

    return {
        "status": status,
        "risk_level": combined_risk,
        "release_recommendation": (
            release_recommendation
        ),
        "completeness": completeness,
        "ci_exit_code": ci_exit_code,
        "reasons": reasons,
        "workflow_status": workflow_status,
        "runtime_gate": {
            "execution_status": (
                execution_status
            ),
            "test_result": test_result,
            "agent_release_gate": (
                agent_release_gate
            ),
            "runtime_risk_level": (
                agent_runtime_risk
            ),
            "failure_origin": (
                agent_failure_origin
            ),
            "failure_type": (
                failure_type
            ),
        },
    }


def format_summary_mapping(
    mapping,
):
    if not mapping:
        return "None"

    return ", ".join(
        f"{key}: {value}"
        for key, value
        in mapping.items()
    )


def finding_line_sort_value(
    value,
):
    if (
        value is None
        or value == ""
    ):
        return 0

    try:
        return int(
            str(
                value
            )
            .split("-")[0]
            .split(":")[0]
            .strip()
        )
    except (
        TypeError,
        ValueError,
    ):
        return 0


def normalize_findings(
    findings,
):
    normalized_findings = []

    for finding in (
        findings or []
    ):
        normalized_finding = dict(
            finding
        )
        normalized_finding[
            "severity"
        ] = normalize_risk(
            finding.get(
                "severity"
            )
        )
        normalized_findings.append(
            normalized_finding
        )

    return sorted(
        normalized_findings,
        key=lambda finding: (
            -RISK_ORDER.get(
                finding.get(
                    "severity",
                    "UNKNOWN",
                ),
                -1,
            ),
            str(
                finding.get(
                    "file_path"
                )
                or ""
            ),
            finding_line_sort_value(
                finding.get(
                    "line"
                )
            ),
            str(
                finding.get(
                    "title"
                )
                or ""
            ),
        ),
    )


def build_findings_summary(
    findings,
):
    summary = {
        severity.lower(): 0
        for severity
        in SEVERITY_DISPLAY_ORDER
    }

    for finding in normalize_findings(
        findings
    ):
        severity = finding.get(
            "severity",
            "UNKNOWN",
        ).lower()
        summary[
            severity
        ] = (
            summary.get(
                severity,
                0,
            )
            + 1
        )

    summary[
        "total"
    ] = sum(
        count
        for severity, count
        in summary.items()
        if severity
        != "total"
    )

    return summary


def format_markdown_table(
    headers,
    rows,
):
    if not rows:
        return "No data available."

    header_row = (
        "| "
        + " | ".join(
            str(header)
            for header in headers
        )
        + " |"
    )
    separator_row = (
        "| "
        + " | ".join(
            "---"
            for _ in headers
        )
        + " |"
    )
    data_rows = [
        "| "
        + " | ".join(
            str(
                value
            )
            .replace(
                "\n",
                " ",
            )
            .replace(
                "|",
                "\\|",
            )
            for value in row
        )
        + " |"
        for row in rows
    ]

    return "\n".join(
        [
            header_row,
            separator_row,
            *data_rows,
        ]
    )


def format_source_findings(
    findings,
):
    normalized_findings = normalize_findings(
        findings
    )

    if not normalized_findings:
        return (
            "No source-code findings were reported."
        )

    sections = []

    for severity in SEVERITY_DISPLAY_ORDER:
        severity_findings = [
            finding
            for finding
            in normalized_findings
            if finding.get(
                "severity"
            )
            == severity
        ]

        if not severity_findings:
            continue

        sections.append(
            f"#### {severity} Findings"
        )

        for finding in severity_findings:
            title = safe_value(
                finding.get(
                    "title"
                ),
                "Source-code finding",
            )
            file_path = safe_value(
                finding.get(
                    "file_path"
                ),
                "Project-level",
            )
            line = finding.get(
                "line"
            )
            location = (
                f"{file_path}:{line}"
                if line
                else file_path
            )

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

    return "\n\n".join(
        sections
    )


def build_scope_summary(
    static_map,
    source_discovery,
    source_review_json,
    execution_result,
    qa_decision,
):
    workflow_status = qa_decision.get(
        "workflow_status",
        {},
    )

    runtime_evidence = execution_result.get("runtime_evidence") or {}
    runtime_test_result = normalize_status(
        runtime_evidence.get("test_result"),
        "INCONCLUSIVE",
    )

    return {
        "source_review_supported": bool(
            source_discovery.get(
                "supported"
            )
        ),
        "source_files_discovered": int(
            source_discovery.get(
                "source_files_count",
                0,
            )
        ),
        "source_files_reviewed": int(
            source_review_json.get(
                "reviewed_files_count",
                0,
            )
        ),
        "source_review_status": normalize_status(
            source_review_json.get(
                "status"
            ),
            "NOT_RUN",
        ),
        "tests_detected": bool(
            static_map.get(
                "has_tests"
            )
        ),
        "test_files_detected": int(
            static_map.get(
                "test_files_count",
                0,
            )
        ),
        "test_framework": safe_value(
            static_map.get(
                "test_framework"
            )
        ),
        "test_execution_status": normalize_status(
            build_execution_status(
                execution_result
            ),
            "NOT_RUN",
        ),
        "test_execution_performed": (
            bool(execution_result.get("executed"))
            and runtime_test_result != "NOT_RUN"
        ),
        "evidence_completeness": qa_decision.get(
            "completeness"
        ),
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
    source_status = normalize_status(
        source_review_json.get(
            "status"
        ),
        "NOT_RUN",
    )
    workflow_status = qa_decision.get(
        "workflow_status",
        {},
    )
    runtime_evidence = execution_result.get("runtime_evidence") or {}
    runtime_test_result = normalize_status(
        runtime_evidence.get("test_result"),
        "INCONCLUSIVE",
    )

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

    if execution_result.get(
        "skipped"
    ):
        limitations.append(
            safe_value(
                execution_result.get(
                    "skip_reason"
                ),
                "Automated test execution was skipped.",
            )
        )
    elif not execution_result.get(
        "executed"
    ):
        limitations.append(
            "Automated test execution was not performed."
        )
    elif runtime_test_result == "NOT_RUN":
        limitations.append(
            "The build or test workflow stopped before an executed automated-test result was established."
        )

    if (
        not static_map.get(
            "has_tests"
        )
        and not execution_result.get(
            "skipped"
        )
    ):
        limitations.append(
            "No compatible automated tests were detected, so runtime behavior was not verified by the built-in test runner."
        )

    status_labels = {
        "log_analysis": (
            "Runtime Quality Intelligence analysis"
        ),
        "repair_guidance": (
            "Defect Resolution Intelligence Analyst"
        ),
        "code_repair_guidance": (
            "Agent 3 runtime code-repair guidance"
        ),
    }

    for key, label in status_labels.items():
        status = normalize_status(
            workflow_status.get(
                key
            ),
            "NOT_REQUESTED",
        )

        if status == "UNAVAILABLE":
            limitations.append(
                f"{label} was requested but unavailable."
            )
        elif status == "NOT_RUN":
            limitations.append(
                f"{label} was requested but could not run in this workflow."
            )

    for item in source_review_json.get(
        "limitations",
        [],
    ):
        if (
            item
            and item
            not in limitations
        ):
            limitations.append(
                str(
                    item
                )
            )

    for item in log_agent_json.get(
        "limitations",
        [],
    ):
        if (
            item
            and item
            not in limitations
        ):
            limitations.append(
                str(
                    item
                )
            )

    for item in repair_agent_json.get(
        "limitations",
        [],
    ):
        if item and item not in limitations:
            limitations.append(str(item))

    llm_errors = [
        log_agent_json.get(
            "llm_error"
        ),
        repair_agent_json.get(
            "llm_error"
        ),
        code_agent_json.get(
            "llm_error"
        ),
        source_review_json.get(
            "llm_error"
        ),
    ]

    if any(
        llm_errors
    ):
        limitations.append(
            "One or more AI-agent responses used fallback or incomplete output because an LLM request failed."
        )

    return list(
        dict.fromkeys(
            limitations
        )
    )


def build_next_actions(
    qa_decision,
    static_map,
    source_review_json,
    execution_result,
    log_agent_json=None,
    repair_agent_json=None,
):
    actions = []
    log_agent_json = log_agent_json or {}
    repair_agent_json = repair_agent_json or {}
    status = normalize_status(
        qa_decision.get("status"),
        "QA_INCOMPLETE",
    )
    source_status = normalize_status(
        source_review_json.get("status"),
        "NOT_RUN",
    )
    runtime_evidence = execution_result.get("runtime_evidence") or {}
    test_result = normalize_status(
        runtime_evidence.get("test_result"),
        "INCONCLUSIVE",
    )

    contracts = repair_agent_json.get("stitch_repair_contracts", [])
    covered_findings = set()

    for contract in contracts:
        if not isinstance(contract, dict):
            continue
        covered_findings.update(
            str(ref)
            for ref in contract.get("finding_refs", [])
            if ref
        )
        strategy = safe_value(contract.get("repair_strategy"))
        if not strategy:
            continue
        actions.append(
            {
                "priority": safe_value(contract.get("priority"), "P3"),
                "action": str(strategy),
                "source": "defect-resolution-analyst",
                "contract_id": safe_value(contract.get("contract_id")),
                "finding_refs": format_list(contract.get("finding_refs", [])),
                "done_condition": safe_value(contract.get("done_condition")),
            }
        )

    if repair_agent_json.get("current_knowledge_required"):
        actions.append(
            {
                "priority": safe_value(
                    repair_agent_json.get("overall_priority"),
                    "P2",
                ),
                "action": (
                    "Verify the required current external documentation before implementing the affected repair plan. "
                    + str(
                        safe_value(
                            repair_agent_json.get("current_knowledge_reason"),
                            "The repair depends on current external behavior or compatibility information.",
                        )
                    )
                ),
                "source": "defect-resolution-analyst",
            }
        )

    if test_result == "FAIL" and not contracts:
        actions.append(
            {
                "priority": "P1",
                "action": (
                    "Resolve the confirmed structured test failures and rerun Stitch QA before release."
                ),
            }
        )

    if not contracts:
        for action_text in log_agent_json.get("required_actions", []):
            action = {
                "priority": (
                    "P1"
                    if status in {"BLOCK_RELEASE", "FAIL"}
                    else "P2"
                ),
                "action": str(action_text),
                "source": "runtime-quality-analyst",
            }
            if action not in actions:
                actions.append(action)

    if status in {"BLOCK_RELEASE", "FAIL"}:
        action = {
            "priority": "P1",
            "action": (
                "Keep the release blocked until all confirmed release-blocking conditions are resolved."
            ),
        }
        if action not in actions:
            actions.append(action)

    if source_status == "UNAVAILABLE":
        actions.append(
            {
                "priority": "P1",
                "action": (
                    "Restore Agent 3 availability and rerun the source-code review to complete QA evidence."
                ),
            }
        )

    if not static_map.get("has_tests"):
        actions.append(
            {
                "priority": "P2",
                "action": (
                    "Add compatible automated tests for critical behavior and rerun the validated test workflow."
                ),
            }
        )

    for finding in normalize_findings(source_review_json.get("findings", [])):
        finding_id = safe_value(finding.get("id"))
        if finding_id and str(finding_id) in covered_findings:
            continue

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
            "finding_id": finding_id,
            "severity": severity,
        }
        if action not in actions:
            actions.append(action)

    if not actions:
        actions.append(
            {
                "priority": "P3",
                "action": (
                    "Retain the available QA evidence and continue the normal release workflow."
                ),
            }
        )

    priority_order = {"P1": 0, "P2": 1, "P3": 2}
    return sorted(
        actions,
        key=lambda item: priority_order.get(
            str(item.get("priority") or "P3").upper(),
            3,
        ),
    )


def format_next_actions(
    actions,
):
    if not actions:
        return "- None"

    lines = []

    for item in actions:
        priority = safe_value(
            item.get(
                "priority"
            ),
            "P3",
        )
        action = safe_value(
            item.get(
                "action"
            ),
            "No action supplied.",
        )
        source = item.get(
            "source"
        )
        finding_id = item.get(
            "finding_id"
        )

        context = []

        if source:
            context.append(
                f"Source: {source}"
            )

        if finding_id:
            context.append(
                f"Finding: {finding_id}"
            )

        suffix = (
            f" ({'; '.join(context)})"
            if context
            else ""
        )

        lines.append(
            f"- **{priority}** {action}{suffix}"
        )

    return "\n".join(
        lines
    )


def build_source_review_markdown(
    source_review_json,
):
    findings_text = format_source_findings(
        source_review_json.get(
            "findings",
            [],
        )
    )
    warnings_text = format_markdown_list(
        source_review_json.get(
            "warnings",
            [],
        )
    )
    limitations_text = format_markdown_list(
        source_review_json.get(
            "limitations",
            [],
        )
    )

    return (
        "## Source-Code QA Review\n\n"
        f"- Status: **{safe_value(source_review_json.get('status'), 'NOT_RUN')}**\n"
        f"- Agent: {safe_value(source_review_json.get('agent'), 'Not available')}\n"
        f"- Mode: {safe_value(source_review_json.get('mode'), 'Not available')}\n"
        f"- Risk Level: **{safe_value(source_review_json.get('risk_level'), 'UNKNOWN')}**\n"
        f"- Release Recommendation: **{safe_value(source_review_json.get('release_recommendation'), 'QA_INCOMPLETE')}**\n"
        f"- Reviewed Files: {source_review_json.get('reviewed_files_count', 0)}\n"
        f"- Findings: {source_review_json.get('findings_count', 0)}\n\n"
        "### Summary\n\n"
        f"{safe_value(source_review_json.get('summary'), 'No source-review summary available.')}\n\n"
        "### Prioritized Findings\n\n"
        f"{findings_text}\n\n"
        "### Source Review Warnings\n\n"
        f"{warnings_text}\n\n"
        "### Source Review Limitations\n\n"
        f"{limitations_text}\n\n"
        "### Verification Guidance\n\n"
        f"{safe_value(source_review_json.get('verification'), 'Rerun Stitch QA after addressing confirmed findings.')}\n\n"
    )


def build_qa_decision_markdown(
    qa_decision,
):
    workflow_status = qa_decision.get(
        "workflow_status",
        {},
    )
    runtime_gate = qa_decision.get(
        "runtime_gate",
        {},
    )

    decision_table = format_markdown_table(
        [
            "Decision Field",
            "Result",
        ],
        [
            [
                "Final QA Status",
                f"**{qa_decision.get('status')}**",
            ],
            [
                "Combined Risk Level",
                f"**{qa_decision.get('risk_level')}**",
            ],
            [
                "Release Recommendation",
                f"**{qa_decision.get('release_recommendation')}**",
            ],
            [
                "QA Evidence Completeness",
                f"**{qa_decision.get('completeness')}**",
            ],
            [
                "CI Exit Code",
                qa_decision.get(
                    "ci_exit_code"
                ),
            ],
        ],
    )

    runtime_table = format_markdown_table(
        [
            "Runtime Gate Field",
            "Result",
        ],
        [
            [
                "Execution Status",
                runtime_gate.get(
                    "execution_status"
                ),
            ],
            [
                "Test Result",
                runtime_gate.get(
                    "test_result"
                ),
            ],
            [
                "Agent Release Gate",
                runtime_gate.get(
                    "agent_release_gate"
                ),
            ],
            [
                "Runtime Risk",
                runtime_gate.get(
                    "runtime_risk_level"
                ),
            ],
            [
                "Failure Origin",
                runtime_gate.get(
                    "failure_origin"
                ),
            ],
            [
                "Failure Type",
                runtime_gate.get(
                    "failure_type"
                ),
            ],
        ],
    )

    workflow_table = format_markdown_table(
        [
            "Workflow Component",
            "Status",
        ],
        [
            [
                "Agent 3 Source Review",
                workflow_status.get(
                    "source_review",
                    "NOT_RUN",
                ),
            ],
            [
                "Validated Test Execution",
                workflow_status.get(
                    "test_execution",
                    "NOT_RUN",
                ),
            ],
            [
                "Runtime Quality Intelligence Analyst",
                workflow_status.get(
                    "log_analysis",
                    "NOT_REQUESTED",
                ),
            ],
            [
                "Defect Resolution Intelligence Analyst",
                workflow_status.get(
                    "repair_guidance",
                    "NOT_REQUESTED",
                ),
            ],
            [
                "Agent 3 Code Repair Guidance",
                workflow_status.get(
                    "code_repair_guidance",
                    "NOT_REQUESTED",
                ),
            ],
        ],
    )

    return (
        "## Combined QA Decision\n\n"
        f"{decision_table}\n\n"
        "### Runtime Gate\n\n"
        f"{runtime_table}\n\n"
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
    run_summary = log_agent_json.get(
        "run_summary",
        {},
    )

    run_table = format_markdown_table(
        [
            "Runtime Field",
            "Result",
        ],
        [
            [
                "Execution Status",
                log_agent_json.get(
                    "execution_status"
                ),
            ],
            [
                "Test Result",
                log_agent_json.get(
                    "test_result"
                ),
            ],
            [
                "Runtime Risk",
                log_agent_json.get(
                    "runtime_risk_level"
                ),
            ],
            [
                "Failure Origin",
                log_agent_json.get(
                    "failure_origin"
                ),
            ],
            [
                "Release Gate",
                log_agent_json.get(
                    "release_gate"
                ),
            ],
            [
                "Diagnosis Confidence",
                log_agent_json.get(
                    "diagnosis_confidence"
                ),
            ],
            [
                "Evidence Quality",
                log_agent_json.get(
                    "evidence_quality"
                ),
            ],
            [
                "Framework",
                safe_value(
                    run_summary.get(
                        "framework"
                    ),
                    "Not available",
                ),
            ],
            [
                "Total",
                run_summary.get(
                    "total",
                    0,
                ),
            ],
            [
                "Passed",
                run_summary.get(
                    "passed",
                    0,
                ),
            ],
            [
                "Failed",
                run_summary.get(
                    "failed",
                    0,
                ),
            ],
            [
                "Errors",
                run_summary.get(
                    "errors",
                    0,
                ),
            ],
            [
                "Skipped",
                run_summary.get(
                    "skipped",
                    0,
                ),
            ],
            [
                "Exit Code",
                run_summary.get(
                    "exit_code"
                ),
            ],
            [
                "Duration Seconds",
                run_summary.get(
                    "duration_seconds"
                ),
            ],
            [
                "Report Source",
                safe_value(
                    run_summary.get(
                        "report_source"
                    ),
                    "Not available",
                ),
            ],
        ],
    )

    group_sections = []

    for group in log_agent_json.get(
        "root_cause_groups",
        [],
    ):
        evidence_rows = []

        for item in group.get(
            "evidence",
            [],
        ):
            application_location = safe_value(
                item.get(
                    "application_file"
                ),
                "Not mapped",
            )

            if (
                item.get(
                    "application_file"
                )
                and item.get(
                    "application_line"
                )
            ):
                application_location = (
                    f"{item.get('application_file')}:"
                    f"{item.get('application_line')}"
                )

            test_location = safe_value(
                item.get(
                    "test_file"
                ),
                "Not mapped",
            )

            if (
                item.get(
                    "test_file"
                )
                and item.get(
                    "test_line"
                )
            ):
                test_location = (
                    f"{item.get('test_file')}:"
                    f"{item.get('test_line')}"
                )

            evidence_rows.append(
                [
                    safe_value(
                        item.get(
                            "test_name"
                        ),
                        "Unknown",
                    ),
                    safe_value(
                        item.get(
                            "expected"
                        ),
                        "Not available",
                    ),
                    safe_value(
                        item.get(
                            "actual"
                        ),
                        safe_value(
                            item.get(
                                "exception_type"
                            ),
                            "Not available",
                        ),
                    ),
                    safe_value(
                        item.get(
                            "exception_type"
                        ),
                        "Not available",
                    ),
                    safe_value(
                        item.get(
                            "exception_message"
                        ),
                        "Not available",
                    ),
                    application_location,
                    test_location,
                ]
            )

        evidence_table = format_markdown_table(
            [
                "Test",
                "Expected",
                "Actual",
                "Exception Type",
                "Exception Message",
                "Application",
                "Test Location",
            ],
            evidence_rows,
        )

        group_sections.append(
            f"#### {group.get('group_id')} — {group.get('title')}\n\n"
            f"- Category: {group.get('category')}\n"
            f"- Failure Origin: {safe_value(group.get('failure_origin'), 'NOT_ESTABLISHED')}\n"
            f"- Affected Tests: {format_inline_list(group.get('affected_tests', []))}\n\n"
            f"**Root Cause**\n\n"
            f"{group.get('root_cause')}\n\n"
            f"**Runtime Impact**\n\n"
            f"{group.get('runtime_impact')}\n\n"
            f"**Required Action**\n\n"
            f"{group.get('required_action')}\n\n"
            f"**Evidence**\n\n"
            f"{evidence_table}"
        )

    groups_text = (
        "\n\n".join(
            group_sections
        )
        if group_sections
        else (
            "No runtime root-cause groups were reported."
        )
    )

    log_section = (
        "## Runtime Quality Intelligence Analyst\n\n"
        f"- Agent ID: {safe_value(log_agent_json.get('agent_id'), 'runtime-quality-analyst')}\n"
        f"- Version: {safe_value(log_agent_json.get('agent_version'), '2.0')}\n"
        f"- Mode: {safe_value(log_agent_json.get('mode'), 'Not available')}\n"
        f"- Model: {safe_value(log_agent_json.get('model'), 'Deterministic fallback')}\n\n"
        "### Runtime Assessment\n\n"
        f"{run_table}\n\n"
        "### Summary\n\n"
        f"{safe_value(log_agent_json.get('summary'), 'Not requested')}\n\n"
        "### Root Cause Groups\n\n"
        f"{groups_text}\n\n"
        "### Required Actions\n\n"
        f"{format_markdown_list(log_agent_json.get('required_actions', []))}\n\n"
        "### Verification Steps\n\n"
        f"{format_markdown_list(log_agent_json.get('verification_steps', []))}\n\n"
        "### Runtime Warnings\n\n"
        f"{format_markdown_list(log_agent_json.get('warnings', []))}\n\n"
        "### Runtime Limitations\n\n"
        f"{format_markdown_list(log_agent_json.get('limitations', []))}\n\n"
    )

    if log_agent_json.get(
        "llm_error"
    ):
        log_section += (
            "### Runtime LLM Fallback Reason\n\n"
            f"{log_agent_json.get('llm_error')}\n\n"
        )

    repair_contract_sections = []
    for contract in repair_agent_json.get("stitch_repair_contracts", []):
        repair_contract_sections.append(
            f"#### {safe_value(contract.get('contract_id'), 'Repair Contract')} — "
            f"{safe_value(contract.get('title'), 'Repair target')}\n\n"
            f"- Findings: {format_inline_list(contract.get('finding_refs', []))}\n"
            f"- Priority: {safe_value(contract.get('priority'), 'P3')}\n"
            f"- Side-effect Risk: {safe_value(contract.get('side_effect_risk'), 'UNKNOWN')}\n"
            f"- Status: {safe_value(contract.get('status'), 'PENDING_VERIFICATION')}\n\n"
            f"**Why This Priority**\n\n{safe_value(contract.get('priority_reason'), 'Not available')}\n\n"
            f"**Repair Objective**\n\n{safe_value(contract.get('repair_objective'), 'Not available')}\n\n"
            f"**Repair Strategy**\n\n{safe_value(contract.get('repair_strategy'), 'Not available')}\n\n"
            f"**Change Boundary**\n\n{safe_value(contract.get('change_boundary'), 'Not available')}\n\n"
            f"**Protected Behavior**\n\n{safe_value(contract.get('protected_behavior'), 'Not available')}\n\n"
            f"**Verification**\n\n{safe_value(contract.get('verification'), 'Not available')}\n\n"
            f"**Done Condition**\n\n{safe_value(contract.get('done_condition'), 'Not available')}"
        )

    repair_contracts_text = (
        "\n\n".join(repair_contract_sections)
        if repair_contract_sections
        else "No Stitch Repair Contracts were generated."
    )

    repair_section = (
        "## Defect Resolution Intelligence Analyst\n\n"
        f"- Agent ID: {safe_value(repair_agent_json.get('agent_id'), 'defect-resolution-analyst')}\n"
        f"- Version: {safe_value(repair_agent_json.get('agent_version'), '2.0')}\n"
        f"- Mode: {safe_value(repair_agent_json.get('mode'), 'Not available')}\n"
        f"- Model: {safe_value(repair_agent_json.get('model'), 'Not used')}\n"
        f"- Status: {safe_value(repair_agent_json.get('status'), 'Not requested')}\n"
        f"- Overall Repair Priority: {safe_value(repair_agent_json.get('overall_priority'), 'NONE')}\n"
        f"- Planning Confidence: {safe_value(repair_agent_json.get('confidence'), 'LOW')}\n"
        f"- Repair Side-effect Risk: {safe_value(repair_agent_json.get('repair_risk_level'), 'UNKNOWN')}\n"
        f"- Auto Apply: {safe_value(repair_agent_json.get('auto_apply'), False)}\n\n"
        "### Summary\n\n"
        f"{safe_value(repair_agent_json.get('summary'), 'Not requested')}\n\n"
        "### Stitch Repair Contracts\n\n"
        f"{repair_contracts_text}\n\n"
        "### Current Knowledge Check\n\n"
        f"- Required: {bool(repair_agent_json.get('current_knowledge_required', False))}\n"
        f"- Reason: {safe_value(repair_agent_json.get('current_knowledge_reason'), 'Not required')}\n\n"
        "### Next Action\n\n"
        f"{safe_value(repair_agent_json.get('next_action'), 'Not available')}\n\n"
        "### Warnings\n\n"
        f"{format_markdown_list(repair_agent_json.get('warnings', []))}\n\n"
        "### Limitations\n\n"
        f"{format_markdown_list(repair_agent_json.get('limitations', []))}\n\n"
    )

    if repair_agent_json.get("llm_error"):
        repair_section += (
            "### Agent 2 LLM Fallback Reason\n\n"
            f"{repair_agent_json.get('llm_error')}\n\n"
        )

    code_section = (
        "## Agent 3 Runtime Code Repair Guidance\n\n"
        f"- Agent: {safe_value(code_agent_json.get('agent'), 'Not available')}\n"
        f"- Mode: {safe_value(code_agent_json.get('mode'), 'Not available')}\n"
        f"- Status: {safe_value(code_agent_json.get('status'), 'Not requested')}\n"
        f"- Risk Level: {safe_value(code_agent_json.get('risk_level'), 'UNKNOWN')}\n"
        f"- Auto Apply: {safe_value(code_agent_json.get('auto_apply'), False)}\n\n"
        "### Summary\n\n"
        f"{safe_value(code_agent_json.get('summary'), 'Not requested')}\n\n"
        "### Suggested Patch Guidance\n\n"
        f"{safe_value(code_agent_json.get('suggested_patch'), 'Not available')}\n\n"
        "### Verification\n\n"
        f"{safe_value(code_agent_json.get('verification'), 'Not available')}\n\n"
        "### Warnings\n\n"
        f"{format_markdown_list(code_agent_json.get('warnings', []))}\n\n"
    )

    if code_agent_json.get(
        "llm_error"
    ):
        code_section += (
            "### Agent 3 LLM Error\n\n"
            f"{code_agent_json.get('llm_error')}\n\n"
        )

    return (
        log_section
        + repair_section
        + code_section
    )


def generate_report(
    scan_result,
    execution_result=None,
    agent_data=None,
    repair_data=None,
    code_data=None,
    source_review_data=None,
    qa_decision=None,
    workflow_context=None,
):
    workflow_context = (
        workflow_context
        or {}
    )
    project_path = Path(
        scan_result[
            "project_path"
        ]
    )
    project_type = scan_result[
        "project_type"
    ]
    static_map = scan_result.get(
        "static_map",
        {},
    )
    source_discovery = scan_result.get(
        "source_review",
        {},
    )
    generated_at = datetime.now().astimezone().isoformat(
        timespec="seconds"
    )

    md_report_path = (
        project_path
        / "STITCH_QA_REPORT.md"
    )
    json_report_path = (
        project_path
        / "STITCH_QA_REPORT.json"
    )

    if execution_result is None:
        coming_soon_message = static_map.get(
            "coming_soon_message",
            "Support for this project type is planned for a future release.",
        )

        executive_summary = {
            "final_status": "SKIPPED",
            "risk_level": "UNKNOWN",
            "release_recommendation": (
                "NOT_APPLICABLE"
            ),
            "evidence_completeness": (
                "NOT_STARTED"
            ),
            "ci_exit_code": 0,
        }

        json_content = {
            "report_metadata": {
                "schema_version": REPORT_SCHEMA_VERSION,
                "tool_version": TOOL_VERSION,
                "generated_at": generated_at,
            },
            "executive_summary": (
                executive_summary
            ),
            "final_status": "SKIPPED",
            "project_type": (
                project_type
            ),
            "coming_soon_message": (
                coming_soon_message
            ),
            "skip_reason": (
                "Unsupported or unrecognized project type."
            ),
            "exit_code": 0,
            "generated_at": generated_at,
        }

        md_content = (
            "# Stitch QA Report\n\n"
            "## Executive QA Summary\n\n"
            + format_markdown_table(
                [
                    "Field",
                    "Result",
                ],
                [
                    [
                        "Final QA Status",
                        "**SKIPPED**",
                    ],
                    [
                        "Detected Project Type",
                        project_type,
                    ],
                    [
                        "Release Recommendation",
                        "**NOT_APPLICABLE**",
                    ],
                    [
                        "CI Exit Code",
                        0,
                    ],
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

        md_report_path.write_text(
            md_content,
            encoding="utf-8",
        )
        json_report_path.write_text(
            json.dumps(
                json_content,
                indent=2,
            ),
            encoding="utf-8",
        )

        return md_report_path

    qa_decision = (
        qa_decision
        or build_qa_decision(
            execution_result,
            source_review_data,
            agent_data,
            repair_data,
            code_data,
            workflow_context,
        )
    )
    final_status = qa_decision[
        "status"
    ]
    project_recommendations = scan_result.get(
        "project_recommendations",
        [],
    )
    execution_status = build_execution_status(
        execution_result
    )
    execution_summary = build_execution_summary(
        project_type,
        execution_result,
        source_review_data,
    )
    stdout_text = execution_result.get(
        "stdout",
        "",
    )[-2000:]
    stderr_text = execution_result.get(
        "stderr",
        "",
    )[-2000:]

    source_review_json = build_source_review_json(
        source_review_data
    )
    source_review_json[
        "findings"
    ] = normalize_findings(
        source_review_json.get(
            "findings",
            [],
        )
    )
    source_review_json[
        "findings_count"
    ] = len(
        source_review_json[
            "findings"
        ]
    )

    log_agent_json = build_log_agent_json(
        agent_data
    )
    repair_agent_json = build_repair_agent_json(
        repair_data
    )
    code_agent_json = build_code_agent_json(
        code_data
    )
    findings_summary = build_findings_summary(
        source_review_json[
            "findings"
        ]
    )
    qa_scope = build_scope_summary(
        static_map,
        build_source_discovery_json(
            source_discovery
        ),
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
        log_agent_json,
        repair_agent_json,
    )

    runtime_evidence = (
        execution_result.get(
            "runtime_evidence"
        )
        or {}
    )
    runtime_test_summary = (
        runtime_evidence.get(
            "test_summary"
        )
        or log_agent_json.get(
            "run_summary",
            {},
        )
    )

    executive_summary = {
        "final_status": final_status,
        "risk_level": qa_decision.get(
            "risk_level"
        ),
        "release_recommendation": qa_decision.get(
            "release_recommendation"
        ),
        "evidence_completeness": qa_decision.get(
            "completeness"
        ),
        "ci_exit_code": qa_decision.get(
            "ci_exit_code"
        ),
        "source_review_status": source_review_json.get(
            "status"
        ),
        "test_execution_status": execution_status,
        "total_source_findings": findings_summary.get(
            "total",
            0,
        ),
        "runtime_execution_status": log_agent_json.get(
            "execution_status"
        ),
        "runtime_test_result": log_agent_json.get(
            "test_result"
        ),
        "runtime_release_gate": log_agent_json.get(
            "release_gate"
        ),
        "runtime_risk_level": log_agent_json.get(
            "runtime_risk_level"
        ),
        "runtime_failure_origin": log_agent_json.get(
            "failure_origin"
        ),
        "runtime_diagnosis_confidence": log_agent_json.get(
            "diagnosis_confidence"
        ),
        "runtime_test_summary": runtime_test_summary,
    }

    json_content = {
        "report_metadata": {
            "schema_version": REPORT_SCHEMA_VERSION,
            "tool_version": TOOL_VERSION,
            "generated_at": generated_at,
        },
        "executive_summary": executive_summary,
        "project": {
            "path": scan_result[
                "project_path"
            ],
            "type": scan_result[
                "project_type"
            ],
            "total_files": scan_result[
                "total_files"
            ],
            "total_folders": scan_result[
                "total_folders"
            ],
            "ignored_items": scan_result[
                "ignored_items"
            ],
        },
        "qa_scope": qa_scope,
        "static_mapping": build_static_mapping_json(
            static_map
        ),
        "source_review_discovery": build_source_discovery_json(
            source_discovery
        ),
        "findings_summary": findings_summary,
        "source_review": source_review_json,
        "project_recommendations": format_list(
            project_recommendations
        ),
        "execution": {
            "status": execution_status,
            "executed": bool(
                execution_result.get(
                    "executed",
                    True,
                )
            ),
            "skipped": bool(
                execution_result.get(
                    "skipped",
                    False,
                )
            ),
            "skip_reason": execution_result.get(
                "skip_reason"
            ),
            "command": execution_result.get(
                "command"
            ),
            "command_profile": execution_result.get(
                "command_profile"
            ),
            "execution_policy": execution_result.get(
                "execution_policy"
            ),
            "execution_strategy": execution_result.get(
                "execution_strategy"
            ),
            "shell_enabled": bool(
                execution_result.get(
                    "shell_enabled",
                    False,
                )
            ),
            "command_args": format_list(
                execution_result.get(
                    "command_args",
                    [],
                )
            ),
            "executable": execution_result.get(
                "executable"
            ),
            "validation_status": execution_result.get(
                "validation_status"
            ),
            "validation_error": execution_result.get(
                "validation_error"
            ),
            "timeout_seconds": execution_result.get(
                "timeout_seconds"
            ),
            "success": execution_result.get(
                "success"
            ),
            "exit_code": execution_result.get(
                "exit_code"
            ),
            "failure_type": execution_result.get(
                "failure_type"
            ),
            "help_message": execution_result.get(
                "help_message"
            ),
            "runtime_evidence": runtime_evidence,
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
        json.dumps(
            json_content,
            indent=2,
        ),
        encoding="utf-8",
    )

    executive_table = format_markdown_table(
        [
            "Field",
            "Result",
        ],
        [
            [
                "Final QA Status",
                f"**{final_status}**",
            ],
            [
                "Combined Risk Level",
                f"**{qa_decision.get('risk_level')}**",
            ],
            [
                "Release Recommendation",
                f"**{qa_decision.get('release_recommendation')}**",
            ],
            [
                "Evidence Completeness",
                f"**{qa_decision.get('completeness')}**",
            ],
            [
                "Runtime Test Result",
                log_agent_json.get(
                    "test_result"
                ),
            ],
            [
                "Runtime Risk",
                log_agent_json.get(
                    "runtime_risk_level"
                ),
            ],
            [
                "Runtime Failure Origin",
                log_agent_json.get(
                    "failure_origin"
                ),
            ],
            [
                "Runtime Release Gate",
                log_agent_json.get(
                    "release_gate"
                ),
            ],
            [
                "CI Exit Code",
                qa_decision.get(
                    "ci_exit_code"
                ),
            ],
        ],
    )

    scope_table = format_markdown_table(
        [
            "QA Scope Field",
            "Result",
        ],
        [
            [
                "Source Review Supported",
                qa_scope.get(
                    "source_review_supported"
                ),
            ],
            [
                "Source Files Discovered",
                qa_scope.get(
                    "source_files_discovered"
                ),
            ],
            [
                "Source Files Reviewed",
                qa_scope.get(
                    "source_files_reviewed"
                ),
            ],
            [
                "Source Review Status",
                qa_scope.get(
                    "source_review_status"
                ),
            ],
            [
                "Tests Detected",
                qa_scope.get(
                    "tests_detected"
                ),
            ],
            [
                "Test Files Detected",
                qa_scope.get(
                    "test_files_detected"
                ),
            ],
            [
                "Test Framework",
                safe_value(
                    qa_scope.get(
                        "test_framework"
                    ),
                    "Not available",
                ),
            ],
            [
                "Test Execution Status",
                qa_scope.get(
                    "test_execution_status"
                ),
            ],
            [
                "Evidence Completeness",
                qa_scope.get(
                    "evidence_completeness"
                ),
            ],
        ],
    )

    source_section = build_source_review_markdown(
        source_review_json
    )
    decision_section = build_qa_decision_markdown(
        qa_decision
    )
    agent_section = build_agent_details_markdown(
        log_agent_json,
        repair_agent_json,
        code_agent_json,
    )

    md_content = (
        "# Stitch QA Report\n\n"
        "## Executive QA Summary\n\n"
        f"{executive_table}\n\n"
        "## Project\n\n"
        f"- Path: `{scan_result['project_path']}`\n"
        f"- Type: {scan_result['project_type']}\n"
        f"- Total Files: {scan_result['total_files']}\n"
        f"- Total Folders: {scan_result['total_folders']}\n"
        f"- Ignored Items: {scan_result['ignored_items']}\n\n"
        "## QA Scope\n\n"
        f"{scope_table}\n\n"
        "## Static Mapping\n\n"
        f"{build_static_mapping_markdown(static_map)}\n\n"
        "## Execution Summary\n\n"
        f"{execution_summary}\n\n"
        f"{source_section}"
        f"{decision_section}"
        f"{agent_section}"
        "## Project Recommendations\n\n"
        f"{format_markdown_list(project_recommendations)}\n\n"
        "## Next Actions\n\n"
        f"{format_next_actions(next_actions)}\n\n"
        "## Report Limitations\n\n"
        f"{format_markdown_list(limitations)}\n\n"
        "## Execution Evidence\n\n"
        "### STDOUT\n\n"
        "```text\n"
        f"{stdout_text or 'No stdout output.'}\n"
        "```\n\n"
        "### STDERR\n\n"
        "```text\n"
        f"{stderr_text or 'No stderr output.'}\n"
        "```\n\n"
        "## Report Metadata\n\n"
        f"- Report Schema Version: {REPORT_SCHEMA_VERSION}\n"
        f"- Tool Version: {TOOL_VERSION}\n"
        f"- Generated At: {generated_at}\n"
    )

    md_report_path.write_text(
        md_content,
        encoding="utf-8",
    )

    return md_report_path

