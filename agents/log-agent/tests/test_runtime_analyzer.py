import json
import sys

import pytest
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from model_service import MODEL_RESPONSE_SCHEMA, ModelService
from runtime_analyzer import build_base_analysis, should_use_llm
from schemas import LogAnalysisRequest
from validators import merge_model_output, validate_model_output


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
    assert result["summary"] == (
        "pytest: 2/4 tests failed or errored across 1 root-cause group; "
        "runtime gate BLOCK_RELEASE until fixes are verified."
    )
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


def test_model_merge_refines_root_cause_without_replacing_deterministic_action_or_impact():
    base_analysis = build_base_analysis(build_request())
    payload = validate_model_output(
        json.dumps(valid_model_payload()),
        base_analysis,
    )
    original_impact = base_analysis["root_cause_groups"][0]["runtime_impact"]
    original_action = base_analysis["root_cause_groups"][0]["required_action"]
    merged = merge_model_output(base_analysis, payload)
    assert merged["root_cause_groups"][0]["root_cause"] == payload.group_insights[0].root_cause
    assert merged["root_cause_groups"][0]["runtime_impact"] == original_impact
    assert merged["root_cause_groups"][0]["required_action"] == original_action
    assert merged["outcome_interpretation"] == payload.outcome_interpretation
    assert merged["scope_assurance"] == payload.scope_assurance
    assert merged["residual_runtime_risk"] == payload.residual_runtime_risk
    assert merged["next_verification"] == payload.next_verification
    assert "Gate: BLOCK_RELEASE" in merged["summary"]
    assert "Next:" in merged["summary"]


class FakeGGUFModel:
    def __init__(self, chunks):
        self.chunks = chunks
        self.last_kwargs = None

    def tokenize(self, value, add_bos=False, special=True):
        return list(range(max(1, len(value) // 12)))

    def create_chat_completion(self, **kwargs):
        self.last_kwargs = kwargs
        return iter(self.chunks)


def completion_chunk(content=None, finish_reason=None):
    return {
        "choices": [
            {
                "delta": (
                    {"content": content}
                    if content is not None
                    else {}
                ),
                "finish_reason": finish_reason,
            }
        ]
    }


def test_gguf_model_service_uses_no_think_and_json_schema(monkeypatch):
    payload = json.dumps(valid_model_payload())
    model = FakeGGUFModel(
        [
            completion_chunk(payload),
            completion_chunk(finish_reason="stop"),
        ]
    )
    service = ModelService()
    service.model = model
    service.model_name = service.primary_model
    monkeypatch.setattr(service, "max_generation_seconds", 30.0)
    result = service.generate(
        [
            {"role": "system", "content": "system"},
            {"role": "user", "content": "analyze"},
        ]
    )
    assert json.loads(result) == valid_model_payload()
    assert model.last_kwargs["response_format"]["schema"] == MODEL_RESPONSE_SCHEMA
    assert model.last_kwargs["messages"][0]["content"].endswith("/no_think")
    assert model.last_kwargs["stream"] is True
    assert service.last_generation["backend"] == "llama.cpp"
    assert service.last_generation["timed_out"] is False


def test_gguf_model_service_rejects_output_length_stop():
    partial = '{"outcome_interpretation":"partial"}'
    model = FakeGGUFModel(
        [
            completion_chunk(partial),
            completion_chunk(finish_reason="length"),
        ]
    )
    service = ModelService()
    service.model = model
    service.model_name = service.primary_model
    with pytest.raises(RuntimeError, match="output token limit"):
        service.generate(
            [
                {"role": "system", "content": "system"},
                {"role": "user", "content": "analyze"},
            ]
        )



def test_adaptive_llm_skips_high_confidence_structured_single_group():
    result = build_base_analysis(build_request())
    assert result["diagnosis_confidence"] == "HIGH"
    assert result["evidence_quality"] == "STRUCTURED"
    assert len(result["root_cause_groups"]) == 1
    assert should_use_llm(result) is False


def test_adaptive_llm_runs_for_ambiguous_diagnosis():
    result = build_base_analysis(build_request())
    result["diagnosis_confidence"] = "MEDIUM"
    assert should_use_llm(result) is True


def test_model_service_cooldown_bypasses_repeated_timeout_work():
    service = ModelService()
    service.failure_cooldown_seconds = 300.0
    service._mark_degraded("generation_timeout")

    with pytest.raises(RuntimeError, match="temporarily bypassed"):
        service.generate(
            [
                {"role": "system", "content": "system"},
                {"role": "user", "content": "analyze"},
            ]
        )

    assert service.last_generation["bypassed"] is True
    assert service.last_generation["bypass_reason"] == "cooldown"


def build_maven_plugin_resolution_request():
    return LogAnalysisRequest.model_validate(
        {
            "project_type": "Java Maven Project",
            "command": "mvn test",
            "success": False,
            "exit_code": 1,
            "stdout": "",
            "stderr": "Plugin org.apache.maven.plugins:maven-surefire-plugin:3.6.0 could not be resolved",
            "failure_type": "MAVEN_PLUGIN_RESOLUTION_FAILURE",
            "help_message": (
                "Maven could not resolve a required build plugin before unit-test execution. "
                "Verify the plugin coordinates and version, confirm repository access, and rerun Stitch QA."
            ),
            "runtime_evidence": {
                "schema_version": "1.0",
                "framework": "maven-surefire",
                "command": "mvn test",
                "execution_status": "COMPLETED",
                "test_result": "NOT_RUN",
                "exit_code": 1,
                "duration_seconds": 6.5,
                "test_summary": {
                    "total": 0,
                    "passed": 0,
                    "failed": 0,
                    "skipped": 0,
                    "errors": 0,
                    "duration_seconds": 6.5,
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
                "failure_type": "MAVEN_PLUGIN_RESOLUTION_FAILURE",
            },
        }
    )


def test_maven_plugin_resolution_failure_is_not_reported_as_test_failure():
    result = build_base_analysis(build_maven_plugin_resolution_request())

    assert result["execution_status"] == "COMPLETED"
    assert result["test_result"] == "NOT_RUN"
    assert result["release_gate"] == "REVIEW_REQUIRED"
    assert result["runtime_risk_level"] == "UNKNOWN"
    assert result["failure_origin"] == "EXECUTION"
    assert result["diagnosis_confidence"] == "HIGH"
    assert result["evidence_quality"] == "NONE"
    assert result["root_cause_groups"][0]["category"] == "BUILD_CONFIGURATION"
    assert "resolve a required build plugin" in result["root_cause_groups"][0]["root_cause"]
    assert should_use_llm(result) is False
