from pathlib import Path
from datetime import datetime


def generate_report(scan_result, execution_result, agent_data=None, repair_data=None):
    project_path = Path(scan_result["project_path"])
    report_path = project_path / "STITCH_QA_REPORT.md"

    static_map = scan_result["static_map"]

    final_status = "PASS" if execution_result["success"] else "FAIL"

    stdout_text = execution_result["stdout"][-2000:] if execution_result["stdout"] else "No stdout output."
    stderr_text = execution_result["stderr"][-2000:] if execution_result["stderr"] else "No stderr output."

    ai_section = ""

    if agent_data:
        issues = "\n".join(f"- {i}" for i in agent_data.get("issues", []))
        warnings = "\n".join(f"- {w}" for w in agent_data.get("warnings", []))

        ai_section = (
            "\n## AI Log Analysis\n\n"
            f"Agent: {agent_data.get('agent')}\n\n"
            f"Final Status: {agent_data.get('final_status')}\n\n"
            f"Summary: {agent_data.get('summary')}\n\n"
            f"Root Cause: {agent_data.get('root_cause')}\n\n"
            f"Recommendation: {agent_data.get('recommendation')}\n\n"
            "### Issues\n"
            f"{issues or 'None'}\n\n"
            "### Warnings\n"
            f"{warnings or 'None'}\n\n"
        )

    repair_section = ""

    if repair_data:
        suggestions = "\n".join(f"- {s}" for s in repair_data.get("suggestions", []))

        repair_section = (
            "\n## Repair Agent Suggestions\n\n"
            f"Agent: {repair_data.get('agent')}\n\n"
            f"Risk Level: {repair_data.get('risk_level')}\n\n"
            f"Auto Apply: {repair_data.get('auto_apply')}\n\n"
            f"Summary: {repair_data.get('summary')}\n\n"
            f"Next Action: {repair_data.get('next_action')}\n\n"
            "### Suggestions\n"
            f"{suggestions or 'None'}\n\n"
        )

    content = (
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

        "## STDOUT Summary\n\n"
        "----------------------------------------\n"
        f"{stdout_text}\n"
        "----------------------------------------\n\n"

        "## STDERR / Warnings\n\n"
        "----------------------------------------\n"
        f"{stderr_text}\n"
        "----------------------------------------\n\n"

        + ai_section
        + repair_section +

        "## Final QA Status\n\n"
        f"{final_status}\n\n"

        "----------------------------------------\n"
        f"Generated At: {datetime.now()}\n"
    )

    report_path.write_text(content, encoding="utf-8")

    return report_path