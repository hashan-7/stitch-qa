import json
import sys
from pathlib import Path

import pytest


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from model_service import MODEL_RESPONSE_SCHEMA, ModelService, model_service
from app import analyze_logs
from prompts import build_analysis_messages
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
                        "actual": "ZeroDivisionError",
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
                        "actual": "ZeroDivisionError",
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


def valid_model_payload():
    return {
        "o": "A",
        "r": "H",
        "q": "H",
        "g": [
            {
                "f": [1, 2],
                "k": "BOUNDARY",
                "c": "Unchecked zero division",
                "i": "Boundary paths crash",
                "a": "Validate inputs; rerun failures",
            }
        ],
    }


def test_base_analysis_keeps_exact_facts_and_safe_fallback():
    result = build_base_analysis(build_request())
    assert result["execution_status"] == "COMPLETED"
    assert result["test_result"] == "FAIL"
    assert result["release_gate"] == "BLOCK_RELEASE"
    assert result["run_summary"]["total"] == 4
    assert result["run_summary"]["passed"] == 2
    assert result["run_summary"]["failed"] == 2
    assert result["evidence_quality"] == "STRUCTURED"
    assert result["root_cause_groups"]


def test_ai_is_used_for_high_confidence_structured_failure():
    result = build_base_analysis(build_request())
    assert result["diagnosis_confidence"] == "HIGH"
    assert result["evidence_quality"] == "STRUCTURED"
    assert should_use_llm(result) is True


def test_prompt_uses_compact_locked_evidence_not_fallback_diagnosis():
    result = build_base_analysis(build_request())
    messages = build_analysis_messages(result)
    user_text = messages[1]["content"]
    assert '"n":1' in user_text
    assert '"n":2' in user_text
    assert "ZeroDivisionError" in user_text
    assert "PYTEST-0001" not in user_text
    assert "Boundary-input validation is missing or insufficient" not in user_text
    assert len(user_text) < 1800


def test_valid_dynamic_ai_reasoning_is_accepted():
    base = build_base_analysis(build_request())
    payload = validate_model_output(json.dumps(valid_model_payload()), base)
    assert payload.failure_origin == "APPLICATION_DEFECT"
    assert payload.runtime_risk_level == "HIGH"
    assert payload.groups[0].failure_ids == ["PYTEST-0001", "PYTEST-0002"]


def test_unknown_failure_id_is_rejected():
    base = build_base_analysis(build_request())
    data = valid_model_payload()
    data["g"][0]["f"] = [1, 99]
    with pytest.raises(ValueError, match="unknown evidence number"):
        validate_model_output(json.dumps(data), base)


def test_missing_failure_id_is_rejected():
    base = build_base_analysis(build_request())
    data = valid_model_payload()
    data["g"][0]["f"] = [1]
    with pytest.raises(ValueError, match="cover every submitted failure ID"):
        validate_model_output(json.dumps(data), base)


def test_invented_exception_type_is_rejected():
    base = build_base_analysis(build_request())
    data = valid_model_payload()
    data["g"][0]["c"] = "DatabaseError division failure"
    with pytest.raises(ValueError, match="unsupported exception type"):
        validate_model_output(json.dumps(data), base)


def test_wrong_locked_test_count_is_rejected():
    base = build_base_analysis(build_request())
    data = {
        "s": "3 failed tests share boundary validation defects.",
        "o": "APPLICATION_DEFECT",
        "r": "HIGH",
        "c": "HIGH",
        "v": "Rerun affected tests.",
        "x": [{
            "f": ["PYTEST-0001", "PYTEST-0002"],
            "k": "BOUNDARY",
            "o": "APPLICATION_DEFECT",
            "c": "Unchecked zero division",
            "i": "Boundary paths crash",
            "a": "Validate inputs; rerun failures",
        }],
    }
    with pytest.raises(ValueError, match="parser-validated test count"):
        validate_model_output(json.dumps(data), base)


def test_confirmed_failure_cannot_be_downgraded_to_low_risk():
    base = build_base_analysis(build_request())
    data = valid_model_payload()
    data["r"] = "L"
    with pytest.raises(ValueError, match="cannot be downgraded"):
        validate_model_output(json.dumps(data), base)


def test_ai_merge_owns_reasoning_but_preserves_locked_release_gate_and_facts():
    base = build_base_analysis(build_request())
    payload = validate_model_output(json.dumps(valid_model_payload()), base)
    merged = merge_model_output(base, payload)

    assert merged["run_summary"] == base["run_summary"]
    assert merged["test_result"] == "FAIL"
    assert merged["release_gate"] == "BLOCK_RELEASE"
    assert merged["failure_origin"] == "APPLICATION_DEFECT"
    assert merged["runtime_risk_level"] == "HIGH"
    assert merged["diagnosis_confidence"] == "HIGH"
    assert merged["root_cause_groups"][0]["category"] == "BOUNDARY"
    assert "Unchecked zero division" in merged["root_cause_groups"][0]["root_cause"]
    assert "Validate inputs; rerun failures" in merged["required_actions"][0]
    assert merged["summary"].startswith("Unchecked zero division")
    assert "Gate: BLOCK_RELEASE" in merged["summary"]


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
                "delta": {"content": content} if content is not None else {},
                "finish_reason": finish_reason,
            }
        ]
    }


def test_response_schema_uses_compact_reasoning_contract():
    schema = MODEL_RESPONSE_SCHEMA
    assert schema["additionalProperties"] is False
    assert schema["required"] == ["o", "r", "q", "g"]
    assert schema["properties"]["o"]["enum"] == ["A", "E", "D", "X", "N"]
    group_schema = schema["properties"]["g"]["items"]
    assert group_schema["type"] == "object"
    assert group_schema["additionalProperties"] is False
    assert group_schema["required"] == ["f", "k", "c", "i", "a"]
    assert group_schema["properties"]["f"]["items"]["type"] == "integer"


def test_malformed_positional_group_output_is_rejected():
    base = build_base_analysis(build_request())
    data = valid_model_payload()
    data["g"] = [[1, 2, "BOUNDARY_VALIDATION"]]
    with pytest.raises(ValueError, match="must be a JSON object"):
        validate_model_output(json.dumps(data), base)


def test_expanded_legacy_payload_is_still_accepted():
    base = build_base_analysis(build_request())
    data = {
        "s": "Two boundary paths violate their expected exception contract.",
        "o": "APPLICATION_DEFECT",
        "r": "HIGH",
        "c": "HIGH",
        "v": "Rerun both affected tests, then execute the full suite.",
        "x": [
            {
                "f": ["PYTEST-0001", "PYTEST-0002"],
                "k": "BOUNDARY_VALIDATION",
                "o": "APPLICATION_DEFECT",
                "c": "Missing boundary validation causes ZeroDivisionError in both tested paths.",
                "i": "Both tested boundary paths terminate unexpectedly.",
                "a": "Validate zero and empty inputs, then rerun both tests.",
            }
        ],
    }
    payload = validate_model_output(json.dumps(data), base)
    assert payload.groups[0].failure_ids == ["PYTEST-0001", "PYTEST-0002"]


def test_gguf_model_service_uses_compact_schema_and_early_json_stop(monkeypatch):
    payload = json.dumps(valid_model_payload())
    model = FakeGGUFModel([
        completion_chunk(payload),
        completion_chunk(finish_reason="stop"),
    ])
    service = ModelService()
    service.model = model
    service.model_name = service.primary_model
    monkeypatch.setattr(service, "max_generation_seconds", 30.0)
    result = service.generate([
        {"role": "system", "content": "system"},
        {"role": "user", "content": "analyze"},
    ])

    assert json.loads(result) == valid_model_payload()
    assert model.last_kwargs["response_format"] == {
        "type": "json_object",
        "schema": MODEL_RESPONSE_SCHEMA,
    }
    assert model.last_kwargs["messages"][0]["content"].endswith("/no_think")
    assert model.last_kwargs["stream"] is True
    assert service.last_generation["backend"] == "llama.cpp"
    assert service.last_generation["timed_out"] is False
    assert service.last_generation["finish_reason"] == "json_complete"
    assert service.max_new_tokens == 64


def test_gguf_model_service_rejects_output_length_stop():
    model = FakeGGUFModel([
        completion_chunk('{"s":"partial"'),
        completion_chunk(finish_reason="length"),
    ])
    service = ModelService()
    service.model = model
    service.model_name = service.primary_model
    with pytest.raises(RuntimeError, match="output token limit"):
        service.generate([
            {"role": "system", "content": "system"},
            {"role": "user", "content": "analyze"},
        ])


def test_model_service_cooldown_bypasses_repeated_timeout_work():
    service = ModelService()
    service.failure_cooldown_seconds = 180.0
    service._mark_degraded("generation_timeout")
    with pytest.raises(RuntimeError, match="temporarily bypassed"):
        service.generate([
            {"role": "system", "content": "system"},
            {"role": "user", "content": "analyze"},
        ])
    assert service.last_generation["bypassed"] is True
    assert service.last_generation["bypass_reason"] == "cooldown"



def build_maven_failure_request():
    return LogAnalysisRequest.model_validate(
        {
            "project_type": "Java Maven Project",
            "command": "mvn test",
            "success": False,
            "exit_code": 1,
            "stdout": "",
            "stderr": "",
            "runtime_evidence": {
                "schema_version": "1.0",
                "framework": "maven-surefire",
                "command": "mvn test",
                "execution_status": "COMPLETED",
                "test_result": "FAIL",
                "exit_code": 1,
                "duration_seconds": 5.4,
                "test_summary": {"total": 5, "passed": 3, "failed": 2, "skipped": 0, "errors": 0},
                "failures": [
                    {
                        "id": "MAVEN-0001",
                        "status": "FAILED",
                        "test_name": "com.stitchqa.fixture.CalculatorTest::divide_rejects_zero",
                        "test_file": "src/test/java/com/stitchqa/fixture/CalculatorTest.java",
                        "test_line": 27,
                        "exception_type": "AssertionFailedError",
                        "exception_message": "Unexpected exception type thrown",
                        "expected": "java.lang.IllegalArgumentException",
                        "actual": "java.lang.ArithmeticException",
                        "application_file": "src/main/java/com/stitchqa/fixture/Calculator.java",
                        "application_line": 13,
                    },
                    {
                        "id": "MAVEN-0002",
                        "status": "FAILED",
                        "test_name": "com.stitchqa.fixture.CalculatorTest::average_rejects_empty_values",
                        "test_file": "src/test/java/com/stitchqa/fixture/CalculatorTest.java",
                        "test_line": 35,
                        "exception_type": "AssertionFailedError",
                        "exception_message": "Unexpected exception type thrown",
                        "expected": "java.lang.IllegalArgumentException",
                        "actual": "java.lang.ArithmeticException",
                        "application_file": "src/main/java/com/stitchqa/fixture/Calculator.java",
                        "application_line": 23,
                    },
                ],
                "failure_records_total": 2,
                "failure_records_submitted": 2,
                "evidence_truncated": False,
                "warnings": [],
                "report_files": ["TEST-com.stitchqa.fixture.CalculatorTest.xml"],
                "report_source": "SUREFIRE_XML",
                "evidence_quality": "STRUCTURED",
                "collection_errors": [],
            },
        }
    )


def test_maven_structured_failure_also_uses_dynamic_ai_reasoning():
    base = build_base_analysis(build_maven_failure_request())
    assert base["run_summary"]["total"] == 5
    assert base["run_summary"]["failed"] == 2
    assert should_use_llm(base) is True

    data = {
        "o": "A",
        "r": "H",
        "q": "H",
        "g": [
            {
                "f": [1, 2],
                "k": "BOUNDARY",
                "c": "Wrong ArithmeticException behavior",
                "i": "Boundary contracts fail",
                "a": "Validate inputs; rerun failures",
            }
        ],
    }
    payload = validate_model_output(json.dumps(data), base)
    merged = merge_model_output(base, payload)
    assert merged["root_cause_groups"][0]["category"] == "BOUNDARY"
    assert merged["root_cause_groups"][0]["evidence"][0]["application_file"].endswith("Calculator.java")
    assert merged["release_gate"] == "BLOCK_RELEASE"

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
            "runtime_evidence": {
                "schema_version": "1.0",
                "framework": "maven-surefire",
                "command": "mvn test",
                "execution_status": "COMPLETED",
                "test_result": "NOT_RUN",
                "exit_code": 1,
                "duration_seconds": 6.5,
                "test_summary": {"total": 0, "passed": 0, "failed": 0, "skipped": 0, "errors": 0},
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


def test_maven_pretest_blocker_remains_fast_deterministic_path():
    result = build_base_analysis(build_maven_plugin_resolution_request())
    assert result["test_result"] == "NOT_RUN"
    assert result["release_gate"] == "REVIEW_REQUIRED"
    assert result["root_cause_groups"][0]["category"] == "BUILD_CONFIGURATION"
    assert should_use_llm(result) is False


def test_analyze_endpoint_uses_ai_reasoning_for_confirmed_failure(monkeypatch):
    monkeypatch.setattr(model_service, "enabled", True)
    monkeypatch.setattr(model_service, "model_name", "Qwen/Qwen3-1.7B-GGUF:Q5_K_M")
    monkeypatch.setattr(model_service, "generate", lambda messages: json.dumps(valid_model_payload()))
    response = analyze_logs(build_request())
    assert response.mode == "ai-reasoned-validated"
    assert response.model == "Qwen/Qwen3-1.7B-GGUF:Q5_K_M"
    assert response.root_cause_groups[0].category == "BOUNDARY"
    assert response.runtime_risk_level == "HIGH"
    assert response.release_gate == "BLOCK_RELEASE"


def test_analyze_endpoint_preserves_deterministic_fallback_on_ai_failure(monkeypatch):
    def fail_generation(messages):
        raise RuntimeError("simulated model failure")

    monkeypatch.setattr(model_service, "enabled", True)
    monkeypatch.setattr(model_service, "model_name", "Qwen/Qwen3-1.7B-GGUF:Q5_K_M")
    monkeypatch.setattr(model_service, "generate", fail_generation)
    response = analyze_logs(build_request())
    assert response.mode == "rule-based-fallback"
    assert response.test_result == "FAIL"
    assert response.release_gate == "BLOCK_RELEASE"
    assert response.run_summary["failed"] == 2
    assert "simulated model failure" in response.llm_error
