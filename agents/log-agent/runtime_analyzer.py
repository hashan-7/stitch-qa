import re
from collections import defaultdict

from schemas import LogAnalysisRequest, RuntimeEvidence


AGENT_ID = "runtime-quality-analyst"
DISPLAY_NAME = "Runtime Quality Intelligence Analyst"
AGENT_VERSION = "2.0"

ENVIRONMENT_FAILURES = {
    "MAVEN_NOT_AVAILABLE",
    "MAVEN_WRAPPER_NOT_AVAILABLE",
    "MAVEN_WRAPPER_NOT_EXECUTABLE",
    "PYTHON_NOT_AVAILABLE",
    "PYTEST_NOT_AVAILABLE",
    "INVALID_PROJECT_PATH",
    "COMMAND_PROFILE_NOT_ALLOWED",
}

DISCOVERY_FAILURES = {
    "PYTHON_TESTS_NOT_FOUND",
}

TIMEOUT_FAILURES = {
    "COMMAND_TIMEOUT",
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


def extract_console_summary(logs):
    summary = {
        "total": 0,
        "passed": 0,
        "failed": 0,
        "skipped": 0,
        "errors": 0,
        "duration_seconds": None,
    }

    maven_match = re.search(
        r"Tests run:\s*(\d+),\s*Failures:\s*(\d+),\s*Errors:\s*(\d+),\s*Skipped:\s*(\d+)",
        logs,
        re.IGNORECASE,
    )

    if maven_match:
        total, failed, errors, skipped = [
            int(value)
            for value in maven_match.groups()
        ]
        summary.update(
            {
                "total": total,
                "passed": max(
                    total - failed - errors - skipped,
                    0,
                ),
                "failed": failed,
                "errors": errors,
                "skipped": skipped,
            }
        )

    pytest_match = re.search(
        r"=+\s*(?P<body>[^=\n]+?)\s+in\s+(?P<duration>\d+(?:\.\d+)?)s\s*=+",
        logs,
        re.IGNORECASE,
    )

    if pytest_match:
        body = pytest_match.group("body")
        outcomes = {
            "passed": r"(\d+)\s+passed",
            "failed": r"(\d+)\s+failed",
            "skipped": r"(\d+)\s+skipped",
            "errors": r"(\d+)\s+errors?",
        }

        for key, pattern in outcomes.items():
            match = re.search(
                pattern,
                body,
                re.IGNORECASE,
            )
            summary[key] = (
                int(match.group(1))
                if match
                else 0
            )

        summary["total"] = sum(
            summary[key]
            for key in (
                "passed",
                "failed",
                "skipped",
                "errors",
            )
        )
        summary["duration_seconds"] = float(
            pytest_match.group("duration")
        )

    return summary


def build_fallback_evidence(request):
    logs = f"{request.stdout}\n{request.stderr}"
    summary = extract_console_summary(logs)

    if request.failure_type in ENVIRONMENT_FAILURES:
        execution_status = "FAILED_TO_START"
        test_result = "NOT_RUN"
    elif request.failure_type in DISCOVERY_FAILURES:
        execution_status = "COMPLETED"
        test_result = "NOT_RUN"
    elif request.failure_type in TIMEOUT_FAILURES:
        execution_status = "TIMED_OUT"
        test_result = "INCONCLUSIVE"
    else:
        execution_status = (
            "COMPLETED"
            if request.exit_code is not None
            else "FAILED_TO_START"
        )

        if summary["failed"] or summary["errors"]:
            test_result = "FAIL"
        elif summary["total"] and request.success:
            test_result = "PASS"
        elif request.success:
            test_result = "INCONCLUSIVE"
        else:
            test_result = "FAIL"

    warnings = []
    lower_logs = logs.lower()

    if "warning" in lower_logs:
        warnings.append(
            "Warnings were detected in the execution output."
        )

    if (
        "mockito" in lower_logs
        and "dynamic loading of agents" in lower_logs
    ):
        warnings.append(
            "Mockito dynamic Java agent loading was detected and may require future JDK configuration changes."
        )

    return RuntimeEvidence.model_validate(
        {
            "framework": request.project_type,
            "command": request.command,
            "execution_status": execution_status,
            "test_result": test_result,
            "exit_code": request.exit_code,
            "test_summary": summary,
            "warnings": warnings,
            "report_source": "CONSOLE_FALLBACK",
            "evidence_quality": "LOG_ONLY",
            "failure_type": request.failure_type,
            "help_message": request.help_message,
        }
    )


def select_evidence(request):
    if request.runtime_evidence is None:
        return build_fallback_evidence(request)

    evidence = request.runtime_evidence.model_copy(
        deep=True
    )

    if evidence.failure_type is None:
        evidence.failure_type = request.failure_type

    if evidence.help_message is None:
        evidence.help_message = request.help_message

    if evidence.command is None:
        evidence.command = request.command

    if evidence.exit_code is None:
        evidence.exit_code = request.exit_code

    return evidence


def normalize_exception_type(value):
    text = str(
        value or "UnknownFailure"
    ).strip()

    return (
        text.rsplit(".", 1)[-1]
        if text
        else "UnknownFailure"
    )


def failure_category(failure):
    exception_type = normalize_exception_type(
        failure.exception_type
    ).lower()
    message = str(
        failure.exception_message or ""
    ).lower()

    if (
        "zero" in exception_type
        and "division" in exception_type
    ):
        return "INPUT_VALIDATION"

    if (
        "assert" in exception_type
        or failure.expected
        or failure.actual
    ):
        return "ASSERTION_FAILURE"

    if (
        "module" in exception_type
        or "import" in exception_type
    ):
        return "DEPENDENCY_FAILURE"

    if (
        "timeout" in exception_type
        or "timeout" in message
    ):
        return "TIMEOUT"

    if (
        "permission" in exception_type
        or "permission" in message
    ):
        return "PERMISSION_FAILURE"

    if (
        "connection" in exception_type
        or "network" in message
    ):
        return "NETWORK_FAILURE"

    return "RUNTIME_EXCEPTION"


def failure_signature(failure):
    normalized_message = re.sub(
        r"\b\d+\b",
        "#",
        str(
            failure.exception_message or ""
        ).strip().lower(),
    )

    return (
        failure_category(failure),
        normalize_exception_type(
            failure.exception_type
        ),
        str(failure.expected or "").strip(),
        str(failure.actual or "").strip(),
        normalized_message,
    )


def build_default_root_cause(failures, category):
    first = failures[0]
    exception_type = normalize_exception_type(
        first.exception_type
    )
    expected = first.expected
    actual = first.actual or exception_type
    location = first.application_file

    if location and first.application_line:
        location = (
            f"{location}:{first.application_line}"
        )

    if (
        category == "INPUT_VALIDATION"
        and exception_type == "ZeroDivisionError"
    ):
        return (
            "A division operation is reached without validating an input that can create a zero denominator. "
            "The uncontrolled ZeroDivisionError violates the behavior expected by the affected tests."
        )

    if expected and actual:
        location_text = (
            f" at {location}"
            if location
            else ""
        )
        return (
            f"The observed behavior{location_text} does not satisfy the tested contract. "
            f"The tests expected {expected}, but the runtime produced {actual}."
        )

    if category == "DEPENDENCY_FAILURE":
        return (
            "A required runtime dependency could not be loaded. "
            f"The primary observed exception was {exception_type}."
        )

    if category == "TIMEOUT":
        return (
            "The tested execution path did not complete within the configured time limit."
        )

    if category == "PERMISSION_FAILURE":
        return (
            "The tested execution path attempted an operation without the required permission."
        )

    if category == "NETWORK_FAILURE":
        return (
            "The tested execution path failed while performing a network-dependent operation."
        )

    return (
        f"The affected tests reached an uncontrolled {exception_type} runtime failure. "
        "The evidence identifies the failing execution path but may not prove the complete underlying defect."
    )


def build_default_impact(failures, category):
    affected_count = len(failures)

    if category == "INPUT_VALIDATION":
        return (
            f"Invalid boundary inputs can terminate {affected_count} tested execution path"
            f"{'s' if affected_count != 1 else ''} unexpectedly and violate the tested error-handling contract."
        )

    if category == "ASSERTION_FAILURE":
        return (
            f"The implementation conflicts with {affected_count} validated test expectation"
            f"{'s' if affected_count != 1 else ''}, creating tested-scope regression and release risk."
        )

    if category == "DEPENDENCY_FAILURE":
        return (
            "The application or test workflow cannot complete reliably until the dependency problem is resolved."
        )

    if category == "TIMEOUT":
        return (
            "The workflow may exceed CI limits, remain blocked, or produce an inconclusive runtime result."
        )

    if category == "PERMISSION_FAILURE":
        return (
            "The affected runtime path cannot complete under the observed permission configuration."
        )

    if category == "NETWORK_FAILURE":
        return (
            "The affected runtime path is unavailable or unreliable when the observed connection failure occurs."
        )

    return (
        "The affected tested runtime path fails before completing its expected behavior."
    )


def build_default_action(failures, category):
    first = failures[0]

    if category == "INPUT_VALIDATION":
        return (
            "Add explicit boundary validation before the failing operation, preserve the tested exception contract, "
            "then rerun the affected tests followed by the full test suite."
        )

    if first.expected and first.actual:
        return (
            "Correct the implementation or documented contract so the observed behavior matches the validated expectation, "
            "then rerun the affected tests followed by the full regression suite."
        )

    if category == "DEPENDENCY_FAILURE":
        return (
            "Restore the required dependency and rerun the affected tests followed by the full test suite."
        )

    if category == "TIMEOUT":
        return (
            "Investigate the long-running operation or hang, then rerun the affected test with a justified timeout."
        )

    if category == "PERMISSION_FAILURE":
        return (
            "Correct the runtime permission or configuration and rerun the affected tests."
        )

    if category == "NETWORK_FAILURE":
        return (
            "Validate the external dependency and its failure-handling path, then rerun the affected tests."
        )

    return (
        "Correct the confirmed failing runtime path and rerun the affected tests followed by the full regression suite."
    )


def evidence_location(failure):
    return {
        "failure_id": failure.id,
        "status": failure.status,
        "test_name": failure.test_name,
        "test_file": failure.test_file,
        "test_line": failure.test_line,
        "exception_type": failure.exception_type,
        "exception_message": failure.exception_message,
        "expected": failure.expected,
        "actual": failure.actual,
        "application_file": failure.application_file,
        "application_line": failure.application_line,
    }


def build_root_cause_groups(evidence):
    grouped = defaultdict(list)

    for item in evidence.failures:
        grouped[
            failure_signature(item)
        ].append(item)

    groups = []

    for index, failures in enumerate(
        grouped.values(),
        start=1,
    ):
        category = failure_category(
            failures[0]
        )
        count = len(failures)

        groups.append(
            {
                "group_id": f"RQI-{index:03d}",
                "title": (
                    f"{category.replace('_', ' ').title()} affecting "
                    f"{count} test{'s' if count != 1 else ''}"
                ),
                "category": category,
                "root_cause": build_default_root_cause(
                    failures,
                    category,
                ),
                "runtime_impact": build_default_impact(
                    failures,
                    category,
                ),
                "required_action": build_default_action(
                    failures,
                    category,
                ),
                "affected_tests": unique_strings(
                    item.test_name or item.id
                    for item in failures
                ),
                "evidence": [
                    evidence_location(item)
                    for item in failures
                ],
            }
        )

    return groups


def build_environment_group(evidence, request):
    failure_type = (
        evidence.failure_type
        or request.failure_type
        or "EXECUTION_ENVIRONMENT"
    )
    help_message = (
        evidence.help_message
        or request.help_message
    )

    mapping = {
        "MAVEN_NOT_AVAILABLE": (
            "Maven is not installed or is unavailable in PATH.",
            "The Maven test workflow did not start, so no runtime test result was established.",
            "Install Maven or provide a valid Maven Wrapper, then rerun Stitch QA.",
        ),
        "MAVEN_WRAPPER_NOT_AVAILABLE": (
            "The selected Maven Wrapper file is missing or unavailable.",
            "The Maven test workflow did not start, so runtime QA evidence is incomplete.",
            "Restore the correct Maven Wrapper files or use a valid Maven installation, then rerun Stitch QA.",
        ),
        "MAVEN_WRAPPER_NOT_EXECUTABLE": (
            "The Maven Wrapper exists but is not executable.",
            "The validated Maven test workflow could not start.",
            "Grant execute permission to the wrapper and rerun Stitch QA.",
        ),
        "PYTHON_NOT_AVAILABLE": (
            "The active Stitch QA process could not resolve a usable Python interpreter.",
            "The Python test workflow did not start, so runtime QA evidence is incomplete.",
            "Run Stitch QA from a valid Python environment and retry.",
        ),
        "PYTEST_NOT_AVAILABLE": (
            "pytest is not installed in the active Python environment.",
            "The Python test workflow did not start, so no runtime test result was established.",
            "Install the project test dependencies and rerun Stitch QA.",
        ),
        "PYTHON_TESTS_NOT_FOUND": (
            "pytest completed discovery without finding compatible tests.",
            "Runtime behavior was not verified because no automated tests were executed.",
            "Add or correctly configure compatible tests, then rerun Stitch QA.",
        ),
        "COMMAND_TIMEOUT": (
            "The validated execution command exceeded the configured timeout.",
            "The QA run ended before a conclusive runtime result was produced.",
            "Investigate the long-running operation or hang, then rerun the workflow.",
        ),
    }

    root_cause, impact, action = mapping.get(
        failure_type,
        (
            help_message
            or "The validated execution workflow could not produce conclusive runtime evidence.",
            "The current runtime QA evidence is incomplete and cannot establish tested-scope release confidence.",
            "Resolve the execution issue and rerun Stitch QA.",
        ),
    )

    return {
        "group_id": "RQI-001",
        "title": failure_type.replace(
            "_",
            " ",
        ).title(),
        "category": (
            "ENVIRONMENT"
            if failure_type in ENVIRONMENT_FAILURES
            else "EXECUTION"
        ),
        "root_cause": root_cause,
        "runtime_impact": impact,
        "required_action": action,
        "affected_tests": [],
        "evidence": [
            {
                "failure_type": failure_type,
                "help_message": help_message,
                "command": request.command,
                "exit_code": request.exit_code,
            }
        ],
    }


def determine_release_gate(evidence, request):
    failure_type = (
        evidence.failure_type
        or request.failure_type
    )

    if (
        failure_type in ENVIRONMENT_FAILURES
        or failure_type in DISCOVERY_FAILURES
    ):
        return "REVIEW_REQUIRED"

    if evidence.execution_status in {
        "FAILED_TO_START",
        "TIMED_OUT",
        "SKIPPED",
    }:
        return "REVIEW_REQUIRED"

    if evidence.test_result == "FAIL":
        return "BLOCK_RELEASE"

    if evidence.test_result in {
        "NOT_RUN",
        "INCONCLUSIVE",
    }:
        return "REVIEW_REQUIRED"

    if (
        evidence.warnings
        or evidence.collection_errors
    ):
        return "ALLOW_WITH_WARNINGS"

    return "ALLOW_RELEASE"


def determine_confidence(evidence, groups):
    if evidence.evidence_quality == "STRUCTURED":
        if (
            evidence.collection_errors
            or evidence.evidence_truncated
        ):
            return "MEDIUM"

        if evidence.test_result == "PASS":
            return "HIGH"

        if groups:
            evidence_items = [
                item
                for group in groups
                for item in group.get(
                    "evidence",
                    [],
                )
            ]
            mapped_items = [
                item
                for item in evidence_items
                if (
                    item.get("application_file")
                    or item.get("test_file")
                    or item.get("failure_type")
                )
            ]

            if (
                evidence_items
                and len(mapped_items)
                == len(evidence_items)
            ):
                return "HIGH"

        return "MEDIUM"

    if evidence.evidence_quality == "PARTIAL":
        return "MEDIUM"

    return "LOW"


def build_summary(
    evidence,
    release_gate,
    groups,
    request,
):
    summary = evidence.test_summary
    framework = (
        evidence.framework
        or request.project_type
    )

    if evidence.test_result == "PASS":
        warning_text = (
            " Supplied warnings still require review."
            if evidence.warnings
            else ""
        )
        return (
            f"The validated {framework} runtime workflow completed with "
            f"{summary.total} tests, {summary.passed} passed, no confirmed failures, "
            f"and no execution errors. The runtime gate is {release_gate} for the tested scope only."
            f"{warning_text}"
        )

    if evidence.test_result == "FAIL":
        failed_count = (
            summary.failed
            + summary.errors
        )
        group_count = len(groups)

        return (
            f"The validated runtime workflow produced {failed_count} failing or errored tests "
            f"across {group_count} evidence-based root-cause group"
            f"{'s' if group_count != 1 else ''}. The runtime gate is {release_gate} "
            "until the confirmed failures are resolved and verified."
        )

    if evidence.test_result == "NOT_RUN":
        return (
            f"The validated command did not establish an executed test result. "
            f"The runtime gate is {release_gate} because runtime QA evidence remains incomplete."
        )

    return (
        f"The runtime result for `{request.command}` is inconclusive. "
        f"The runtime gate is {release_gate} until the execution barrier is resolved "
        "and conclusive evidence is collected."
    )


def build_verification_steps(evidence, groups):
    steps = []
    affected_tests = unique_strings(
        test
        for group in groups
        for test in group.get(
            "affected_tests",
            [],
        )
    )

    if affected_tests:
        steps.append(
            "Rerun the affected tests and confirm that each previously failing test passes."
        )

    if evidence.test_result == "FAIL":
        steps.append(
            "Run the complete test suite after the targeted verification."
        )
        steps.append(
            "Confirm that the full validated test command exits with code 0 and introduces no regression."
        )
    elif evidence.test_result == "PASS":
        steps.append(
            "Retain the structured runtime evidence with the tested-scope release record."
        )
    else:
        steps.append(
            "Resolve the execution or discovery issue and rerun the validated test command."
        )

    return unique_strings(steps)


def build_limitations(evidence):
    limitations = [
        "This assessment is limited to supplied runtime and automated test evidence and does not establish complete application correctness."
    ]

    if evidence.evidence_quality != "STRUCTURED":
        limitations.append(
            "Structured test-report evidence was unavailable or incomplete, so parts of the assessment rely on console output."
        )

    if evidence.collection_errors:
        limitations.append(
            "One or more structured evidence files could not be parsed completely."
        )

    if evidence.evidence_truncated:
        limitations.append(
            "Submitted failure-detail records were truncated for inference limits, while aggregate test counts remain parser-validated."
        )

    return unique_strings(limitations)


def build_base_analysis(request: LogAnalysisRequest):
    evidence = select_evidence(request)
    groups = build_root_cause_groups(evidence)

    if not groups and (
        evidence.failure_type
        or request.failure_type
        or evidence.test_result in {
            "NOT_RUN",
            "INCONCLUSIVE",
        }
        or not request.success
    ):
        groups = [
            build_environment_group(
                evidence,
                request,
            )
        ]

    release_gate = determine_release_gate(
        evidence,
        request,
    )
    confidence = determine_confidence(
        evidence,
        groups,
    )
    summary = build_summary(
        evidence,
        release_gate,
        groups,
        request,
    )

    required_actions = unique_strings(
        group.get("required_action")
        for group in groups
    )

    if (
        not required_actions
        and evidence.test_result == "PASS"
    ):
        if evidence.warnings:
            required_actions = [
                "Review the supplied runtime warnings and retain the structured evidence with the tested-scope release record."
            ]
        else:
            required_actions = [
                "Retain the structured runtime evidence and evaluate it together with the remaining QA evidence before the final project-level release decision."
            ]

    primary_root_cause = (
        groups[0].get("root_cause")
        if groups
        else None
    )
    runtime_impact = (
        groups[0].get("runtime_impact")
        if groups
        else "No blocking runtime impact was detected within the supplied tested scope."
    )
    final_status = (
        "PASS"
        if release_gate in {
            "ALLOW_RELEASE",
            "ALLOW_WITH_WARNINGS",
        }
        else "FAIL"
    )
    warnings = unique_strings(
        evidence.warnings
    )
    issues = unique_strings(
        group.get("title")
        for group in groups
    )

    return {
        "agent_id": AGENT_ID,
        "display_name": DISPLAY_NAME,
        "agent_version": AGENT_VERSION,
        "agent": "log-agent",
        "mode": "rule-based-validated",
        "model": None,
        "execution_status": evidence.execution_status,
        "test_result": evidence.test_result,
        "release_gate": release_gate,
        "diagnosis_confidence": confidence,
        "final_status": final_status,
        "summary": summary,
        "run_summary": {
            "framework": evidence.framework,
            "command": (
                evidence.command
                or request.command
            ),
            "total": evidence.test_summary.total,
            "passed": evidence.test_summary.passed,
            "failed": evidence.test_summary.failed,
            "skipped": evidence.test_summary.skipped,
            "errors": evidence.test_summary.errors,
            "exit_code": evidence.exit_code,
            "duration_seconds": (
                evidence.duration_seconds
                or evidence.test_summary.duration_seconds
            ),
            "report_source": evidence.report_source,
            "report_files": evidence.report_files,
            "failure_records_total": (
                evidence.failure_records_total
                or len(evidence.failures)
            ),
            "failure_records_submitted": (
                evidence.failure_records_submitted
                or len(evidence.failures)
            ),
            "evidence_truncated": evidence.evidence_truncated,
        },
        "root_cause_groups": groups,
        "primary_root_cause": primary_root_cause,
        "root_cause": primary_root_cause,
        "runtime_impact": runtime_impact,
        "required_actions": required_actions,
        "recommendation": (
            required_actions[0]
            if required_actions
            else "No blocking runtime remediation was identified within the tested scope."
        ),
        "verification_steps": build_verification_steps(
            evidence,
            groups,
        ),
        "issues": issues,
        "warnings": warnings,
        "limitations": build_limitations(
            evidence
        ),
        "evidence_quality": evidence.evidence_quality,
        "llm_error": None,
    }


def should_use_llm(base_analysis):
    return (
        bool(
            base_analysis.get(
                "root_cause_groups"
            )
        )
        and base_analysis.get("test_result")
        != "PASS"
    )