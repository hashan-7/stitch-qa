import importlib
import sys
import types

import requests

from stitch_cli.runtime_fallback import build_client_runtime_fallback


def build_execution_result():
    return {
        "command": "python -m pytest",
        "success": False,
        "exit_code": 1,
        "duration_seconds": 0.13,
        "failure_type": None,
        "help_message": None,
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
                    "actual": None,
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
                    "actual": None,
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
            "failure_type": None,
            "help_message": None,
        },
    }


def test_client_fallback_preserves_structured_runtime_facts():
    result = build_client_runtime_fallback(
        {"project_type": "Python Project"},
        build_execution_result(),
        "Remote end closed connection without response",
    )

    assert result["mode"] == "client-rule-based-fallback"
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
    assert any("Remote Runtime Quality Intelligence service fallback" in item for item in result["warnings"])


class FailingSession:
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        return False

    def post(self, *args, **kwargs):
        raise requests.ConnectionError("remote closed connection")


def test_remote_failure_uses_structured_client_fallback(monkeypatch):
    code_cli = types.ModuleType("stitch_cli.code_cli")
    code_cli.call_code_agent = lambda *args, **kwargs: None
    code_cli.call_source_review_agent = lambda *args, **kwargs: None
    code_cli.call_repair_assurance_agent = lambda *args, **kwargs: None
    monkeypatch.setitem(sys.modules, "stitch_cli.code_cli", code_cli)
    monkeypatch.delitem(sys.modules, "stitch_cli.agent_client", raising=False)
    agent_client = importlib.import_module("stitch_cli.agent_client")
    monkeypatch.setattr(
        agent_client,
        "build_runtime_agent_session",
        lambda: FailingSession(),
    )
    result = agent_client.analyze_logs_with_agent(
        "https://example.invalid",
        {"project_type": "Python Project"},
        build_execution_result(),
    )

    assert result["success"] is True
    assert result["degraded"] is True
    assert result["data"]["mode"] == "client-rule-based-fallback"
    assert result["data"]["execution_status"] == "COMPLETED"
    assert result["data"]["test_result"] == "FAIL"
    assert result["data"]["runtime_risk_level"] == "HIGH"
    assert result["data"]["failure_origin"] == "APPLICATION_DEFECT"
    assert result["data"]["release_gate"] == "BLOCK_RELEASE"
    assert result["data"]["diagnosis_confidence"] == "HIGH"
    assert result["data"]["evidence_quality"] == "STRUCTURED"
