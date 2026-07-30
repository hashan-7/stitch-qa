from pathlib import Path
import requests
from stitch_cli.code_cli import call_code_agent, call_source_review_agent

DEFAULT_AGENT_TIMEOUT_SECONDS = 120
MAX_CODE_SNIPPET_CHARS = 8000
MAX_ERROR_LOG_CHARS = 12000
MAX_SOURCE_REVIEW_FILES = 100
MAX_SOURCE_FILE_CHARS = 50000
MAX_SOURCE_REVIEW_CHARS = 300000


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


def resolve_project_file(project_path, relative_file_path):
    if not relative_file_path:
        return None

    project_root = Path(project_path).resolve()
    absolute_path = (project_root / relative_file_path).resolve()

    try:
        absolute_path.relative_to(project_root)
    except ValueError:
        return None

    if not absolute_path.is_file():
        return None

    return absolute_path


def read_project_file(project_path, relative_file_path):
    try:
        absolute_path = resolve_project_file(project_path, relative_file_path)

        if absolute_path is None:
            return None

        content = absolute_path.read_text(encoding="utf-8", errors="ignore")

        if len(content) > MAX_CODE_SNIPPET_CHARS:
            return content[-MAX_CODE_SNIPPET_CHARS:]

        return content

    except OSError:
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


def build_source_review_payload(scan_result):
    source_review = scan_result.get("source_review", {})
    project_path = scan_result["project_path"]
    source_files = source_review.get("source_files", [])
    submitted_files = []
    omitted_files = []
    read_errors = []
    submitted_chars = 0
    truncated_files_count = 0

    for relative_path in source_files:
        if len(submitted_files) >= MAX_SOURCE_REVIEW_FILES:
            omitted_files.append(relative_path)
            continue

        absolute_path = resolve_project_file(project_path, relative_path)

        if absolute_path is None:
            read_errors.append(relative_path)
            continue

        try:
            content = absolute_path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            read_errors.append(relative_path)
            continue

        original_chars = len(content)
        truncated = original_chars > MAX_SOURCE_FILE_CHARS

        if truncated:
            content = content[:MAX_SOURCE_FILE_CHARS]

        remaining_chars = MAX_SOURCE_REVIEW_CHARS - submitted_chars

        if remaining_chars <= 0:
            omitted_files.append(relative_path)
            continue

        if len(content) > remaining_chars:
            if remaining_chars < 1000:
                omitted_files.append(relative_path)
                continue

            content = content[:remaining_chars]
            truncated = True

        if truncated:
            truncated_files_count += 1

        submitted_files.append(
            {
                "path": relative_path,
                "content": content,
                "truncated": truncated,
                "original_chars": original_chars,
            }
        )
        submitted_chars += len(content)

    static_map = scan_result.get("static_map", {})

    payload = {
        "project_type": scan_result["project_type"],
        "has_tests": bool(static_map.get("has_tests")),
        "files": submitted_files,
        "discovered_files_count": int(source_review.get("source_files_count", 0)),
        "submitted_files_count": len(submitted_files),
        "submitted_chars": submitted_chars,
        "truncated_files_count": truncated_files_count,
        "omitted_files_count": len(omitted_files),
        "read_error_files_count": len(read_errors),
    }

    collection = {
        "discovered_files_count": int(source_review.get("source_files_count", 0)),
        "submitted_files_count": len(submitted_files),
        "submitted_chars": submitted_chars,
        "truncated_files_count": truncated_files_count,
        "omitted_files_count": len(omitted_files),
        "read_error_files_count": len(read_errors),
        "omitted_files": omitted_files,
        "read_error_files": read_errors,
    }

    return payload, collection


def build_local_no_source_review(scan_result, collection):
    source_review = scan_result.get("source_review", {})
    warning = source_review.get("warning") or "No reviewable source files were detected."

    return {
        "agent": "code-agent",
        "mode": "local-guard",
        "status": "NO_SOURCE_FILES",
        "summary": warning,
        "risk_level": "UNKNOWN",
        "release_recommendation": "QA_INCOMPLETE",
        "reviewed_files_count": 0,
        "findings_count": 0,
        "severity_summary": {
            "CRITICAL": 0,
            "HIGH": 0,
            "MEDIUM": 0,
            "LOW": 0,
            "INFO": 0,
        },
        "category_summary": {},
        "findings": [],
        "warnings": [warning],
        "limitations": ["Source-code QA review could not run because no eligible application source files were available."],
        "verification": "Confirm the project path and supported source files, then rerun Stitch QA.",
        "llm_error": None,
        "coverage": collection,
    }


def normalize_source_review_data(data, collection):
    normalized = dict(data)
    normalized["findings"] = data.get("findings") if isinstance(data.get("findings"), list) else []
    normalized["warnings"] = data.get("warnings") if isinstance(data.get("warnings"), list) else []
    normalized["limitations"] = data.get("limitations") if isinstance(data.get("limitations"), list) else []
    normalized["severity_summary"] = (
        data.get("severity_summary")
        if isinstance(data.get("severity_summary"), dict)
        else {}
    )
    normalized["category_summary"] = (
        data.get("category_summary")
        if isinstance(data.get("category_summary"), dict)
        else {}
    )
    normalized["reviewed_files_count"] = int(
        data.get("reviewed_files_count", collection["submitted_files_count"])
    )
    normalized["findings_count"] = int(
        data.get("findings_count", len(normalized["findings"]))
    )
    normalized["coverage"] = collection
    return normalized


def review_source_with_agent(code_agent_url, scan_result):
    payload, collection = build_source_review_payload(scan_result)

    if not payload["files"]:
        return {
            "success": True,
            "data": build_local_no_source_review(scan_result, collection),
            "error": None,
        }

    result = call_source_review_agent(payload, code_agent_url)

    if not result["success"]:
        return result

    data = result.get("data")

    if not isinstance(data, dict) or not data.get("status"):
        return {
            "success": False,
            "data": None,
            "error": "Code agent returned an invalid source-review response.",
        }

    return {
        "success": True,
        "data": normalize_source_review_data(data, collection),
        "error": None,
    }


def build_unavailable_source_review(scan_result, error):
    source_review = scan_result.get("source_review", {})
    return {
        "agent": "code-agent",
        "mode": "unavailable",
        "status": "UNAVAILABLE",
        "summary": "Source-code QA review could not be completed because Agent 3 was unavailable.",
        "risk_level": "UNKNOWN",
        "release_recommendation": "QA_INCOMPLETE",
        "reviewed_files_count": 0,
        "findings_count": 0,
        "severity_summary": {},
        "category_summary": {},
        "findings": [],
        "warnings": [str(error)],
        "limitations": ["No Agent 3 source-review result was available for this run."],
        "verification": "Check the Code Agent deployment and rerun Stitch QA.",
        "llm_error": None,
        "coverage": {
            "discovered_files_count": int(source_review.get("source_files_count", 0)),
            "submitted_files_count": 0,
            "submitted_chars": 0,
            "truncated_files_count": 0,
            "omitted_files_count": 0,
            "read_error_files_count": 0,
            "omitted_files": [],
            "read_error_files": [],
        },
    }


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
            f"{agent_url.rstrip('/')}/analyze",
            json=payload,
            timeout=DEFAULT_AGENT_TIMEOUT_SECONDS,
        )
        response.raise_for_status()
        return {
            "success": True,
            "data": response.json(),
            "error": None,
        }

    except (requests.exceptions.RequestException, ValueError) as error:
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
            f"{repair_agent_url.rstrip('/')}/suggest",
            json=payload,
            timeout=DEFAULT_AGENT_TIMEOUT_SECONDS,
        )
        response.raise_for_status()
        return {
            "success": True,
            "data": response.json(),
            "error": None,
        }

    except (requests.exceptions.RequestException, ValueError) as error:
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
    repair_data=None,
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

    return call_code_agent(payload, code_agent_url)
