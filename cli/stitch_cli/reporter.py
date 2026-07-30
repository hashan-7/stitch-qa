from pathlib import Path
from datetime import datetime
import json


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


def build_status_label(execution_result, agent_data=None, source_review_data=None):
    if agent_data and agent_data.get("final_status"):
        return agent_data.get("final_status")

    if execution_result.get("skipped"):
        source_status = str(
            source_review_data.get("status") if source_review_data else ""
        ).upper()

        if source_status in {"COMPLETED", "PARTIAL"}:
            return "REVIEW_COMPLETED_WITHOUT_TESTS"

        return "QA_INCOMPLETE"

    return "PASS" if execution_result.get("success") else "FAIL"


def build_execution_status(execution_result):
    if execution_result.get("status"):
        return execution_result["status"]

    if execution_result.get("skipped"):
        return "SKIPPED"

    return "PASSED" if execution_result.get("success") else "FAILED"


def build_execution_summary(project_type, execution_result, source_review_data=None):
    command = safe_value(execution_result.get("command"), "Not available")

    if execution_result.get("skipped"):
        reason = safe_value(
            execution_result.get("skip_reason"),
            "Test execution was not required.",
        )
        source_status = safe_value(
            source_review_data.get("status") if source_review_data else None,
            "NOT_RUN",
        )
        return (
            f"The {project_type} was scanned successfully. Test execution was skipped because {reason} "
            f"The command `{command}` was not run. Agent 3 source review status was `{source_status}`."
        )

    outcome = "completed successfully" if execution_result.get("success") else "failed"
    return (
        f"The {project_type} was scanned and executed using `{command}`. "
        f"The execution {outcome} with exit code {execution_result.get('exit_code')}."
    )


def build_static_mapping_json(static_map):
    mapping = {
        "build_file": static_map.get("build_file"),
        "main_source_dir": static_map.get("main_source_dir"),
        "test_source_dir": static_map.get("test_source_dir"),
        "test_source_dirs": format_list(static_map.get("test_source_dirs", [])),
        "main_file": static_map.get("main_file"),
        "suggested_command": static_map.get("suggested_command"),
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
        "excluded_test_files_count": int(
            source_review.get("excluded_test_files_count", 0)
        ),
        "excluded_sensitive_files_count": int(
            source_review.get("excluded_sensitive_files_count", 0)
        ),
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


def format_summary_mapping(mapping):
    if not mapping:
        return "None"

    return ", ".join(f"{key}: {value}" for key, value in mapping.items())


def format_source_findings(findings):
    if not findings:
        return "No source-code findings were reported."

    sections = []

    for finding in findings:
        severity = safe_value(finding.get("severity"), "UNKNOWN")
        title = safe_value(finding.get("title"), "Source-code finding")
        file_path = safe_value(finding.get("file_path"), "Project-level")
        line = finding.get("line")
        location = f"{file_path}:{line}" if line else file_path
        sections.append(
            f"### [{severity}] {title}\n\n"
            f"- Finding ID: {safe_value(finding.get('id'), 'Not available')}\n"
            f"- Location: `{location}`\n"
            f"- Category: {safe_value(finding.get('category'), 'Not available')}\n"
            f"- Confidence: {safe_value(finding.get('confidence'), 'Not available')}\n\n"
            f"**Evidence:** {safe_value(finding.get('evidence'), 'Not available')}\n\n"
            f"**Impact:** {safe_value(finding.get('impact'), 'Not available')}\n\n"
            f"**Recommendation:** {safe_value(finding.get('recommendation'), 'Not available')}"
        )

    return "\n\n".join(sections)


def build_source_review_markdown(source_review_data):
    data = build_source_review_json(source_review_data)
    findings_text = format_source_findings(data["findings"])
    warnings_text = format_markdown_list(data["warnings"])
    limitations_text = format_markdown_list(data["limitations"])
    coverage = data.get("coverage", {})

    return (
        "## Agent 3 Source Code QA Review\n\n"
        f"- Status: **{safe_value(data.get('status'), 'NOT_RUN')}**\n"
        f"- Agent: {safe_value(data.get('agent'), 'Not available')}\n"
        f"- Mode: {safe_value(data.get('mode'), 'Not available')}\n"
        f"- Reviewed Files: {data.get('reviewed_files_count', 0)}\n"
        f"- Findings: {data.get('findings_count', 0)}\n"
        f"- Risk Level: **{safe_value(data.get('risk_level'), 'UNKNOWN')}**\n"
        f"- Release Recommendation: **{safe_value(data.get('release_recommendation'), 'QA_INCOMPLETE')}**\n"
        f"- Severity Summary: {format_summary_mapping(data.get('severity_summary'))}\n"
        f"- Category Summary: {format_summary_mapping(data.get('category_summary'))}\n\n"
        "### Summary\n\n"
        f"{safe_value(data.get('summary'), 'Source review was not run.')}\n\n"
        "### Coverage\n\n"
        f"- Discovered Files: {coverage.get('discovered_files_count', 0)}\n"
        f"- Submitted Files: {coverage.get('submitted_files_count', 0)}\n"
        f"- Submitted Characters: {coverage.get('submitted_chars', 0)}\n"
        f"- Truncated Files: {coverage.get('truncated_files_count', 0)}\n"
        f"- Omitted Files: {coverage.get('omitted_files_count', 0)}\n"
        f"- Read Errors: {coverage.get('read_error_files_count', 0)}\n\n"
        "### Findings\n\n"
        f"{findings_text}\n\n"
        "### Warnings\n\n"
        f"{warnings_text}\n\n"
        "### Limitations\n\n"
        f"{limitations_text}\n\n"
        "### Verification\n\n"
        f"{safe_value(data.get('verification'), 'Rerun Stitch QA after addressing confirmed findings.')}\n\n"
    )


def generate_report(
    scan_result,
    execution_result,
    agent_data=None,
    repair_data=None,
    code_data=None,
    source_review_data=None,
):
    project_path = Path(scan_result["project_path"])
    project_type = scan_result.get("project_type", "Unknown")
    static_map = scan_result.get("static_map", {})
    source_discovery = scan_result.get("source_review", {})
    generated_at = str(datetime.now())

    md_report_path = project_path / "STITCH_QA_REPORT.md"
    json_report_path = project_path / "STITCH_QA_REPORT.json"

    if execution_result is None:
        coming_soon_message = static_map.get(
            "coming_soon_message",
            "Support for this project type is planned for a future release.",
        )

        md_content = f"""# Stitch QA Report

## Project Type Not Yet Supported

**Detected Project Type:** {project_type}

**Message:** {coming_soon_message}

Stitch QA V2 currently supports:
- **Java Maven** (pom.xml)
- **Python** (requirements.txt / pyproject.toml)

**Action Taken:** QA execution was skipped. No tests or AI agent workflows were run.
**Exit Code:** 0 (Clean skip)

---
Generated At: {generated_at}
"""

        json_content = {
            "final_status": "SKIPPED",
            "project_type": project_type,
            "coming_soon_message": coming_soon_message,
            "skip_reason": "Unsupported or unrecognized project type.",
            "exit_code": 0,
            "generated_at": generated_at,
        }

        md_report_path.write_text(md_content, encoding="utf-8")
        json_report_path.write_text(json.dumps(json_content, indent=2), encoding="utf-8")

        return md_report_path

    project_recommendations = scan_result.get("project_recommendations", [])
    final_status = build_status_label(
        execution_result,
        agent_data,
        source_review_data,
    )
    execution_status = build_execution_status(execution_result)
    execution_summary = build_execution_summary(
        project_type,
        execution_result,
        source_review_data,
    )
    stdout_text = execution_result.get("stdout", "")[-2000:]
    stderr_text = execution_result.get("stderr", "")[-2000:]
    source_review_json = build_source_review_json(source_review_data)

    json_content = {
        "project": {
            "path": scan_result["project_path"],
            "type": scan_result["project_type"],
            "total_files": scan_result["total_files"],
            "total_folders": scan_result["total_folders"],
            "ignored_items": scan_result["ignored_items"],
        },
        "static_mapping": build_static_mapping_json(static_map),
        "source_review_discovery": build_source_discovery_json(source_discovery),
        "source_review": source_review_json,
        "project_recommendations": format_list(project_recommendations),
        "execution": {
            "status": execution_status,
            "executed": bool(execution_result.get("executed", True)),
            "skipped": bool(execution_result.get("skipped", False)),
            "skip_reason": execution_result.get("skip_reason"),
            "command": execution_result.get("command"),
            "success": execution_result.get("success"),
            "exit_code": execution_result.get("exit_code"),
            "failure_type": execution_result.get("failure_type"),
            "help_message": execution_result.get("help_message"),
        },
        "log_agent": {
            "agent": safe_value(agent_data.get("agent") if agent_data else None),
            "mode": safe_value(agent_data.get("mode") if agent_data else None),
            "final_status": safe_value(agent_data.get("final_status") if agent_data else None),
            "summary": safe_value(agent_data.get("summary") if agent_data else None),
            "root_cause": safe_value(agent_data.get("root_cause") if agent_data else None),
            "recommendation": safe_value(agent_data.get("recommendation") if agent_data else None),
            "issues": format_list(agent_data.get("issues") if agent_data else []),
            "warnings": format_list(agent_data.get("warnings") if agent_data else []),
            "llm_error": safe_value(agent_data.get("llm_error") if agent_data else None),
        },
        "repair_agent": {
            "agent": safe_value(repair_data.get("agent") if repair_data else None),
            "mode": safe_value(repair_data.get("mode") if repair_data else None),
            "risk_level": safe_value(repair_data.get("risk_level") if repair_data else None),
            "auto_apply": safe_value(repair_data.get("auto_apply") if repair_data else None),
            "summary": safe_value(repair_data.get("summary") if repair_data else None),
            "suggestions": format_list(repair_data.get("suggestions") if repair_data else []),
            "next_action": safe_value(repair_data.get("next_action") if repair_data else None),
            "llm_error": safe_value(repair_data.get("llm_error") if repair_data else None),
        },
        "code_agent_repair": {
            "agent": safe_value(code_data.get("agent") if code_data else None),
            "mode": safe_value(code_data.get("mode") if code_data else None),
            "risk_level": safe_value(code_data.get("risk_level") if code_data else None),
            "auto_apply": safe_value(code_data.get("auto_apply") if code_data else None),
            "summary": safe_value(code_data.get("summary") if code_data else None),
            "suggested_patch": safe_value(code_data.get("suggested_patch") if code_data else None),
            "verification": safe_value(code_data.get("verification") if code_data else None),
            "llm_error": safe_value(code_data.get("llm_error") if code_data else None),
        },
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

    log_issues = format_markdown_list(agent_data.get("issues") if agent_data else [])
    log_warnings = format_markdown_list(agent_data.get("warnings") if agent_data else [])
    repair_suggestions = format_markdown_list(repair_data.get("suggestions") if repair_data else [])
    project_recommendations_text = format_markdown_list(project_recommendations)
    static_mapping_text = build_static_mapping_markdown(static_map)
    detected_test_files_text = format_markdown_list(static_map.get("test_files", []))
    command_text = safe_value(execution_result.get("command"), "Not available")
    skip_reason_text = safe_value(execution_result.get("skip_reason"), "None")
    source_review_section = build_source_review_markdown(source_review_data)

    if execution_result.get("skipped"):
        evidence_section = (
            "## Evidence Logs\n\n"
            "No runtime evidence logs were generated because the test command was not executed.\n\n"
        )
    else:
        evidence_section = (
            "## Evidence Logs\n\n"
            "### STDOUT Snapshot\n\n"
            "```text\n"
            f"{stdout_text}\n"
            "```\n\n"
            "### STDERR / Warning Snapshot\n\n"
            "```text\n"
            f"{stderr_text}\n"
            "```\n\n"
        )

    if code_data:
        code_section = (
            "## Agent 3 Code Repair Guidance\n\n"
            f"- Agent: {safe_value(code_data.get('agent'), 'Not available')}\n"
            f"- Mode: {safe_value(code_data.get('mode'), 'Not available')}\n"
            f"- Risk Level: {safe_value(code_data.get('risk_level'), 'Not available')}\n"
            f"- Auto Apply: {safe_value(code_data.get('auto_apply'), 'Not available')}\n\n"
            "### Summary\n\n"
            f"{safe_value(code_data.get('summary'), 'Not available')}\n\n"
            "### Suggested Patch\n\n"
            f"{safe_value(code_data.get('suggested_patch'), 'No direct patch generated. Manual review required.')}\n\n"
            "### Verification\n\n"
            f"{safe_value(code_data.get('verification'), 'Rerun Stitch QA after applying any manual changes.')}\n\n"
        )

        if code_data.get("llm_error"):
            code_section += (
                "### Code Agent LLM Error\n\n"
                f"{code_data.get('llm_error')}\n\n"
            )
    else:
        code_section = (
            "## Agent 3 Code Repair Guidance\n\n"
            "No runtime code-repair guidance was requested or generated for this run.\n\n"
        )

    md_content = (
        "# Stitch QA Report\n\n"
        "## Executive Summary\n\n"
        f"- Final QA Status: **{final_status}**\n"
        f"- Project Type: {scan_result['project_type']}\n"
        f"- Source Review Status: **{source_review_json.get('status')}**\n"
        f"- Source Risk Level: **{source_review_json.get('risk_level')}**\n"
        f"- Release Recommendation: **{source_review_json.get('release_recommendation')}**\n"
        f"- Tests Found: {'Yes' if static_map.get('has_tests') else 'No'}\n"
        f"- Test Files Count: {static_map.get('test_files_count', 0)}\n"
        f"- Execution Status: **{execution_status}**\n"
        f"- Test Command: `{command_text}`\n"
        f"- Exit Code: {execution_result.get('exit_code')}\n\n"
        f"{execution_summary}\n\n"
        "## Project Summary\n\n"
        f"- Project Path: {scan_result['project_path']}\n"
        f"- Project Type: {scan_result['project_type']}\n"
        f"- Total Files: {scan_result['total_files']}\n"
        f"- Total Folders: {scan_result['total_folders']}\n"
        f"- Ignored Items: {scan_result['ignored_items']}\n"
        f"- Reviewable Source Files: {source_discovery.get('source_files_count', 0)}\n\n"
        "## Static Mapping\n\n"
        f"{static_mapping_text}\n\n"
        + source_review_section
        + "## Detected Test Files\n\n"
        f"{detected_test_files_text}\n\n"
        "## Project Recommendations\n\n"
        f"{project_recommendations_text}\n\n"
        "## Test Execution Result\n\n"
        f"- Status: {execution_status}\n"
        f"- Command: `{command_text}`\n"
        f"- Executed: {execution_result.get('executed', True)}\n"
        f"- Skipped: {execution_result.get('skipped', False)}\n"
        f"- Skip Reason: {skip_reason_text}\n"
        f"- Success: {execution_result.get('success')}\n"
        f"- Exit Code: {execution_result.get('exit_code')}\n"
        f"- Failure Type: {safe_value(execution_result.get('failure_type'), 'None')}\n"
        f"- Help Message: {safe_value(execution_result.get('help_message'), 'None')}\n\n"
        "## Agent 1 Runtime Log Analysis\n\n"
        f"- Agent: {safe_value(agent_data.get('agent') if agent_data else None, 'Not available')}\n"
        f"- Mode: {safe_value(agent_data.get('mode') if agent_data else None, 'Not available')}\n"
        f"- Final Status: {safe_value(agent_data.get('final_status') if agent_data else None, 'Not available')}\n\n"
        "### Summary\n\n"
        f"{safe_value(agent_data.get('summary') if agent_data else None, 'Not available')}\n\n"
        "### Root Cause\n\n"
        f"{safe_value(agent_data.get('root_cause') if agent_data else None, 'Not available')}\n\n"
        "### Recommendation\n\n"
        f"{safe_value(agent_data.get('recommendation') if agent_data else None, 'Not available')}\n\n"
        "### Issues\n\n"
        f"{log_issues}\n\n"
        "### Warnings\n\n"
        f"{log_warnings}\n\n"
        "## Agent 2 Repair Guidance\n\n"
        f"- Agent: {safe_value(repair_data.get('agent') if repair_data else None, 'Not available')}\n"
        f"- Mode: {safe_value(repair_data.get('mode') if repair_data else None, 'Not available')}\n"
        f"- Risk Level: {safe_value(repair_data.get('risk_level') if repair_data else None, 'Not available')}\n"
        f"- Auto Apply: {safe_value(repair_data.get('auto_apply') if repair_data else None, 'Not available')}\n\n"
        "### Summary\n\n"
        f"{safe_value(repair_data.get('summary') if repair_data else None, 'Not available')}\n\n"
        "### Suggestions\n\n"
        f"{repair_suggestions}\n\n"
        "### Next Action\n\n"
        f"{safe_value(repair_data.get('next_action') if repair_data else None, 'Not available')}\n\n"
        + code_section
        + evidence_section
        + "## Final QA Status\n\n"
        f"**{final_status}**\n\n"
        "----------------------------------------\n"
        f"Generated At: {generated_at}\n"
    )

    md_report_path.write_text(md_content, encoding="utf-8")

    return md_report_path
