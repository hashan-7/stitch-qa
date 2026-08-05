import os
import platform
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from stitch_cli.runtime_evidence import build_minimal_runtime_evidence, collect_runtime_evidence
from stitch_cli.test_report_parser import discover_maven_report_files

EXECUTION_POLICY = "BUILT_IN_ONLY"
EXECUTION_STRATEGY = "ARGUMENT_LIST"
SUPPORTED_EXECUTION_PROFILES = {
    "PYTHON_PYTEST",
    "MAVEN_SYSTEM",
    "MAVEN_WRAPPER",
}


def command_to_text(command):
    if not command:
        return ""

    if isinstance(command, (list, tuple)):
        return " ".join(str(item) for item in command)

    return str(command)


def classify_execution_failure(stderr_text, stdout_text=None, command=None):
    stderr_lower = (stderr_text or "").lower()
    stdout_lower = (stdout_text or "").lower()
    output_lower = f"{stdout_lower}\n{stderr_lower}"
    command_lower = command_to_text(command).lower()

    if (
        "mvnw.cmd" in command_lower
        and (
            "not recognized" in output_lower
            or "cannot find" in output_lower
            or "no such file" in output_lower
        )
    ):
        return {
            "failure_type": "MAVEN_WRAPPER_NOT_AVAILABLE",
            "help_message": (
                "The Maven Wrapper command was selected, but mvnw.cmd was not found or could not run. "
                "Check that mvnw.cmd exists in the project root."
            ),
        }

    if (
        "mvnw" in command_lower
        and (
            "permission denied" in output_lower
            or "not executable" in output_lower
        )
    ):
        return {
            "failure_type": "MAVEN_WRAPPER_NOT_EXECUTABLE",
            "help_message": (
                "The Maven Wrapper exists but is not executable. "
                "Run `chmod +x mvnw` and rerun Stitch QA."
            ),
        }

    if (
        "mvnw" in command_lower
        and (
            "not found" in output_lower
            or "no such file" in output_lower
            or "cannot find" in output_lower
        )
    ):
        return {
            "failure_type": "MAVEN_WRAPPER_NOT_AVAILABLE",
            "help_message": (
                "The Maven Wrapper command was selected, but the wrapper file was not found or could not run. "
                "Check that the correct mvnw or mvnw.cmd file exists in the project root."
            ),
        }

    if (
        "mvn" in command_lower
        and (
            "not recognized" in output_lower
            or "command not found" in output_lower
            or "no such file" in output_lower
            or "cannot find" in output_lower
        )
    ):
        return {
            "failure_type": "MAVEN_NOT_AVAILABLE",
            "help_message": (
                "Maven is not installed or not available in PATH. "
                "Install Apache Maven and add it to PATH, or add Maven Wrapper files "
                "(mvnw, mvnw.cmd, .mvn/wrapper) to this project."
            ),
        }

    if (
        "python" in command_lower
        and (
            "python was not found" in output_lower
            or "python is not recognized" in output_lower
            or "python' is not recognized" in output_lower
            or "no python at" in output_lower
            or "no such file" in output_lower
            or "cannot find" in output_lower
        )
    ):
        return {
            "failure_type": "PYTHON_NOT_AVAILABLE",
            "help_message": (
                "Python is not available to the Stitch QA process. "
                "Run Stitch QA from a valid Python environment and retry."
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
                "The command took too long to finish. "
                "Review the build for hangs or long-running operations before increasing the timeout."
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
    command_profile=None,
    command_args=None,
    executable=None,
    validation_status="VALIDATED",
    validation_error=None,
    timeout_seconds=None,
    failure_type=None,
    help_message=None,
    project_path=None,
    duration_seconds=None,
    runtime_evidence=None,
):
    if skipped:
        failure_info = {
            "failure_type": None,
            "help_message": None,
        }
        enhanced_stderr = stderr
        status = "SKIPPED"
    elif failure_type or help_message:
        failure_info = {
            "failure_type": failure_type,
            "help_message": help_message,
        }
        enhanced_stderr = build_stderr_with_help(stderr, failure_info)
        status = "PASSED" if success else "FAILED"
    else:
        failure_info = classify_execution_failure(stderr, stdout, command_args or command)
        enhanced_stderr = build_stderr_with_help(stderr, failure_info)
        status = "PASSED" if success else "FAILED"

    if runtime_evidence is None:
        runtime_evidence = build_minimal_runtime_evidence(
            command=command,
            command_profile=command_profile,
            success=success,
            exit_code=exit_code,
            executed=executed,
            skipped=skipped,
            failure_type=failure_info.get("failure_type"),
            help_message=failure_info.get("help_message"),
            duration_seconds=duration_seconds,
        )

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
        "command_profile": command_profile,
        "execution_policy": EXECUTION_POLICY,
        "execution_strategy": EXECUTION_STRATEGY,
        "shell_enabled": False,
        "command_args": list(command_args or []),
        "executable": executable,
        "validation_status": validation_status,
        "validation_error": validation_error,
        "timeout_seconds": timeout_seconds,
        "duration_seconds": duration_seconds,
        "project_path": str(project_path) if project_path else None,
        "failure_type": failure_info.get("failure_type"),
        "help_message": failure_info.get("help_message"),
        "runtime_evidence": runtime_evidence,
        "execution_status": runtime_evidence.get("execution_status"),
        "test_result": runtime_evidence.get("test_result"),
    }

def build_skipped_result(command, skip_reason, command_profile=None):
    validation_status = "PROFILE_VALIDATED_NOT_EXECUTED" if command_profile else "NOT_AVAILABLE"
    validation_error = None if command_profile else "No built-in execution profile was available."

    return build_result(
        success=True,
        exit_code=0,
        stdout="",
        stderr="",
        command=command,
        executed=False,
        skipped=True,
        skip_reason=skip_reason,
        command_profile=command_profile,
        validation_status=validation_status,
        validation_error=validation_error,
    )


def build_rejected_result(command, command_profile, validation_error):
    return build_result(
        success=False,
        executed=False,
        exit_code=None,
        stdout="",
        stderr=validation_error,
        command=command,
        command_profile=command_profile,
        validation_status="REJECTED",
        validation_error=validation_error,
        failure_type="COMMAND_PROFILE_NOT_ALLOWED",
        help_message=(
            "Stitch QA only executes built-in validated command profiles. "
            "Custom or unrecognized commands are not allowed."
        ),
    )


def resolve_python_plan():
    executable = sys.executable

    if not executable:
        return {
            "success": False,
            "failure_type": "PYTHON_NOT_AVAILABLE",
            "help_message": (
                "The active Stitch QA process could not resolve its Python interpreter."
            ),
        }

    executable_path = Path(executable).resolve()

    if not executable_path.is_file():
        return {
            "success": False,
            "failure_type": "PYTHON_NOT_AVAILABLE",
            "help_message": (
                "The active Stitch QA Python interpreter path is not available."
            ),
        }

    return {
        "success": True,
        "command": "python -m pytest",
        "command_args": [str(executable_path), "-m", "pytest"],
        "executable": str(executable_path),
    }


def resolve_maven_system_plan():
    executable = shutil.which("mvn")

    if not executable:
        return {
            "success": False,
            "failure_type": "MAVEN_NOT_AVAILABLE",
            "help_message": (
                "Maven is not installed or not available in PATH. "
                "Install Apache Maven and add it to PATH, or add Maven Wrapper files "
                "(mvnw, mvnw.cmd, .mvn/wrapper) to this project."
            ),
        }

    executable_path = Path(executable).resolve()

    return {
        "success": True,
        "command": "mvn test",
        "command_args": [str(executable_path), "test"],
        "executable": str(executable_path),
    }


def resolve_maven_wrapper_plan(project_path):
    current_os = platform.system()

    if current_os == "Windows":
        wrapper_path = (project_path / "mvnw.cmd").resolve()
        command = ".\\mvnw.cmd test"
    else:
        wrapper_path = (project_path / "mvnw").resolve()
        command = "./mvnw test"

    try:
        wrapper_path.relative_to(project_path)
    except ValueError:
        return {
            "success": False,
            "failure_type": "MAVEN_WRAPPER_NOT_AVAILABLE",
            "help_message": "The resolved Maven Wrapper path is outside the project directory.",
        }

    if not wrapper_path.is_file():
        return {
            "success": False,
            "failure_type": "MAVEN_WRAPPER_NOT_AVAILABLE",
            "help_message": (
                f"The required Maven Wrapper file for {current_os} was not found in the project root."
            ),
        }

    if current_os != "Windows" and not os.access(wrapper_path, os.X_OK):
        return {
            "success": False,
            "failure_type": "MAVEN_WRAPPER_NOT_EXECUTABLE",
            "help_message": (
                "The Maven Wrapper exists but is not executable. "
                "Run `chmod +x mvnw` and rerun Stitch QA."
            ),
        }

    return {
        "success": True,
        "command": command,
        "command_args": [str(wrapper_path), "test"],
        "executable": str(wrapper_path),
    }


def resolve_execution_plan(project_path, command_profile):
    if command_profile not in SUPPORTED_EXECUTION_PROFILES:
        return {
            "success": False,
            "failure_type": "COMMAND_PROFILE_NOT_ALLOWED",
            "help_message": (
                "Stitch QA only executes built-in validated command profiles. "
                "Custom or unrecognized commands are not allowed."
            ),
        }

    if command_profile == "PYTHON_PYTEST":
        return resolve_python_plan()

    if command_profile == "MAVEN_SYSTEM":
        return resolve_maven_system_plan()

    return resolve_maven_wrapper_plan(project_path)


def execute_command(
    project_path,
    command_profile,
    display_command=None,
    timeout_seconds=120,
):
    working_dir = Path(project_path).resolve()

    if not working_dir.exists():
        return build_result(
            success=False,
            exit_code=None,
            stdout="",
            stderr=f"Project path does not exist: {working_dir}",
            executed=False,
            command=display_command,
            command_profile=command_profile,
            validation_status="REJECTED",
            validation_error="Project path does not exist.",
            timeout_seconds=timeout_seconds,
            failure_type="INVALID_PROJECT_PATH",
            help_message="Provide an existing project directory and rerun Stitch QA.",
            project_path=working_dir,
        )

    if not working_dir.is_dir():
        return build_result(
            success=False,
            exit_code=None,
            stdout="",
            stderr=f"Project path is not a directory: {working_dir}",
            executed=False,
            command=display_command,
            command_profile=command_profile,
            validation_status="REJECTED",
            validation_error="Project path is not a directory.",
            timeout_seconds=timeout_seconds,
            failure_type="INVALID_PROJECT_PATH",
            help_message="Provide a project directory and rerun Stitch QA.",
            project_path=working_dir,
        )

    if command_profile not in SUPPORTED_EXECUTION_PROFILES:
        return build_rejected_result(
            display_command,
            command_profile,
            "The requested execution profile is not in the Stitch QA allowlist.",
        )

    execution_plan = resolve_execution_plan(working_dir, command_profile)

    if not execution_plan.get("success"):
        failure_type = execution_plan.get("failure_type")
        help_message = execution_plan.get("help_message")
        return build_result(
            success=False,
            exit_code=None,
            stdout="",
            stderr=help_message or "Unable to resolve the built-in execution command.",
            executed=False,
            command=display_command,
            command_profile=command_profile,
            validation_status="VALIDATED",
            validation_error=None,
            timeout_seconds=timeout_seconds,
            failure_type=failure_type,
            help_message=help_message,
            project_path=working_dir,
        )

    command = display_command or execution_plan["command"]
    base_command_args = list(execution_plan["command_args"])
    executable = execution_plan["executable"]

    with tempfile.TemporaryDirectory(prefix="stitch-qa-runtime-") as artifact_dir:
        artifact_path = Path(artifact_dir)
        command_args = list(base_command_args)
        pytest_report = artifact_path / "pytest-junit.xml"

        if command_profile == "PYTHON_PYTEST":
            command_args.append(f"--junitxml={pytest_report}")

        started_at_epoch = time.time()
        started_at_monotonic = time.monotonic()

        try:
            completed_process = subprocess.run(
                command_args,
                cwd=working_dir,
                shell=False,
                capture_output=True,
                text=True,
                timeout=timeout_seconds,
            )
            duration_seconds = round(time.monotonic() - started_at_monotonic, 6)
            failure_info = classify_execution_failure(
                completed_process.stderr,
                completed_process.stdout,
                command_args,
            )
            report_files = []

            if pytest_report.is_file():
                report_files.append(pytest_report)
            elif command_profile in {"MAVEN_SYSTEM", "MAVEN_WRAPPER"}:
                report_files.extend(
                    discover_maven_report_files(working_dir, started_at_epoch)
                )

            runtime_evidence = collect_runtime_evidence(
                project_root=working_dir,
                command=command,
                command_profile=command_profile,
                success=completed_process.returncode == 0,
                exit_code=completed_process.returncode,
                stdout=completed_process.stdout,
                stderr=completed_process.stderr,
                duration_seconds=duration_seconds,
                report_files=report_files,
                failure_type=failure_info.get("failure_type"),
                help_message=failure_info.get("help_message"),
                executed=True,
                skipped=False,
            )

            return build_result(
                success=completed_process.returncode == 0,
                exit_code=completed_process.returncode,
                stdout=completed_process.stdout,
                stderr=completed_process.stderr,
                command=command,
                command_profile=command_profile,
                command_args=command_args,
                executable=executable,
                validation_status="VALIDATED",
                timeout_seconds=timeout_seconds,
                failure_type=failure_info.get("failure_type"),
                help_message=failure_info.get("help_message"),
                project_path=working_dir,
                duration_seconds=duration_seconds,
                runtime_evidence=runtime_evidence,
            )

        except subprocess.TimeoutExpired as error:
            duration_seconds = round(time.monotonic() - started_at_monotonic, 6)
            stdout_text = error.stdout or ""
            stderr_text = error.stderr or ""

            if isinstance(stdout_text, bytes):
                stdout_text = stdout_text.decode(errors="replace")

            if isinstance(stderr_text, bytes):
                stderr_text = stderr_text.decode(errors="replace")

            timeout_message = f"Command timed out after {timeout_seconds} seconds."
            stderr_text = f"{stderr_text}\n{timeout_message}".strip()
            help_message = (
                "The command took too long to finish. Review the build for hangs or "
                "long-running operations before increasing the timeout."
            )
            runtime_evidence = collect_runtime_evidence(
                project_root=working_dir,
                command=command,
                command_profile=command_profile,
                success=False,
                exit_code=None,
                stdout=stdout_text,
                stderr=stderr_text,
                duration_seconds=duration_seconds,
                report_files=[],
                failure_type="COMMAND_TIMEOUT",
                help_message=help_message,
                executed=True,
                skipped=False,
            )

            return build_result(
                success=False,
                exit_code=None,
                stdout=stdout_text,
                stderr=stderr_text,
                command=command,
                command_profile=command_profile,
                command_args=command_args,
                executable=executable,
                validation_status="VALIDATED",
                timeout_seconds=timeout_seconds,
                failure_type="COMMAND_TIMEOUT",
                help_message=help_message,
                project_path=working_dir,
                duration_seconds=duration_seconds,
                runtime_evidence=runtime_evidence,
            )

        except OSError as error:
            duration_seconds = round(time.monotonic() - started_at_monotonic, 6)
            runtime_evidence = collect_runtime_evidence(
                project_root=working_dir,
                command=command,
                command_profile=command_profile,
                success=False,
                exit_code=None,
                stdout="",
                stderr=str(error),
                duration_seconds=duration_seconds,
                report_files=[],
                failure_type="EXECUTION_OS_ERROR",
                help_message="The validated command could not be started by the operating system.",
                executed=False,
                skipped=False,
            )
            return build_result(
                success=False,
                exit_code=None,
                stdout="",
                stderr=str(error),
                command=command,
                executed=False,
                command_profile=command_profile,
                command_args=command_args,
                executable=executable,
                validation_status="VALIDATED",
                timeout_seconds=timeout_seconds,
                failure_type="EXECUTION_OS_ERROR",
                help_message="The validated command could not be started by the operating system.",
                project_path=working_dir,
                duration_seconds=duration_seconds,
                runtime_evidence=runtime_evidence,
            )

        except Exception as error:
            duration_seconds = round(time.monotonic() - started_at_monotonic, 6)
            runtime_evidence = collect_runtime_evidence(
                project_root=working_dir,
                command=command,
                command_profile=command_profile,
                success=False,
                exit_code=None,
                stdout="",
                stderr=str(error),
                duration_seconds=duration_seconds,
                report_files=[],
                failure_type="EXECUTION_ERROR",
                help_message="The validated test command could not be completed.",
                executed=False,
                skipped=False,
            )
            return build_result(
                success=False,
                exit_code=None,
                stdout="",
                stderr=str(error),
                command=command,
                executed=False,
                command_profile=command_profile,
                command_args=command_args,
                executable=executable,
                validation_status="VALIDATED",
                timeout_seconds=timeout_seconds,
                failure_type="EXECUTION_ERROR",
                help_message="The validated test command could not be completed.",
                project_path=working_dir,
                duration_seconds=duration_seconds,
                runtime_evidence=runtime_evidence,
            )
