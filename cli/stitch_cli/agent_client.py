from pathlib import Path
import requests


DEFAULT_AGENT_TIMEOUT_SECONDS = 120
MAX_CODE_SNIPPET_CHARS = 8000
MAX_ERROR_LOG_CHARS = 12000


def get_failure_context(execution_result):
    return {
        "failure_type": execution_result.get("failure_type"),
        "help_message": execution_result.get("help_message"),
    }


def get_root_cause(agent_data, execution_result):
    if agent_data and agent_data.get("root_cause"):
        return agent_data.get("root_cause")

    if execution_result.get("help_message"):
        return execution_result.get("help_message")

    return None


def read_project_file(project_path, relative_file_path):
    if not relative_file_path:
        return None

    try:
        absolute_path = Path(project_path).resolve() / relative_file_path

        if not absolute_path.exists() or not absolute_path.is_file():
            return None

        content = absolute_path.read_text(encoding="utf-8", errors="ignore")

        if len(content) > MAX_CODE_SNIPPET_CHARS:
            return content[-MAX_CODE_SNIPPET_CHARS:]

        return content

    except Exception:
        return None


def build_error_log(execution_result):
    stdout = execution_result.get("stdout") or ""
    stderr = execution_result.get("stderr") or ""

    combined_log = (
        "STDOUT:\n"
        f"{stdout}\n\n"
        "STDERR:\n"
        f"{stderr}"
    )

    if len(combined_log) > MAX_ERROR_LOG_CHARS:
        return combined_log[-MAX_ERROR_LOG_CHARS:]

    return combined_log


def analyze_logs_with_agent(agent_url, scan_result, execution_result):
    failure_context = get_failure_context(execution_result)

    payload = {
        "project_type": scan_result["project_type"],
        "command": execution_result["command"],
        "success": execution_result["success"],
        "exit_code": execution_result["exit_code"],
        "stdout": execution_result["stdout"],
        "stderr": execution_result["stderr"],
        "failure_type": failure_context["failure_type"],
        "help_message": failure_context["help_message"],
    }

    try:
        response = requests.post(
            f"{agent_url}/analyze",
            json=payload,
            timeout=DEFAULT_AGENT_TIMEOUT_SECONDS,
        )
        response.raise_for_status()
        return {
            "success": True,
            "data": response.json(),
            "error": None,
        }

    except requests.exceptions.RequestException as error:
        return {
            "success": False,
            "data": None,
            "error": str(error),
        }


def suggest_repair_with_agent(repair_agent_url, scan_result, execution_result, agent_data=None):
    failure_context = get_failure_context(execution_result)

    payload = {
        "project_type": scan_result["project_type"],
        "command": execution_result["command"],
        "success": execution_result["success"],
        "exit_code": execution_result["exit_code"],
        "stdout": execution_result["stdout"],
        "stderr": execution_result["stderr"],
        "root_cause": get_root_cause(agent_data, execution_result),
        "failure_type": failure_context["failure_type"],
        "help_message": failure_context["help_message"],
    }

    try:
        response = requests.post(
            f"{repair_agent_url}/suggest",
            json=payload,
            timeout=DEFAULT_AGENT_TIMEOUT_SECONDS,
        )
        response.raise_for_status()
        return {
            "success": True,
            "data": response.json(),
            "error": None,
        }

    except requests.exceptions.RequestException as error:
        return {
            "success": False,
            "data": None,
            "error": str(error),
        }


def suggest_code_fix_with_agent(
    code_agent_url,
    scan_result,
    execution_result,
    agent_data=None,
    repair_data=None
):
    static_map = scan_result.get("static_map", {})
    failure_context = get_failure_context(execution_result)

    main_file = static_map.get("main_file")
    code_snippet = read_project_file(scan_result["project_path"], main_file)

    root_cause = get_root_cause(agent_data, execution_result)

    if not root_cause and failure_context["help_message"]:
        root_cause = failure_context["help_message"]

    repair_summary = repair_data.get("summary") if repair_data else None

    if not repair_summary and failure_context["help_message"]:
        repair_summary = failure_context["help_message"]

    payload = {
        "project_type": scan_result["project_type"],
        "file_path": main_file,
        "code_snippet": code_snippet,
        "error_log": build_error_log(execution_result),
        "root_cause": root_cause,
        "repair_summary": repair_summary,
        "failure_type": failure_context["failure_type"],
        "help_message": failure_context["help_message"],
        "success": execution_result["success"],
        "exit_code": execution_result["exit_code"],
    }

    try:
        response = requests.post(
            f"{code_agent_url}/suggest-code-fix",
            json=payload,
            timeout=DEFAULT_AGENT_TIMEOUT_SECONDS,
        )
        response.raise_for_status()
        return {
            "success": True,
            "data": response.json(),
            "error": None,
        }

    except requests.exceptions.RequestException as error:
        return {
            "success": False,
            "data": None,
            "error": str(error),
        }