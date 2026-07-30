import subprocess
from pathlib import Path


def classify_execution_failure(stderr_text, stdout_text=None, command=None):
    stderr_lower = (stderr_text or "").lower()
    stdout_lower = (stdout_text or "").lower()
    output_lower = f"{stdout_lower}\n{stderr_lower}"
    command_lower = (command or "").lower()

    if "mvn" in stderr_lower and "not recognized" in stderr_lower:
        return {
            "failure_type": "MAVEN_NOT_AVAILABLE",
            "help_message": (
                "Maven is not installed or not available in PATH. "
                "Install Apache Maven and add it to PATH, or add Maven Wrapper files "
                "(mvnw, mvnw.cmd, .mvn/wrapper) to this project."
            ),
        }

    if "mvnw.cmd" in stderr_lower and "not recognized" in stderr_lower:
        return {
            "failure_type": "MAVEN_WRAPPER_NOT_AVAILABLE",
            "help_message": (
                "Maven Wrapper command was selected, but mvnw.cmd was not found or could not run. "
                "Check that mvnw.cmd exists in the project root."
            ),
        }

    if (
        "python" in command_lower
        and (
            "python was not found" in output_lower
            or "python is not recognized" in output_lower
            or "python' is not recognized" in output_lower
            or "no python at" in output_lower
        )
    ):
        return {
            "failure_type": "PYTHON_NOT_AVAILABLE",
            "help_message": (
                "Python is not installed or not available in PATH. "
                "Install Python and add it to PATH, then rerun Stitch QA."
            ),
        }

    if (
        "pytest" in command_lower
        and (
            "no module named pytest" in output_lower
            or "pytest: command not found" in output_lower
            or "pytest is not recognized" in output_lower
            or "pytest' is not recognized" in output_lower
        )
    ):
        return {
            "failure_type": "PYTEST_NOT_AVAILABLE",
            "help_message": (
                "pytest is not installed in the active Python environment. "
                "Install pytest with `python -m pip install pytest`, or add it to the project dependencies."
            ),
        }

    if (
        "pytest" in command_lower
        and (
            "collected 0 items" in output_lower
            or "no tests ran" in output_lower
            or "no tests collected" in output_lower
        )
    ):
        return {
            "failure_type": "PYTHON_TESTS_NOT_FOUND",
            "help_message": (
                "pytest ran but did not find any tests. "
                "Add Python tests in a tests folder or files named test_*.py or *_test.py."
            ),
        }

    if "command timed out" in output_lower:
        return {
            "failure_type": "COMMAND_TIMEOUT",
            "help_message": (
                "The command took too long to finish. Increase the timeout or check whether the build is stuck."
            ),
        }

    return {
        "failure_type": None,
        "help_message": None,
    }


def build_stderr_with_help(stderr_text, failure_info):
    help_message = failure_info.get("help_message")

    if not help_message:
        return stderr_text

    if stderr_text:
        return f"{stderr_text}\n\nStitch QA Help: {help_message}"

    return f"Stitch QA Help: {help_message}"


def build_result(
    success,
    exit_code,
    stdout,
    stderr,
    command,
    executed=True,
    skipped=False,
    skip_reason=None,
):
    if skipped:
        failure_info = {
            "failure_type": None,
            "help_message": None,
        }
        enhanced_stderr = stderr
        status = "SKIPPED"
    else:
        failure_info = classify_execution_failure(stderr, stdout, command)
        enhanced_stderr = build_stderr_with_help(stderr, failure_info)
        status = "PASSED" if success else "FAILED"

    return {
        "status": status,
        "executed": executed,
        "skipped": skipped,
        "skip_reason": skip_reason,
        "success": success,
        "exit_code": exit_code,
        "stdout": stdout,
        "stderr": enhanced_stderr,
        "command": command,
        "failure_type": failure_info.get("failure_type"),
        "help_message": failure_info.get("help_message"),
    }


def build_skipped_result(command, skip_reason):
    return build_result(
        success=True,
        exit_code=0,
        stdout="",
        stderr="",
        command=command,
        executed=False,
        skipped=True,
        skip_reason=skip_reason,
    )


def execute_command(project_path, command, timeout_seconds=120):
    if not command:
        return build_result(
            success=False,
            exit_code=None,
            stdout="",
            stderr="No command provided for execution.",
            command=command,
        )

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

        return build_result(
            success=completed_process.returncode == 0,
            exit_code=completed_process.returncode,
            stdout=completed_process.stdout,
            stderr=completed_process.stderr,
            command=command,
        )

    except subprocess.TimeoutExpired as error:
        stdout_text = error.stdout or ""
        stderr_text = error.stderr or ""

        if isinstance(stdout_text, bytes):
            stdout_text = stdout_text.decode(errors="replace")

        if isinstance(stderr_text, bytes):
            stderr_text = stderr_text.decode(errors="replace")

        timeout_message = f"Command timed out after {timeout_seconds} seconds."
        stderr_text = f"{stderr_text}\n{timeout_message}".strip()

        return build_result(
            success=False,
            exit_code=None,
            stdout=stdout_text,
            stderr=stderr_text,
            command=command,
        )

    except Exception as error:
        return build_result(
            success=False,
            exit_code=None,
            stdout="",
            stderr=str(error),
            command=command,
        )
