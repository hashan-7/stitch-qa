from pathlib import Path
from datetime import datetime
import json


def format_list(items):
    if not items:
        return []

    return items


def safe_value(value, default=None):
    if value is None or value == "":
        return default
    return value


def build_status_label(execution_result, agent_data=None):
    if agent_data and agent_data.get("final_status"):
        return agent_data.get("final_status")

    return "PASS" if execution_result["success"] else "FAIL"


def generate_report(scan_result, execution_result, agent_data=None, repair_data=None):
    project_path = Path(scan_result["project_path"])

    md_report_path = project_path / "STITCH_QA_REPORT.md"
    json_report_path = project_path / "STITCH_QA_REPORT.json"

    static_map = scan_result["static_map"]

    final_status = build_status_label(execution_result, agent_data)

    stdout_text = execution_result["stdout"][-2000:] if execution_result["stdout"] else ""
    stderr_text = execution_result["stderr"][-2000:] if execution_result["stderr"] else ""

    # =========================
    # JSON STRUCTURE
    # =========================

    json_content = {
        "project": {
            "path": scan_result["project_path"],
            "type": scan_result["project_type"],
            "total_files": scan_result["total_files"],
            "total_folders": scan_result["total_folders"],
            "ignored_items": scan_result["ignored_items"],
        },
        "static_mapping": {
            "build_file": static_map.get("build_file"),
            "main_source_dir": static_map.get("main_source_dir"),
            "test_source_dir": static_map.get("test_source_dir"),
            "main_file": static_map.get("main_file"),
            "suggested_command": static_map.get("suggested_command"),
        },
        "execution": {
            "command": execution_result["command"],
            "success": execution_result["success"],
            "exit_code": execution_result["exit_code"],
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
        },
        "repair_agent": {
            "agent": safe_value(repair_data.get("agent") if repair_data else None),
            "mode": safe_value(repair_data.get("mode") if repair_data else None),
            "risk_level": safe_value(repair_data.get("risk_level") if repair_data else None),
            "auto_apply": safe_value(repair_data.get("auto_apply") if repair_data else None),
            "summary": safe_value(repair_data.get("summary") if repair_data else None),
            "suggestions": format_list(repair_data.get("suggestions") if repair_data else []),
            "next_action": safe_value(repair_data.get("next_action") if repair_data else None),
        },
        "evidence": {
            "stdout": stdout_text,
            "stderr": stderr_text,
        },
        "final_status": final_status,
        "generated_at": str(datetime.now()),
    }

    # write JSON
    json_report_path.write_text(json.dumps(json_content, indent=2), encoding="utf-8")

    # =========================
    # MARKDOWN (existing style)
    # =========================

    md_content = (
        "# Stitch QA Report\n\n"

        "## Project Summary\n\n"
        f"- Project Path: {scan_result['project_path']}\n"
        f"- Project Type: {scan_result['project_type']}\n"
        f"- Total Files: {scan_result['total_files']}\n"
        f"- Total Folders: {scan_result['total_folders']}\n"
        f"- Ignored Items: {scan_result['ignored_items']}\n\n"

        "## Static Mapping\n\n"
        f"- Build File: {static_map['build_file']}\n"
        f"- Main Source Directory: {static_map['main_source_dir']}\n"
        f"- Test Source Directory: {static_map['test_source_dir']}\n"
        f"- Main File: {static_map['main_file']}\n"
        f"- Suggested Command: {static_map['suggested_command']}\n\n"

        "## Execution Result\n\n"
        f"- Command: {execution_result['command']}\n"
        f"- Success: {execution_result['success']}\n"
        f"- Exit Code: {execution_result['exit_code']}\n\n"

        "## AI Log Analysis\n\n"
        f"{agent_data.get('summary') if agent_data else 'Not available'}\n\n"

        "## Repair Suggestions\n\n"
        f"{repair_data.get('summary') if repair_data else 'Not available'}\n\n"

        "## Final QA Status\n\n"
        f"{final_status}\n\n"

        "----------------------------------------\n"
        f"Generated At: {datetime.now()}\n"
    )

    md_report_path.write_text(md_content, encoding="utf-8")

    return md_report_path