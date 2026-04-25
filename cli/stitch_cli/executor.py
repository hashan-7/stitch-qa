import subprocess
from pathlib import Path


def execute_command(project_path, command, timeout_seconds=120):
    if not command:
        return {
            "success": False,
            "exit_code": None,
            "stdout": "",
            "stderr": "No command provided for execution.",
            "command": command,
        }

    working_dir = Path(project_path).resolve()

    try:
        completed_process = subprocess.run(
            command,
            cwd=working_dir,
            shell=True,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
        )

        return {
            "success": completed_process.returncode == 0,
            "exit_code": completed_process.returncode,
            "stdout": completed_process.stdout,
            "stderr": completed_process.stderr,
            "command": command,
        }

    except subprocess.TimeoutExpired:
        return {
            "success": False,
            "exit_code": None,
            "stdout": "",
            "stderr": f"Command timed out after {timeout_seconds} seconds.",
            "command": command,
        }

    except Exception as error:
        return {
            "success": False,
            "exit_code": None,
            "stdout": "",
            "stderr": str(error),
            "command": command,
        }