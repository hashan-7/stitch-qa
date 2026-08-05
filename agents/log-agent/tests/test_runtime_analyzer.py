import sys
from pathlib import Path

AGENT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(AGENT_ROOT))

from runtime_analyzer import build_base_analysis
from schemas import LogAnalysisRequest


def test_structured_failure_blocks_release():
    request = LogAnalysisRequest.model_validate(
        {
            "project_type": "Python",
            "command": "python -m pytest",
            "success": False,
            "exit_code": 1,
            "stdout": "",
            "stderr": "",
            "runtime_evidence": {
                "framework": "pytest",
                "command": "python -m pytest",
                "execution_status": "COMPLETED",
                "test_result": "FAIL",
                "exit_code": 1,
                "duration_seconds": 0.08,
                "test_summary": {
                    "total": 4,
                    "passed": 2,
                    "failed": 2,
                    "skipped": 0,
                    "errors": 0,
                    "duration_seconds": 0.08,
                },
                "failures": [
                    {
                        "id": "FAIL-0001",
                        "status": "FAILED",
                        "test_name": "test_divide_rejects_zero",
                        "test_file": "test_app.py",
                        "test_line": 12,
                        "exception_type": "ZeroDivisionError",
                        "exception_message": "division by zero",
                        "expected": "ValueError",
                        "actual": "ZeroDivisionError",
                        "application_file": "app.py",
                        "application_line": 2,
                    },
                    {
                        "id": "FAIL-0002",
                        "status": "FAILED",
                        "test_name": "test_average_rejects_empty_values",
                        "test_file": "test_app.py",
                        "test_line": 21,
                        "exception_type": "ZeroDivisionError",
                        "exception_message": "division by zero",
                        "expected": "ValueError",
                        "actual": "ZeroDivisionError",
                        "application_file": "app.py",
                        "application_line": 6,
                    },
                ],
                "report_source": "JUNIT_XML",
                "evidence_quality": "STRUCTURED",
            },
        }
    )

    result = build_base_analysis(request)

    assert result["agent_id"] == "runtime-quality-analyst"
    assert result["release_gate"] == "BLOCK_RELEASE"
    assert result["diagnosis_confidence"] == "HIGH"
    assert result["run_summary"]["total"] == 4
    assert len(result["root_cause_groups"]) == 1
    assert result["root_cause_groups"][0]["evidence"][0]["application_file"] == "app.py"


def test_environment_failure_requires_review():
    request = LogAnalysisRequest.model_validate(
        {
            "project_type": "Java Maven",
            "command": "mvn test",
            "success": False,
            "exit_code": None,
            "stdout": "",
            "stderr": "Maven is unavailable",
            "failure_type": "MAVEN_NOT_AVAILABLE",
            "help_message": "Install Maven.",
        }
    )

    result = build_base_analysis(request)

    assert result["execution_status"] == "FAILED_TO_START"
    assert result["test_result"] == "NOT_RUN"
    assert result["release_gate"] == "REVIEW_REQUIRED"
