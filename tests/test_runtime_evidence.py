from stitch_cli.runtime_evidence import collect_runtime_evidence


def test_console_fallback_extracts_pytest_summary(tmp_path):
    evidence = collect_runtime_evidence(
        project_root=tmp_path,
        command="python -m pytest",
        command_profile="PYTHON_PYTEST",
        success=False,
        exit_code=1,
        stdout="FAILED test_app.py::test_one\n= 1 failed, 2 passed in 0.08s =",
        stderr="",
        duration_seconds=0.1,
        report_files=[],
        executed=True,
        skipped=False,
    )

    assert evidence["test_result"] == "FAIL"
    assert evidence["test_summary"]["total"] == 3
    assert evidence["test_summary"]["passed"] == 2
    assert evidence["test_summary"]["failed"] == 1
    assert evidence["evidence_quality"] == "LOG_ONLY"


def test_environment_failure_is_not_a_code_failure(tmp_path):
    evidence = collect_runtime_evidence(
        project_root=tmp_path,
        command="mvn test",
        command_profile="MAVEN_SYSTEM",
        success=False,
        exit_code=None,
        stdout="",
        stderr="Maven is not available",
        duration_seconds=0.0,
        report_files=[],
        failure_type="MAVEN_NOT_AVAILABLE",
        help_message="Install Maven.",
        executed=False,
        skipped=False,
    )

    assert evidence["execution_status"] == "FAILED_TO_START"
    assert evidence["test_result"] == "NOT_RUN"
