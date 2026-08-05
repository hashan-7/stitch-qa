import re

from stitch_cli.runtime_contract import RUNTIME_EVIDENCE_SCHEMA_VERSION, empty_test_summary
from stitch_cli.test_report_parser import parse_junit_reports


ENVIRONMENT_FAILURES = {
    "MAVEN_NOT_AVAILABLE",
    "MAVEN_WRAPPER_NOT_AVAILABLE",
    "MAVEN_WRAPPER_NOT_EXECUTABLE",
    "PYTHON_NOT_AVAILABLE",
    "PYTEST_NOT_AVAILABLE",
    "INVALID_PROJECT_PATH",
    "COMMAND_PROFILE_NOT_ALLOWED",
}


def unique_strings(items):
    result = []
    seen = set()
    for item in items:
        value = str(item or "").strip()
        key = value.lower()
        if not value or key in seen:
            continue
        seen.add(key)
        result.append(value)
    return result


def framework_from_profile(command_profile):
    if command_profile == "PYTHON_PYTEST":
        return "pytest"
    if command_profile in {"MAVEN_SYSTEM", "MAVEN_WRAPPER"}:
        return "maven-surefire"
    return "unknown"


def extract_console_test_summary(stdout, stderr):
    logs = f"{stdout or ''}\n{stderr or ''}"
    summary = empty_test_summary()

    maven_matches = re.findall(
        r"Tests run:\s*(\d+),\s*Failures:\s*(\d+),\s*Errors:\s*(\d+),\s*Skipped:\s*(\d+)",
        logs,
        re.IGNORECASE,
    )
    if maven_matches:
        totals = [0, 0, 0, 0]
        for values in maven_matches:
            for index, value in enumerate(values):
                totals[index] += int(value)
        total, failed, errors, skipped = totals
        summary.update(
            {
                "total": total,
                "passed": max(total - failed - errors - skipped, 0),
                "failed": failed,
                "errors": errors,
                "skipped": skipped,
            }
        )

    pytest_matches = list(
        re.finditer(
            r"=+\s*(?P<body>[^=\n]+?)\s+in\s+(?P<duration>\d+(?:\.\d+)?)s\s*=+",
            logs,
            re.IGNORECASE,
        )
    )
    if pytest_matches:
        match = pytest_matches[-1]
        body = match.group("body")
        outcomes = {
            "passed": r"(\d+)\s+passed",
            "failed": r"(\d+)\s+failed",
            "skipped": r"(\d+)\s+skipped",
            "errors": r"(\d+)\s+errors?",
        }
        for key, pattern in outcomes.items():
            outcome = re.search(pattern, body, re.IGNORECASE)
            summary[key] = int(outcome.group(1)) if outcome else 0
        summary["total"] = sum(summary[key] for key in ("passed", "failed", "skipped", "errors"))
        summary["duration_seconds"] = float(match.group("duration"))

    return summary


def extract_console_failures(stdout, stderr):
    logs = f"{stdout or ''}\n{stderr or ''}"
    failures = []
    seen = set()

    for match in re.finditer(r"(?m)^FAILED\s+([^\s]+)", logs):
        test_name = match.group(1).strip()
        if test_name in seen:
            continue
        seen.add(test_name)
        failures.append(
            {
                "id": f"LOG-{len(failures) + 1:04d}",
                "status": "FAILED",
                "test_name": test_name,
                "test_file": test_name.split("::", 1)[0] if "::" in test_name else None,
                "test_line": None,
                "classname": None,
                "duration_seconds": None,
                "exception_type": None,
                "exception_message": None,
                "expected": None,
                "actual": None,
                "application_file": None,
                "application_line": None,
                "traceback_excerpt": None,
                "raw_failure": None,
            }
        )

    return failures


def extract_warnings(stdout, stderr):
    logs = f"{stdout or ''}\n{stderr or ''}"
    lower_logs = logs.lower()
    warnings = []

    if "warning" in lower_logs:
        warnings.append("Warnings were detected in the execution output.")
    if "mockito" in lower_logs and "dynamic loading of agents" in lower_logs:
        warnings.append(
            "Mockito dynamic Java agent loading was detected and may require future JDK configuration changes."
        )
    if "deprecated" in lower_logs:
        warnings.append("Deprecated runtime or build behavior was detected in the execution output.")

    return unique_strings(warnings)


def determine_execution_status(executed, skipped, failure_type, exit_code):
    if skipped:
        return "SKIPPED"
    if failure_type == "COMMAND_TIMEOUT":
        return "TIMED_OUT"
    if failure_type in ENVIRONMENT_FAILURES or exit_code is None:
        return "FAILED_TO_START"
    if executed:
        return "COMPLETED"
    return "UNKNOWN"


def determine_test_result(summary, success, failure_type, execution_status):
    if execution_status in {"FAILED_TO_START", "SKIPPED"}:
        return "NOT_RUN"
    if failure_type == "PYTHON_TESTS_NOT_FOUND":
        return "NOT_RUN"
    if summary["failed"] or summary["errors"]:
        return "FAIL"
    if summary["total"] and success:
        return "PASS"
    if success:
        return "INCONCLUSIVE"
    return "FAIL" if execution_status == "COMPLETED" else "INCONCLUSIVE"


def build_minimal_runtime_evidence(
    command,
    command_profile,
    success,
    exit_code,
    executed,
    skipped,
    failure_type,
    help_message,
    duration_seconds=None,
):
    execution_status = determine_execution_status(executed, skipped, failure_type, exit_code)
    return {
        "schema_version": RUNTIME_EVIDENCE_SCHEMA_VERSION,
        "framework": framework_from_profile(command_profile),
        "command": command,
        "execution_status": execution_status,
        "test_result": "NOT_RUN" if execution_status in {"FAILED_TO_START", "SKIPPED"} else "INCONCLUSIVE",
        "exit_code": exit_code,
        "duration_seconds": duration_seconds,
        "test_summary": empty_test_summary(duration_seconds),
        "failures": [],
        "failure_records_total": 0,
        "failure_records_submitted": 0,
        "evidence_truncated": False,
        "warnings": [],
        "report_files": [],
        "report_source": "NONE",
        "evidence_quality": "NONE",
        "collection_errors": [],
        "failure_type": failure_type,
        "help_message": help_message,
    }


def collect_runtime_evidence(
    project_root,
    command,
    command_profile,
    success,
    exit_code,
    stdout,
    stderr,
    duration_seconds,
    report_files,
    failure_type=None,
    help_message=None,
    executed=True,
    skipped=False,
):
    framework = framework_from_profile(command_profile)

    if report_files:
        evidence = parse_junit_reports(
            report_files=report_files,
            project_root=project_root,
            framework=framework,
            command=command,
            exit_code=exit_code,
            duration_seconds=duration_seconds,
            failure_type=failure_type,
            help_message=help_message,
        )
        evidence["warnings"] = extract_warnings(stdout, stderr)
        if evidence["test_result"] == "INCONCLUSIVE":
            console_summary = extract_console_test_summary(stdout, stderr)
            if console_summary["total"]:
                evidence["test_summary"] = console_summary
                evidence["test_result"] = determine_test_result(
                    console_summary,
                    success,
                    failure_type,
                    evidence["execution_status"],
                )
        return evidence

    summary = extract_console_test_summary(stdout, stderr)
    execution_status = determine_execution_status(executed, skipped, failure_type, exit_code)
    failures = extract_console_failures(stdout, stderr)
    return {
        "schema_version": RUNTIME_EVIDENCE_SCHEMA_VERSION,
        "framework": framework,
        "command": command,
        "execution_status": execution_status,
        "test_result": determine_test_result(summary, success, failure_type, execution_status),
        "exit_code": exit_code,
        "duration_seconds": duration_seconds,
        "test_summary": summary,
        "failures": failures,
        "failure_records_total": len(failures),
        "failure_records_submitted": len(failures),
        "evidence_truncated": False,
        "warnings": extract_warnings(stdout, stderr),
        "report_files": [],
        "report_source": "CONSOLE_FALLBACK" if summary["total"] or failures else "NONE",
        "evidence_quality": "LOG_ONLY" if summary["total"] or failures else "NONE",
        "collection_errors": [],
        "failure_type": failure_type,
        "help_message": help_message,
    }
