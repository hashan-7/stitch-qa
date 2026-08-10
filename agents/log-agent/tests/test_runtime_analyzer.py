import json
import sys

import pytest
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from runtime_analyzer import build_base_analysis
from schemas import LogAnalysisRequest
from validators import validate_model_output


def build_request():
    return LogAnalysisRequest.model_validate(
        {
            "project_type": "Python Project",
            "command": "python -m pytest",
            "success": False,
            "exit_code": 1,
            "stdout": "",
            "stderr": "",
            "runtime_evidence": {
                "schema_version": "1.0",
                "framework": "pytest",
                "command": "python -m pytest",
                "execution_status": "COMPLETED",
                "test_result": "FAIL",
                "exit_code": 1,
                "duration_seconds": 0.13,
                "test_summary": {
                    "total": 4,
                    "passed": 2,
                    "failed": 2,
                    "skipped": 0,
                    "errors": 0,
                    "duration_seconds": 0.13,
                },
                "failures": [
                    {
                        "id": "PYTEST-0001",
                        "status": "FAILED",
                        "test_name": "tests/test_app.py::test_divide_rejects_zero",
                        "test_file": "tests/test_app.py",
                        "test_line": 16,
                        "exception_type": "ZeroDivisionError",
                        "exception_message": "division by zero",
                        "expected": "ValueError",
                        "application_file": "app.py",
                        "application_line": 10,
                    },
                    {
                        "id": "PYTEST-0002",
                        "status": "FAILED",
                        "test_name": "tests/test_app.py::test_average_rejects_empty_values",
                        "test_file": "tests/test_app.py",
                        "test_line": 21,
                        "exception_type": "ZeroDivisionError",
                        "exception_message": "division by zero",
                        "expected": "ValueError",
                        "application_file": "app.py",
                        "application_line": 14,
                    },
                ],
                "failure_records_total": 2,
                "failure_records_submitted": 2,
                "evidence_truncated": False,
                "warnings": [],
                "report_files": ["pytest-junit.xml"],
                "report_source": "JUNIT_XML",
                "evidence_quality": "STRUCTURED",
                "collection_errors": [],
            },
        }
    )


def test_structured_failure_analysis_is_complete_and_evidence_backed():
    result = build_base_analysis(build_request())

    assert result["execution_status"] == "COMPLETED"
    assert result["test_result"] == "FAIL"
    assert result["release_gate"] == "BLOCK_RELEASE"
    assert result["runtime_risk_level"] == "HIGH"
    assert result["failure_origin"] == "APPLICATION_DEFECT"
    assert result["diagnosis_confidence"] == "HIGH"
    assert result["evidence_quality"] == "STRUCTURED"
    assert result["run_summary"]["total"] == 4
    assert result["run_summary"]["passed"] == 2
    assert result["run_summary"]["failed"] == 2
    assert len(result["root_cause_groups"]) == 1
    assert len(result["root_cause_groups"][0]["affected_tests"]) == 2
    assert "Boundary-input validation" in result["primary_root_cause"]


def valid_model_payload():
    return {
        "outcome_interpretation": "The validated tested paths fail because ZeroDivisionError violates the expected ValueError behavior.",
        "scope_assurance": "The supplied evidence validates only the exercised boundary-input runtime paths.",
        "residual_runtime_risk": "Equivalent untested boundary paths may still expose the same input validation weakness.",
        "next_verification": "Rerun the affected tests after remediation and then execute the complete regression suite.",
        "group_insights": [
            {
                "group_id": "RQI-001",
                "root_cause": "Input validation is insufficient because ZeroDivisionError is observed where ValueError is expected.",
                "runtime_impact": "The exercised boundary-input paths terminate with the wrong exception contract.",
                "required_action": "Add the expected boundary validation, rerun the affected tests, then run the full suite.",
            }
        ],
    }


def test_valid_grounded_model_output_is_accepted():
    base_analysis = build_base_analysis(build_request())
    payload = validate_model_output(
        json.dumps(valid_model_payload()),
        base_analysis,
    )
    assert payload.group_insights[0].group_id == "RQI-001"


def test_invented_exception_type_is_rejected():
    base_analysis = build_base_analysis(build_request())
    data = valid_model_payload()
    data["group_insights"][0]["root_cause"] = (
        "A DatabaseError caused the validated boundary-input failure instead of the observed exception behavior."
    )
    with pytest.raises(ValueError, match="unsupported exception type"):
        validate_model_output(json.dumps(data), base_analysis)


def test_wrong_locked_test_count_is_rejected():
    base_analysis = build_base_analysis(build_request())
    data = valid_model_payload()
    data["outcome_interpretation"] = (
        "The validated runtime result confirms 3 failed tests in the exercised boundary-input scope."
    )
    with pytest.raises(ValueError, match="parser-validated test count"):
        validate_model_output(json.dumps(data), base_analysis)


def test_ungrounded_root_cause_is_rejected():
    base_analysis = build_base_analysis(build_request())
    data = valid_model_payload()
    data["group_insights"][0]["root_cause"] = (
        "A remote database outage caused unrelated persistence operations to terminate unexpectedly."
    )
    with pytest.raises(ValueError, match="not sufficiently grounded"):
        validate_model_output(json.dumps(data), base_analysis)
