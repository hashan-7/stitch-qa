import re
from collections import defaultdict


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

EXECUTION_FAILURES = {
    "EXECUTION_OS_ERROR",
    "EXECUTION_ERROR",
}

MAVEN_TEST_BLOCKERS = {
    "MAVEN_PLUGIN_RESOLUTION_FAILURE",
    "MAVEN_DEPENDENCY_RESOLUTION_FAILURE",
    "MAVEN_TEST_COMPILATION_FAILURE",
    "MAVEN_COMPILATION_FAILURE",
    "MAVEN_TEST_EXECUTION_BLOCKED",
}

PRECISE_MAVEN_TEST_BLOCKERS = MAVEN_TEST_BLOCKERS - {
    "MAVEN_TEST_EXECUTION_BLOCKED",
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


def safe_int(value, default=0):
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def short_text(value, limit=240):
    text = " ".join(str(value or "").split()).strip()

    if len(text) <= limit:
        return text

    return text[: limit - 3].rstrip() + "..."


def normalize_exception_type(value):
    text = str(value or "UnknownFailure").strip()
    return text.rsplit(".", 1)[-1] if text else "UnknownFailure"


def failure_category(failure):
    exception_type = normalize_exception_type(
        failure.get("exception_type")
    ).lower()
    message = str(
        failure.get("exception_message") or ""
    ).lower()

    if "zero" in exception_type and "division" in exception_type:
        return "INPUT_VALIDATION"

    if (
        "assert" in exception_type
        or failure.get("expected")
        or failure.get("actual")
    ):
        return "ASSERTION_FAILURE"

    if "module" in exception_type or "import" in exception_type:
        return "DEPENDENCY_FAILURE"

    if "timeout" in exception_type or "timeout" in message:
        return "TIMEOUT"

    if "permission" in exception_type or "permission" in message:
        return "PERMISSION_FAILURE"

    if "connection" in exception_type or "network" in message:
        return "NETWORK_FAILURE"

    return "RUNTIME_EXCEPTION"


def failure_signature(failure):
    normalized_message = re.sub(
        r"\b\d+\b",
        "#",
        str(
            failure.get("exception_message") or ""
        ).strip().lower(),
    )

    return (
        failure_category(failure),
        normalize_exception_type(
            failure.get("exception_type")
        ),
        str(failure.get("expected") or "").strip(),
        str(failure.get("actual") or "").strip(),
        normalized_message,
    )


def failure_origin_for_category(category):
    if category in {
        "INPUT_VALIDATION",
        "ASSERTION_FAILURE",
        "RUNTIME_EXCEPTION",
    }:
        return "APPLICATION_DEFECT"

    if category == "DEPENDENCY_FAILURE":
        return "ENVIRONMENT"

    if category in {
        "TIMEOUT",
        "PERMISSION_FAILURE",
        "NETWORK_FAILURE",
    }:
        return "EXECUTION"

    return "NOT_ESTABLISHED"


def failure_location(failure):
    application_file = failure.get("application_file")
    application_line = failure.get("application_line")
    test_file = failure.get("test_file")
    test_line = failure.get("test_line")

    if application_file and application_line:
        return f"{application_file}:{application_line}"

    if application_file:
        return application_file

    if test_file and test_line:
        return f"{test_file}:{test_line}"

    if test_file:
        return test_file

    return "an unmapped tested runtime path"


def failure_observation(failure):
    test_name = short_text(
        failure.get("test_name")
        or failure.get("id")
        or "unknown test",
        180,
    )
    location = short_text(
        failure_location(failure),
        220,
    )
    exception_type = normalize_exception_type(
        failure.get("exception_type")
    )
    exception_message = short_text(
        failure.get("exception_message"),
        240,
    )
    expected = short_text(
        failure.get("expected"),
        220,
    )
    actual = short_text(
        failure.get("actual"),
        220,
    )

    observed = exception_type

    if exception_message:
        observed = f"{exception_type} ({exception_message})"
    elif actual:
        observed = actual

    if expected:
        return (
            f"{test_name} reached {location} and produced "
            f"{observed} instead of the expected {expected} contract"
        )

    return f"{test_name} reached {location} and produced {observed}"


def build_default_root_cause(failures, category):
    first = failures[0]
    exception_type = normalize_exception_type(
        first.get("exception_type")
    )
    observations = "; ".join(
        failure_observation(failure)
        for failure in failures[:3]
    )

    if len(failures) > 3:
        observations += (
            f"; {len(failures) - 3} additional affected test paths are "
            "represented by the same validated failure pattern"
        )

    if category == "INPUT_VALIDATION" and exception_type == "ZeroDivisionError":
        return (
            "Boundary-input validation is missing or insufficient before an operation "
            "that can create a zero divisor. "
            f"{observations}. "
            "The validated tested paths therefore violate their expected error-handling contract."
        )

    if category == "ASSERTION_FAILURE":
        return (
            "The observed runtime behavior does not satisfy the validated test contract. "
            f"{observations}."
        )

    if category == "DEPENDENCY_FAILURE":
        return (
            "A required runtime dependency could not be loaded in the validated execution workflow. "
            f"{observations}."
        )

    if category == "TIMEOUT":
        return (
            "The validated execution path did not complete within the configured time limit. "
            f"{observations}."
        )

    if category == "PERMISSION_FAILURE":
        return (
            "The validated execution path could not complete under the observed permission configuration. "
            f"{observations}."
        )

    if category == "NETWORK_FAILURE":
        return (
            "The validated execution path failed while performing a network-dependent operation. "
            f"{observations}."
        )

    return (
        f"The affected tested paths reached an uncontrolled {exception_type} runtime failure. "
        f"{observations}. "
        "The supplied evidence confirms the failing paths but may not establish every contributing implementation condition."
    )


def build_default_impact(failures, category):
    affected_count = len(failures)

    if category == "INPUT_VALIDATION":
        return (
            f"Invalid boundary inputs can terminate {affected_count} tested execution path"
            f"{'s' if affected_count != 1 else ''} unexpectedly and violate the validated error-handling contract."
        )

    if category == "ASSERTION_FAILURE":
        return (
            f"The implementation conflicts with {affected_count} validated test expectation"
            f"{'s' if affected_count != 1 else ''}, creating tested-scope regression and runtime release risk."
        )

    if category == "DEPENDENCY_FAILURE":
        return "The validated runtime or test workflow cannot complete reliably until the dependency problem is resolved."

    if category == "TIMEOUT":
        return "The validated workflow may exceed execution limits, remain blocked, or produce an inconclusive runtime result."

    if category == "PERMISSION_FAILURE":
        return "The affected validated runtime path cannot complete under the observed permission configuration."

    if category == "NETWORK_FAILURE":
        return "The affected validated runtime path is unavailable or unreliable when the observed connection failure occurs."

    return "The affected tested runtime path fails before completing its expected behavior."


def build_default_action(failures, category):
    affected_tests = unique_strings(
        failure.get("test_name") or failure.get("id")
        for failure in failures
    )
    affected_text = ", ".join(affected_tests[:6]) or "the affected tests"
    expected_contracts = unique_strings(
        failure.get("expected")
        for failure in failures
        if failure.get("expected")
    )
    expected_text = ", ".join(expected_contracts[:4])

    if category == "INPUT_VALIDATION":
        contract_text = (
            f" Preserve the validated {expected_text} contract."
            if expected_text
            else ""
        )
        return (
            "Add explicit boundary-input validation before the failing operation for the behavior exercised by "
            f"{affected_text}.{contract_text} "
            "Rerun the affected tests first, then execute the complete test suite."
        )

    if category == "ASSERTION_FAILURE":
        contract_text = (
            f" The validated expectation is {expected_text}."
            if expected_text
            else ""
        )
        return (
            "Align the affected implementation behavior with the validated expectations exercised by "
            f"{affected_text}.{contract_text} "
            "Rerun the affected tests first, then execute the complete regression suite."
        )

    if category == "DEPENDENCY_FAILURE":
        return (
            "Restore or correctly configure the required runtime dependency for "
            f"{affected_text}, rerun the affected tests, then execute the complete test suite."
        )

    if category == "TIMEOUT":
        return (
            "Investigate the long-running or blocked operation represented by "
            f"{affected_text}, establish a justified execution bound, then rerun the affected workflow."
        )

    if category == "PERMISSION_FAILURE":
        return (
            "Correct the runtime permission or execution configuration affecting "
            f"{affected_text}, then rerun the affected tests and verify completion."
        )

    if category == "NETWORK_FAILURE":
        return (
            "Validate the external dependency and its failure-handling path for "
            f"{affected_text}, restore the required connectivity or controlled test substitute, then rerun the affected tests."
        )

    return (
        "Correct the confirmed failing runtime behavior represented by "
        f"{affected_text}, rerun the affected tests, then execute the complete regression suite."
    )


def evidence_location(failure):
    return {
        "failure_id": failure.get("id"),
        "status": failure.get("status"),
        "test_name": failure.get("test_name"),
        "test_file": failure.get("test_file"),
        "test_line": failure.get("test_line"),
        "exception_type": failure.get("exception_type"),
        "exception_message": failure.get("exception_message"),
        "expected": failure.get("expected"),
        "actual": failure.get("actual"),
        "application_file": failure.get("application_file"),
        "application_line": failure.get("application_line"),
    }


def build_root_cause_groups(evidence):
    grouped = defaultdict(list)

    for item in evidence.get("failures", []):
        if isinstance(item, dict):
            grouped[failure_signature(item)].append(item)

    groups = []

    for index, failures in enumerate(grouped.values(), start=1):
        category = failure_category(failures[0])
        count = len(failures)
        groups.append(
            {
                "group_id": f"RQI-{index:03d}",
                "title": (
                    f"{category.replace('_', ' ').title()} affecting "
                    f"{count} test{'s' if count != 1 else ''}"
                ),
                "category": category,
                "failure_origin": failure_origin_for_category(category),
                "root_cause": build_default_root_cause(failures, category),
                "runtime_impact": build_default_impact(failures, category),
                "required_action": build_default_action(failures, category),
                "affected_tests": unique_strings(
                    item.get("test_name") or item.get("id")
                    for item in failures
                ),
                "evidence": [
                    evidence_location(item)
                    for item in failures
                ],
            }
        )

    return groups


def build_environment_group(evidence, execution_result):
    failure_type = (
        evidence.get("failure_type")
        or execution_result.get("failure_type")
        or "EXECUTION_ENVIRONMENT"
    )
    help_message = (
        evidence.get("help_message")
        or execution_result.get("help_message")
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
        "INVALID_PROJECT_PATH": (
            "The requested project path was not valid or accessible to the test runner.",
            "The runtime test workflow did not start, so no runtime result was established.",
            "Provide an accessible project path and rerun Stitch QA.",
        ),
        "COMMAND_PROFILE_NOT_ALLOWED": (
            "The requested execution command did not match an allowed Stitch QA execution profile.",
            "The command was not executed, so runtime evidence for the intended test workflow is unavailable.",
            "Use a supported built-in execution profile and rerun Stitch QA.",
        ),
        "COMMAND_TIMEOUT": (
            "The validated execution command exceeded the configured timeout.",
            "The QA run ended before a conclusive runtime result was produced.",
            "Investigate the long-running operation or hang, then rerun the workflow.",
        ),
        "EXECUTION_OS_ERROR": (
            "The operating system prevented the validated execution command from completing.",
            "The intended runtime workflow did not produce a conclusive test result.",
            "Resolve the reported operating-system execution error and rerun Stitch QA.",
        ),
        "EXECUTION_ERROR": (
            "The validated execution workflow encountered an execution-layer error before a conclusive test result was established.",
            "Runtime assurance remains incomplete for the intended tested scope.",
            "Resolve the execution-layer error and rerun Stitch QA.",
        ),
        "MAVEN_PLUGIN_RESOLUTION_FAILURE": (
            "Maven could not resolve a required build plugin before unit-test execution.",
            "The Maven process exited before Surefire produced an executed test result, so runtime test assurance is incomplete.",
            "Verify the plugin coordinates and version, confirm repository access, then rerun Stitch QA.",
        ),
        "MAVEN_DEPENDENCY_RESOLUTION_FAILURE": (
            "Maven could not resolve required project or test dependencies before unit-test execution completed.",
            "The Maven workflow did not establish a conclusive executed test result.",
            "Verify dependency coordinates and repositories, restore dependency resolution, then rerun Stitch QA.",
        ),
        "MAVEN_TEST_COMPILATION_FAILURE": (
            "Maven test-source compilation failed before the test suite could execute.",
            "No conclusive runtime test result was established because the test sources did not compile.",
            "Resolve the reported test compilation errors, then rerun Stitch QA.",
        ),
        "MAVEN_COMPILATION_FAILURE": (
            "Maven application compilation failed before a conclusive unit-test result was produced.",
            "The test phase could not establish runtime test assurance for the intended scope.",
            "Resolve the reported compilation errors, then rerun Stitch QA.",
        ),
        "MAVEN_TEST_EXECUTION_BLOCKED": (
            "Maven exited before Surefire produced an executed test result.",
            "Runtime test assurance remains incomplete because no conclusive unit-test result was established.",
            "Resolve the reported build or test-phase blocker, then rerun Stitch QA.",
        ),
    }
    root_cause, impact, action = mapping.get(
        failure_type,
        (
            help_message
            or "The validated execution workflow could not produce conclusive runtime evidence.",
            "The current runtime QA evidence is incomplete and cannot establish tested-scope runtime confidence.",
            "Resolve the execution issue and rerun Stitch QA.",
        ),
    )

    if failure_type in ENVIRONMENT_FAILURES:
        category = "ENVIRONMENT"
        failure_origin = "ENVIRONMENT"
    elif failure_type in DISCOVERY_FAILURES:
        category = "TEST_DISCOVERY"
        failure_origin = "TEST_DISCOVERY"
    elif failure_type in {
        "MAVEN_PLUGIN_RESOLUTION_FAILURE",
        "MAVEN_DEPENDENCY_RESOLUTION_FAILURE",
    }:
        category = "BUILD_CONFIGURATION"
        failure_origin = "EXECUTION"
    elif failure_type in {
        "MAVEN_TEST_COMPILATION_FAILURE",
        "MAVEN_COMPILATION_FAILURE",
    }:
        category = "BUILD_COMPILATION"
        failure_origin = "EXECUTION"
    else:
        category = "EXECUTION"
        failure_origin = "EXECUTION"

    return {
        "group_id": "RQI-001",
        "title": failure_type.replace("_", " ").title(),
        "category": category,
        "failure_origin": failure_origin,
        "root_cause": root_cause,
        "runtime_impact": impact,
        "required_action": action,
        "affected_tests": [],
        "evidence": [
            {
                "failure_type": failure_type,
                "help_message": help_message,
                "command": execution_result.get("command"),
                "exit_code": execution_result.get("exit_code"),
            }
        ],
    }


def determine_release_gate(evidence, execution_result):
    failure_type = (
        evidence.get("failure_type")
        or execution_result.get("failure_type")
    )
    execution_status = str(
        evidence.get("execution_status") or "UNKNOWN"
    ).upper()
    test_result = str(
        evidence.get("test_result") or "INCONCLUSIVE"
    ).upper()

    if (
        failure_type in ENVIRONMENT_FAILURES
        or failure_type in DISCOVERY_FAILURES
        or failure_type in MAVEN_TEST_BLOCKERS
    ):
        return "REVIEW_REQUIRED"

    if execution_status in {
        "FAILED_TO_START",
        "TIMED_OUT",
        "SKIPPED",
    }:
        return "REVIEW_REQUIRED"

    if test_result == "FAIL":
        return "BLOCK_RELEASE"

    if test_result in {"NOT_RUN", "INCONCLUSIVE"}:
        return "REVIEW_REQUIRED"

    if evidence.get("warnings") or evidence.get("collection_errors"):
        return "ALLOW_WITH_WARNINGS"

    return "ALLOW_RELEASE"


def determine_confidence(evidence, groups):
    failure_type = evidence.get("failure_type")

    if failure_type in PRECISE_MAVEN_TEST_BLOCKERS:
        return "HIGH"

    if failure_type == "MAVEN_TEST_EXECUTION_BLOCKED":
        return "MEDIUM"

    evidence_quality = str(
        evidence.get("evidence_quality") or "NONE"
    ).upper()
    test_result = str(
        evidence.get("test_result") or "INCONCLUSIVE"
    ).upper()

    if evidence_quality == "STRUCTURED":
        if evidence.get("collection_errors") or evidence.get("evidence_truncated"):
            return "MEDIUM"

        if test_result == "PASS":
            return "HIGH"

        if groups:
            evidence_items = [
                item
                for group in groups
                for item in group.get("evidence", [])
                if isinstance(item, dict)
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

            if evidence_items and len(mapped_items) == len(evidence_items):
                return "HIGH"

        return "MEDIUM"

    if evidence_quality in {"PARTIAL", "LOG_ONLY"}:
        return "MEDIUM"

    return "LOW"


def determine_failure_origin(evidence, execution_result, groups):
    origins = unique_strings(
        group.get("failure_origin")
        for group in groups
    )

    if "APPLICATION_DEFECT" in origins:
        return "APPLICATION_DEFECT"

    failure_type = (
        evidence.get("failure_type")
        or execution_result.get("failure_type")
    )

    if failure_type in ENVIRONMENT_FAILURES:
        return "ENVIRONMENT"

    if failure_type in DISCOVERY_FAILURES:
        return "TEST_DISCOVERY"

    if (
        failure_type in TIMEOUT_FAILURES
        or failure_type in EXECUTION_FAILURES
        or failure_type in MAVEN_TEST_BLOCKERS
    ):
        return "EXECUTION"

    for origin in (
        "ENVIRONMENT",
        "TEST_DISCOVERY",
        "EXECUTION",
    ):
        if origin in origins:
            return origin

    return "NOT_ESTABLISHED"


def determine_runtime_risk(evidence, release_gate):
    test_result = str(
        evidence.get("test_result") or "INCONCLUSIVE"
    ).upper()

    if test_result == "PASS":
        if (
            release_gate == "ALLOW_WITH_WARNINGS"
            or evidence.get("warnings")
            or evidence.get("collection_errors")
        ):
            return "MEDIUM"

        return "LOW"

    if test_result == "FAIL":
        return "HIGH"

    return "UNKNOWN"


def build_summary(evidence, release_gate, groups, scan_result):
    summary = evidence.get("test_summary") or {}
    framework = (
        evidence.get("framework")
        or scan_result.get("project_type")
        or "runtime"
    )
    test_result = str(
        evidence.get("test_result") or "INCONCLUSIVE"
    ).upper()

    if test_result == "PASS":
        warning_text = (
            " Supplied runtime warnings still require review."
            if evidence.get("warnings")
            else ""
        )
        return (
            f"The validated {framework} runtime test workflow completed successfully within the exercised scope: "
            f"{safe_int(summary.get('total'))} tests were executed, {safe_int(summary.get('passed'))} passed, "
            "with no confirmed test failures or execution errors. "
            f"The runtime gate is {release_gate} for the tested runtime scope only."
            f"{warning_text}"
        )

    if test_result == "FAIL":
        failed_count = safe_int(summary.get("failed")) + safe_int(summary.get("errors"))
        group_count = len(groups)
        return (
            f"The validated {framework} runtime test workflow failed within the exercised scope: "
            f"{failed_count} tests failed or errored and were organized into "
            f"{group_count} evidence-backed root-cause group{'s' if group_count != 1 else ''}. "
            f"The runtime gate is {release_gate} until the confirmed tested-path failures are resolved and verified."
        )

    if test_result == "NOT_RUN":
        reason = (
            short_text(groups[0].get("root_cause"), 180).rstrip(".")
            if groups
            else "no executed test result was established"
        )
        return (
            f"{framework}: tests not run because {reason}. "
            f"Runtime gate {release_gate} until the blocker is resolved."
        )

    command = evidence.get("command") or "the validated command"
    return (
        f"The validated runtime result for `{command}` is inconclusive within the intended tested scope. "
        f"The runtime gate is {release_gate} until the execution barrier is resolved and conclusive runtime evidence is collected."
    )


def build_verification_steps(evidence, groups):
    steps = []
    affected_tests = unique_strings(
        test
        for group in groups
        for test in group.get("affected_tests", [])
    )
    test_result = str(
        evidence.get("test_result") or "INCONCLUSIVE"
    ).upper()

    if affected_tests:
        steps.append(
            "Rerun the affected tests and confirm that each previously failing test passes."
        )

    if test_result == "FAIL":
        steps.append("Run the complete test suite after the targeted verification.")
        steps.append(
            "Confirm that the full validated test command exits with code 0 and introduces no regression."
        )
    elif test_result == "PASS":
        steps.append(
            "Retain the structured runtime evidence with the tested-scope release record."
        )
    else:
        steps.append(
            "Resolve the execution or discovery issue and rerun the validated test command."
        )

    return unique_strings(steps)


def build_limitations(evidence, service_error):
    limitations = [
        "This assessment is limited to supplied runtime and automated test evidence and does not establish complete application correctness.",
        "The remote Runtime Quality Intelligence service was unavailable or returned an unusable response, so this result was produced by the local deterministic runtime fallback.",
    ]

    if str(evidence.get("evidence_quality") or "NONE").upper() != "STRUCTURED":
        limitations.append(
            "Structured test-report evidence was unavailable or incomplete, so parts of the assessment rely on console output."
        )

    if evidence.get("collection_errors"):
        limitations.append(
            "One or more structured evidence files could not be parsed completely."
        )

    if evidence.get("evidence_truncated"):
        limitations.append(
            "Submitted failure-detail records were truncated for transport limits, while aggregate test counts remain parser-validated."
        )

    if not service_error:
        return unique_strings(limitations[0:1])

    return unique_strings(limitations)


def build_client_runtime_fallback(scan_result, execution_result, service_error=None):
    evidence = execution_result.get("runtime_evidence")

    if not isinstance(evidence, dict):
        evidence = {
            "framework": scan_result.get("project_type"),
            "command": execution_result.get("command"),
            "execution_status": execution_result.get("execution_status") or "UNKNOWN",
            "test_result": execution_result.get("test_result") or "INCONCLUSIVE",
            "exit_code": execution_result.get("exit_code"),
            "duration_seconds": execution_result.get("duration_seconds"),
            "test_summary": {
                "total": 0,
                "passed": 0,
                "failed": 0,
                "skipped": 0,
                "errors": 0,
                "duration_seconds": execution_result.get("duration_seconds"),
            },
            "failures": [],
            "failure_records_total": 0,
            "failure_records_submitted": 0,
            "evidence_truncated": False,
            "warnings": [],
            "report_files": [],
            "report_source": "NONE",
            "evidence_quality": "NONE",
            "collection_errors": [],
            "failure_type": execution_result.get("failure_type"),
            "help_message": execution_result.get("help_message"),
        }
    else:
        evidence = dict(evidence)

    groups = build_root_cause_groups(evidence)
    test_result = str(
        evidence.get("test_result") or "INCONCLUSIVE"
    ).upper()

    if not groups and (
        evidence.get("failure_type")
        or execution_result.get("failure_type")
        or test_result in {"NOT_RUN", "INCONCLUSIVE"}
        or not execution_result.get("success")
    ):
        groups = [
            build_environment_group(evidence, execution_result)
        ]

    release_gate = determine_release_gate(evidence, execution_result)
    confidence = determine_confidence(evidence, groups)
    failure_origin = determine_failure_origin(
        evidence,
        execution_result,
        groups,
    )
    runtime_risk_level = determine_runtime_risk(
        evidence,
        release_gate,
    )
    summary = build_summary(
        evidence,
        release_gate,
        groups,
        scan_result,
    )
    required_actions = unique_strings(
        group.get("required_action")
        for group in groups
    )

    if not required_actions and test_result == "PASS":
        if evidence.get("warnings"):
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
        if release_gate in {"ALLOW_RELEASE", "ALLOW_WITH_WARNINGS"}
        else "FAIL"
    )
    warnings = unique_strings(
        [
            *evidence.get("warnings", []),
            (
                f"Remote Runtime Quality Intelligence service fallback: {service_error}"
                if service_error
                else None
            ),
        ]
    )
    issues = unique_strings(
        group.get("title")
        for group in groups
    )
    test_summary = evidence.get("test_summary") or {}

    return {
        "agent_id": AGENT_ID,
        "display_name": DISPLAY_NAME,
        "agent_version": AGENT_VERSION,
        "agent": "log-agent",
        "mode": "client-rule-based-fallback",
        "model": None,
        "execution_status": evidence.get("execution_status") or "UNKNOWN",
        "test_result": test_result,
        "release_gate": release_gate,
        "runtime_risk_level": runtime_risk_level,
        "failure_origin": failure_origin,
        "diagnosis_confidence": confidence,
        "final_status": final_status,
        "summary": summary,
        "run_summary": {
            "framework": evidence.get("framework") or scan_result.get("project_type"),
            "command": evidence.get("command") or execution_result.get("command"),
            "total": safe_int(test_summary.get("total")),
            "passed": safe_int(test_summary.get("passed")),
            "failed": safe_int(test_summary.get("failed")),
            "skipped": safe_int(test_summary.get("skipped")),
            "errors": safe_int(test_summary.get("errors")),
            "exit_code": evidence.get("exit_code", execution_result.get("exit_code")),
            "duration_seconds": (
                evidence.get("duration_seconds")
                or test_summary.get("duration_seconds")
                or execution_result.get("duration_seconds")
            ),
            "report_source": evidence.get("report_source") or "NONE",
            "report_files": list(evidence.get("report_files") or []),
            "failure_records_total": safe_int(
                evidence.get("failure_records_total"),
                len(evidence.get("failures") or []),
            ),
            "failure_records_submitted": safe_int(
                evidence.get("failure_records_submitted"),
                len(evidence.get("failures") or []),
            ),
            "evidence_truncated": bool(evidence.get("evidence_truncated")),
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
        "verification_steps": build_verification_steps(evidence, groups),
        "issues": issues,
        "warnings": warnings,
        "limitations": build_limitations(evidence, service_error),
        "evidence_quality": evidence.get("evidence_quality") or "NONE",
        "llm_error": None,
    }
