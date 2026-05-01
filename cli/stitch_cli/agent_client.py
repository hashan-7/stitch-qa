import requests


DEFAULT_AGENT_TIMEOUT_SECONDS = 120


def analyze_logs_with_agent(agent_url, scan_result, execution_result):
    payload = {
        "project_type": scan_result["project_type"],
        "command": execution_result["command"],
        "success": execution_result["success"],
        "exit_code": execution_result["exit_code"],
        "stdout": execution_result["stdout"],
        "stderr": execution_result["stderr"],
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
    payload = {
        "project_type": scan_result["project_type"],
        "command": execution_result["command"],
        "success": execution_result["success"],
        "exit_code": execution_result["exit_code"],
        "stdout": execution_result["stdout"],
        "stderr": execution_result["stderr"],
        "root_cause": agent_data.get("root_cause") if agent_data else None,
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