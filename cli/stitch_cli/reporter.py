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


def safe_value(value, default=None):
    if value is None or value == "":
        return default

    return value


def build_status_label(execution_result, agent_data=None):
    if agent_data and agent_data.get("final_status"):
        return agent_data.get("final_status")

    return "PASS" if execution_result["success"] else "FAIL"


def build_static_mapping_json(static_map):
    mapping = {
        "build_file": static_map.get("build_file"),
        "main_source_dir": static_map.get("main_source_dir"),
        "test_source_dir": static_map.get("test_source_dir"),
        "main_file": static_map.get("main_file"),
        "suggested_command": static_map.get("suggested_command"),
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
        f"- Main File: {safe_value(static_map.get('main_file'), 'Not available')}",
        f"- Suggested Command: {safe_value(static_map.get('suggested_command'), 'Not available')}",
    ]

    if static_map.get("has_maven_wrapper"):
        lines.append(f"- Maven Wrapper: {static_map.get('has_maven_wrapper')}")
        lines.append(f"- Wrapper Command: {safe_value(static_map.get('wrapper_command'), 'Not available')}")

    if static_map.get("wrapper_recommendation"):
        lines.append(f"- Wrapper Recommendation: {static_map.get('wrapper_recommendation')}")

    return "\n".join(lines)


def generate_report(scan_result, execution_result, agent_data=None, repair_data=None, code_data=None):
    project_path = Path(scan_result["project_path"])
    project_type = scan_result.get("project_type", "Unknown")
    static_map = scan_result.get("static_map", {})
    generated_at = str(datetime.now())

    if execution_result is None:
        coming_soon_message = static_map.get("coming_soon_message", "Support for this project type is planned for a future release.")

        md_content = f"""# Stitch QA Report

## Project Type Not Yet Supported

**Detected Project Type:** {project_type}

**Message:** {coming_soon_message}

Stitch QA V2 currently supports:
- **Java Maven** (pom.xml)
- **Python** (requirements.txt / pyproject.toml)

**Action Taken:** Execution was skipped. No tests were run, and no agents were called.
**Exit Code:** 0 (Clean skip)

Thank you for trying Stitch QA! 

---
Generated At: {generated_at}
"""

        json_content = {
            "final_status": "SKIPPED",
            "project_type": project_type,
            "coming_soon_message": coming_soon_message,
            "skip_reason": "Unsupported or unrecognized project type.",
            "exit_code": 0,
            "generated_at": generated_at
        }

        md_report_path = project_path / "STITCH_QA_REPORT.md"
        json_report_path = project_path / "STITCH_QA_REPORT.json"

        md_report_path.write_text(md_content, encoding="utf-8")
        json_report_path.write_text(json.dumps(json_content, indent=2), encoding="utf-8")

        return md_report_path

    md_report_path = project_path / "STITCH_QA_REPORT.md"
    json_report_path = project_path / "STITCH_QA_REPORT.json"

    project_recommendations = scan_result.get("project_recommendations", [])

    final_status = build_status_label(execution_result, agent_data)

    stdout_text = execution_result["stdout"][-2000:] if execution_result["stdout"] else ""
    stderr_text = execution_result["stderr"][-2000:] if execution_result["stderr"] else ""

    json_content = {
        "project": {
            "path": scan_result["project_path"],
            "type": scan_result["project_type"],
            "total_files": scan_result["total_files"],
            "total_folders": scan_result["total_folders"],
            "ignored_items": scan_result["ignored_items"],
        },
        "static_mapping": build_static_mapping_json(static_map),
        "project_recommendations": format_list(project_recommendations),
        "execution": {
            "command": execution_result["command"],
            "success": execution_result["success"],
            "exit_code": execution_result["exit_code"],
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
        "code_agent": {
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
        encoding="utf-8"
    )

    log_issues = format_markdown_list(agent_data.get("issues") if agent_data else [])
    log_warnings = format_markdown_list(agent_data.get("warnings") if agent_data else [])
    repair_suggestions = format_markdown_list(repair_data.get("suggestions") if repair_data else [])
    project_recommendations_text = format_markdown_list(project_recommendations)
    static_mapping_text = build_static_mapping_markdown(static_map)

    code_section = ""

    if code_data:
        code_section = (
            "## Code Agent Suggestions\n\n"
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
            "## Code Agent Suggestions\n\n"
            "No code-level suggestions were generated for this run.\n\n"
        )

    md_content = (
        "# Stitch QA Report\n\n"

        "## Executive Summary\n\n"
        f"- Final QA Status: **{final_status}**\n"
        f"- Project Type: {scan_result['project_type']}\n"
        f"- Execution Command: `{execution_result['command']}`\n"
        f"- Exit Code: {execution_result['exit_code']}\n\n"
        f"The {scan_result['project_type']} was scanned and executed using `{execution_result['command']}`. "
        f"The execution {'completed successfully' if execution_result['success'] else 'failed'} with exit code {execution_result['exit_code']}.\n\n"

        "## Project Summary\n\n"
        f"- Project Path: {scan_result['project_path']}\n"
        f"- Project Type: {scan_result['project_type']}\n"
        f"- Total Files: {scan_result['total_files']}\n"
        f"- Total Folders: {scan_result['total_folders']}\n"
        f"- Ignored Items: {scan_result['ignored_items']}\n\n"

        "## Static Mapping\n\n"
        f"{static_mapping_text}\n\n"

        "## Project Recommendations\n\n"
        f"{project_recommendations_text}\n\n"

        "## Execution Result\n\n"
        f"- Command: `{execution_result['command']}`\n"
        f"- Success: {execution_result['success']}\n"
        f"- Exit Code: {execution_result['exit_code']}\n"
        f"- Failure Type: {safe_value(execution_result.get('failure_type'), 'None')}\n"
        f"- Help Message: {safe_value(execution_result.get('help_message'), 'None')}\n\n"

        "## AI Log Analysis\n\n"
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

        "## Repair Agent Suggestions\n\n"
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

        + code_section +

        "## Evidence Logs\n\n"
        "### STDOUT Snapshot\n\n"
        "```text\n"
        f"{stdout_text}\n"
        "```\n\n"

        "### STDERR / Warning Snapshot\n\n"
        "```text\n"
        f"{stderr_text}\n"
        "```\n\n"

        "## Final QA Status\n\n"
        f"**{final_status}**\n\n"
        "----------------------------------------\n"
        f"Generated At: {generated_at}\n"
    )

    md_report_path.write_text(md_content, encoding="utf-8")

    return md_report_path