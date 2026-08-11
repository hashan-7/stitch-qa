import importlib.util
import json
from pathlib import Path

import pytest


APP_PATH = Path(__file__).resolve().parents[1] / "app.py"
SPEC = importlib.util.spec_from_file_location("stitch_agent2_app", APP_PATH)
agent2 = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(agent2)


def runtime_group(group_id="RQI-001", severity="HIGH"):
    return {
        "group_id": group_id,
        "title": "Input validation failure",
        "category": "INPUT_VALIDATION",
        "failure_origin": "APPLICATION_DEFECT",
        "root_cause": "Invalid boundary input reaches division without controlled validation.",
        "runtime_impact": "The tested path terminates with an unexpected exception.",
        "required_action": "Add targeted validation and rerun the affected tests.",
        "affected_tests": ["tests/test_app.py::test_divide_rejects_zero"],
        "evidence": [
            {
                "failure_id": "FAIL-0001",
                "test_name": "tests/test_app.py::test_divide_rejects_zero",
                "expected": "ValueError",
                "actual": "ZeroDivisionError",
                "exception_type": "ZeroDivisionError",
                "exception_message": "division by zero",
                "application_file": "app.py",
                "application_line": 10,
                "test_file": "tests/test_app.py",
                "test_line": 16,
            }
        ],
    }


def source_finding(finding_id="SRC-001", severity="MEDIUM"):
    return {
        "id": finding_id,
        "severity": severity,
        "title": "Missing validation",
        "category": "RELIABILITY",
        "file_path": "app.py",
        "line": 10,
        "confidence": "HIGH",
        "evidence": "The function divides without guarding a zero denominator.",
        "impact": "Invalid inputs may terminate the workflow.",
        "recommendation": "Add validation at the input boundary.",
    }


def request_with_findings(include_source=True):
    source = {
        "status": "COMPLETED",
        "risk_level": "MEDIUM",
        "release_recommendation": "REVIEW_REQUIRED",
        "findings": [source_finding()] if include_source else [],
    }
    return agent2.RepairRequest.model_validate(
        {
            "project_type": "Python Project",
            "command": "python -m pytest",
            "success": False,
            "exit_code": 1,
            "runtime_analysis": {
                "test_result": "FAIL",
                "release_gate": "BLOCK_RELEASE",
                "runtime_risk_level": "HIGH",
                "diagnosis_confidence": "HIGH",
                "evidence_quality": "STRUCTURED",
                "root_cause_groups": [runtime_group()],
                "verification_steps": [
                    "Rerun the affected tests.",
                    "Run the complete regression suite.",
                ],
            },
            "source_review": source,
        }
    )


def valid_plan(refs=None, priority="P1"):
    refs = refs or ["RQI-001", "SRC-001"]
    return {
        "p": priority,
        "c": "HIGH",
        "k": False,
        "kr": "",
        "x": [
            {
                "f": refs,
                "p": priority,
                "w": "The confirmed failure blocks tested behavior and overlaps the source finding.",
                "o": "Restore controlled error behavior for invalid boundary inputs.",
                "s": "Add narrow validation before unsafe division while preserving valid calculations.",
                "b": "Limit changes to the affected input-validation path.",
                "q": "Keep successful arithmetic behavior unchanged for valid inputs.",
                "r": "L",
                "v": "Rerun the failing test, then execute the complete regression suite.",
            }
        ],
    }


def test_collects_runtime_and_source_findings():
    request = request_with_findings()
    findings = agent2.collect_locked_findings(request)
    assert [item["ref"] for item in findings] == ["RQI-001", "SRC-001"]
    assert findings[0]["locations"][0] == "app.py:10"
    assert findings[1]["locations"] == ["app.py:10"]


def test_no_findings_returns_no_repair_required():
    request = agent2.RepairRequest.model_validate(
        {
            "project_type": "Python Project",
            "command": "python -m pytest",
            "success": True,
            "exit_code": 0,
            "runtime_analysis": {"root_cause_groups": []},
            "source_review": {"findings": []},
        }
    )
    result = agent2.suggest_repair(request)
    assert result.status == "NO_REPAIR_REQUIRED"
    assert result.overall_priority == "NONE"
    assert result.auto_apply is False


def test_valid_ai_plan_is_grounded_and_keeps_p1_floor():
    request = request_with_findings()
    findings = agent2.collect_locked_findings(request)
    plan = agent2.parse_model_output(json.dumps(valid_plan(priority="P2")))
    plan = agent2.validate_plan(plan, request, findings)
    assert plan.overall_priority == "P1"
    merged = agent2.merge_model_plan(plan, request, findings)
    assert merged["mode"] == "ai-reasoned-validated"
    assert merged["overall_priority"] == "P1"
    assert merged["stitch_repair_contracts"][0]["finding_refs"] == [
        "RQI-001",
        "SRC-001",
    ]


def test_unknown_finding_reference_is_rejected():
    request = request_with_findings()
    findings = agent2.collect_locked_findings(request)
    payload = valid_plan(refs=["RQI-001", "UNKNOWN-1"])
    plan = agent2.parse_model_output(json.dumps(payload))
    with pytest.raises(ValueError, match="unknown finding"):
        agent2.validate_plan(plan, request, findings)


def test_omitted_confirmed_finding_is_rejected():
    request = request_with_findings()
    findings = agent2.collect_locked_findings(request)
    payload = valid_plan(refs=["RQI-001"])
    plan = agent2.parse_model_output(json.dumps(payload))
    with pytest.raises(ValueError, match="omitted confirmed findings"):
        agent2.validate_plan(plan, request, findings)


def test_duplicate_finding_across_contracts_is_rejected():
    request = request_with_findings(include_source=False)
    findings = agent2.collect_locked_findings(request)
    payload = valid_plan(refs=["RQI-001"])
    duplicate = dict(payload["x"][0])
    duplicate["w"] = "A second contract duplicates the same confirmed finding."
    payload["x"].append(duplicate)
    plan = agent2.parse_model_output(json.dumps(payload))
    with pytest.raises(ValueError, match="multiple repair contracts"):
        agent2.validate_plan(plan, request, findings)


def test_invented_file_line_reference_is_rejected():
    request = request_with_findings()
    findings = agent2.collect_locked_findings(request)
    payload = valid_plan()
    payload["x"][0]["s"] = (
        "Change invented.py:999 to fix the issue while preserving all working behavior."
    )
    plan = agent2.parse_model_output(json.dumps(payload))
    with pytest.raises(ValueError, match="unsupported file or line"):
        agent2.validate_plan(plan, request, findings)


def test_auto_modification_claim_is_rejected():
    request = request_with_findings()
    findings = agent2.collect_locked_findings(request)
    payload = valid_plan()
    payload["x"][0]["s"] = (
        "I modified the affected implementation automatically and prepared the remaining verification plan for the developer."
    )
    plan = agent2.parse_model_output(json.dumps(payload))
    with pytest.raises(ValueError, match="automatic project modification"):
        agent2.validate_plan(plan, request, findings)


def test_current_knowledge_flag_is_preserved():
    request = request_with_findings()
    findings = agent2.collect_locked_findings(request)
    payload = valid_plan()
    payload["k"] = True
    payload["kr"] = (
        "The repair depends on current framework compatibility documentation."
    )
    plan = agent2.validate_plan(
        agent2.parse_model_output(json.dumps(payload)),
        request,
        findings,
    )
    merged = agent2.merge_model_plan(plan, request, findings)
    assert merged["current_knowledge_required"] is True
    assert "compatibility" in merged["current_knowledge_reason"].lower()


def test_endpoint_uses_validated_ai_reasoning(monkeypatch):
    request = request_with_findings()
    monkeypatch.setattr(agent2.model_service, "enabled", True)
    monkeypatch.setattr(
        agent2.model_service,
        "generate",
        lambda messages: json.dumps(valid_plan()),
    )
    monkeypatch.setattr(
        agent2.model_service,
        "model_name",
        "ibm-granite/granite-4.0-1b-GGUF:Q4_K_M",
    )
    result = agent2.suggest_repair(request)
    assert result.mode == "ai-reasoned-validated"
    assert result.model == "ibm-granite/granite-4.0-1b-GGUF:Q4_K_M"
    assert result.stitch_repair_contracts[0].status == "PENDING_VERIFICATION"
    assert result.auto_apply is False


def test_endpoint_falls_back_safely_when_llm_fails(monkeypatch):
    request = request_with_findings()
    monkeypatch.setattr(agent2.model_service, "enabled", True)

    def fail(_messages):
        raise RuntimeError("model unavailable")

    monkeypatch.setattr(agent2.model_service, "generate", fail)
    result = agent2.suggest_repair(request)
    assert result.mode == "deterministic-fallback"
    assert result.llm_error is not None
    assert len(result.stitch_repair_contracts) == 2
    assert result.auto_apply is False


def test_runtime_evidence_can_drive_repair_without_agent1_analysis():
    request = agent2.RepairRequest.model_validate(
        {
            "project_type": "Python Project",
            "command": "python -m pytest",
            "success": False,
            "exit_code": 1,
            "runtime_evidence": {
                "test_result": "FAIL",
                "failures": [
                    {
                        "id": "FAIL-0001",
                        "test_name": "tests/test_app.py::test_divide_rejects_zero",
                        "expected": "ValueError",
                        "actual": "ZeroDivisionError",
                        "exception_type": "ZeroDivisionError",
                        "exception_message": "division by zero",
                        "application_file": "app.py",
                        "application_line": 10,
                    }
                ],
            },
            "source_review": {"findings": []},
        }
    )
    findings = agent2.collect_locked_findings(request)
    assert len(findings) == 1
    assert findings[0]["ref"] == "FAIL-0001"
    assert findings[0]["source"] == "runtime"


def test_source_only_findings_can_drive_agent2():
    request = agent2.RepairRequest.model_validate(
        {
            "project_type": "Python Project",
            "command": "python -m pytest",
            "success": False,
            "exit_code": 0,
            "failure_type": "PYTHON_TESTS_NOT_FOUND",
            "help_message": "No pytest-compatible test files were detected.",
            "source_review": {
                "status": "COMPLETED",
                "findings": [source_finding()],
            },
        }
    )
    findings = agent2.collect_locked_findings(request)
    assert [item["ref"] for item in findings] == ["SRC-001"]
    assert agent2.should_use_llm(findings) is agent2.model_service.enabled


def test_environment_only_blocker_uses_deterministic_plan(monkeypatch):
    request = agent2.RepairRequest.model_validate(
        {
            "project_type": "Java Maven Project",
            "command": "mvn test",
            "success": False,
            "exit_code": None,
            "failure_type": "MAVEN_NOT_AVAILABLE",
            "help_message": "Maven is not available in PATH.",
        }
    )
    monkeypatch.setattr(agent2.model_service, "enabled", True)
    findings = agent2.collect_locked_findings(request)
    assert findings[0]["source"] == "execution"
    assert agent2.should_use_llm(findings) is False
    result = agent2.suggest_repair(request)
    assert result.mode == "deterministic-validated"
    assert result.overall_priority == "P1"


def test_overflow_findings_are_not_silently_dropped():
    source_items = [
        source_finding(f"SRC-{index:03d}", "LOW")
        for index in range(1, 15)
    ]
    request = agent2.RepairRequest.model_validate(
        {
            "project_type": "Python Project",
            "command": "python -m pytest",
            "success": True,
            "exit_code": 0,
            "source_review": {"status": "COMPLETED", "findings": source_items},
        }
    )
    findings = agent2.collect_locked_findings(request)
    ai_findings, overflow = agent2.select_ai_findings(findings)
    assert len(ai_findings) == agent2.MAX_AI_FINDINGS
    assert len(overflow) == len(findings) - agent2.MAX_AI_FINDINGS

    payload = valid_plan(refs=[item["ref"] for item in ai_findings])
    payload["x"][0]["w"] = "These low-risk findings can be handled together within one bounded repair pass."
    plan = agent2.validate_plan(
        agent2.parse_model_output(json.dumps(payload)),
        request,
        ai_findings,
    )
    merged = agent2.merge_model_plan(plan, request, ai_findings, overflow)
    covered = {
        ref
        for contract in merged["stitch_repair_contracts"]
        for ref in contract["finding_refs"]
    }
    assert covered == {item["ref"] for item in findings}
    assert merged["warnings"]


def test_fallback_keeps_every_confirmed_finding():
    findings = [
        {
            "ref": f"SRC-{index:03d}",
            "source": "source",
            "severity": "LOW",
            "title": f"Finding {index}",
            "category": "QUALITY",
            "root_cause": "Evidence",
            "impact": "Impact",
            "recommendation": "Apply a targeted repair.",
            "locations": [],
            "evidence": [],
        }
        for index in range(1, 10)
    ]
    request = agent2.RepairRequest.model_validate(
        {
            "project_type": "Python Project",
            "command": "python -m pytest",
            "success": True,
            "exit_code": 0,
        }
    )
    result = agent2.build_fallback_plan(request, findings)
    assert len(result["stitch_repair_contracts"]) == len(findings)


def test_dependency_fallback_requests_current_knowledge_check():
    request = agent2.RepairRequest.model_validate(
        {
            "project_type": "Java Maven Project",
            "command": "mvn test",
            "success": False,
            "exit_code": 1,
        }
    )
    findings = [
        {
            "ref": "SRC-001",
            "source": "source",
            "severity": "MEDIUM",
            "title": "Deprecated dependency version",
            "category": "DEPENDENCY",
            "root_cause": "The configured dependency version may be incompatible.",
            "impact": "Build compatibility may be affected.",
            "recommendation": "Verify supported versions before changing configuration.",
            "locations": [],
            "evidence": [],
        }
    ]
    result = agent2.build_fallback_plan(request, findings)
    assert result["current_knowledge_required"] is True
    assert result["current_knowledge_reason"]


def test_model_schema_requires_compact_contract_objects():
    schema = agent2.MODEL_RESPONSE_SCHEMA
    assert schema["required"] == ["p", "c", "k", "kr", "x"]
    contract_schema = schema["properties"]["x"]["items"]
    assert contract_schema["required"] == ["f", "p", "w", "o", "s", "b", "q", "r", "v"]
    assert contract_schema["properties"]["f"]["minItems"] == 1
    assert contract_schema["properties"]["f"]["maxItems"] == agent2.MAX_AI_FINDINGS
    assert contract_schema["additionalProperties"] is False


def test_model_service_uses_json_schema_and_stops_on_complete_json():
    payload = json.dumps(valid_plan(), separators=(",", ":"))
    captured = {}

    class FakeModel:
        def tokenize(self, value, add_bos=False, special=True):
            return list(range(max(1, len(value) // 8)))

        def create_chat_completion(self, **kwargs):
            captured.update(kwargs)
            yield {
                "choices": [
                    {
                        "delta": {"content": payload},
                        "finish_reason": None,
                    }
                ]
            }

    service = agent2.ModelService()
    service.model = FakeModel()
    service.model_name = service.primary_model
    service.max_input_tokens = 10000
    text = service.generate(
        [
            {"role": "system", "content": "Return JSON."},
            {"role": "user", "content": "Plan repair."},
        ]
    )
    assert json.loads(text) == valid_plan()
    assert captured["response_format"]["type"] == "json_object"
    assert captured["response_format"]["schema"] == agent2.MODEL_RESPONSE_SCHEMA
    assert service.last_generation["finish_reason"] == "json_complete"


def test_model_service_default_initialization_contract(monkeypatch):
    monkeypatch.delenv("HF_MODEL_REVISION", raising=False)
    service = agent2.ModelService()
    assert service.model_repo == "ibm-granite/granite-4.0-1b-GGUF"
    assert service.model_file == "granite-4.0-1b-Q4_K_M.gguf"
    assert service.model_revision == "b27c2fe3f211b7f44e80fa620177aea371099aaa"
    assert service.quantization == "Q4_K_M"



def test_runtime_evidence_does_not_create_duplicate_execution_blocker():
    request = agent2.RepairRequest.model_validate(
        {
            "project_type": "Python Project",
            "command": "python -m pytest",
            "success": False,
            "exit_code": 1,
            "failure_type": "EXECUTION_ERROR",
            "help_message": "Execution returned a failing result.",
            "runtime_evidence": {
                "test_result": "FAIL",
                "failures": [
                    {
                        "id": "FAIL-0001",
                        "test_name": "tests/test_app.py::test_failure",
                        "exception_type": "ValueError",
                        "application_file": "app.py",
                        "application_line": 8,
                    }
                ],
            },
        }
    )
    findings = agent2.collect_locked_findings(request)
    assert [item["source"] for item in findings] == ["runtime"]
    assert [item["ref"] for item in findings] == ["FAIL-0001"]


def test_runtime_failure_without_agent1_clamps_ai_contract_and_overall_priority():
    request = agent2.RepairRequest.model_validate(
        {
            "project_type": "Python Project",
            "command": "python -m pytest",
            "success": False,
            "exit_code": 1,
            "runtime_evidence": {
                "test_result": "FAIL",
                "failures": [
                    {
                        "id": "FAIL-0001",
                        "test_name": "tests/test_app.py::test_failure",
                        "expected": "ValueError",
                        "actual": "ZeroDivisionError",
                        "exception_type": "ZeroDivisionError",
                        "application_file": "app.py",
                        "application_line": 10,
                    }
                ],
            },
        }
    )
    findings = agent2.collect_locked_findings(request)
    payload = valid_plan(refs=["FAIL-0001"], priority="P3")
    plan = agent2.validate_plan(agent2.parse_model_output(json.dumps(payload)), request, findings)
    assert plan.contracts[0].priority == "P1"
    assert plan.overall_priority == "P1"


def test_current_knowledge_guard_applies_even_when_ai_says_false():
    request = agent2.RepairRequest.model_validate(
        {
            "project_type": "Java Maven Project",
            "command": "mvn test",
            "success": True,
            "exit_code": 0,
        }
    )
    findings = [
        {
            "ref": "SRC-001",
            "source": "source",
            "severity": "MEDIUM",
            "title": "Deprecated dependency version",
            "category": "DEPENDENCY",
            "root_cause": "A deprecated dependency may have changed compatibility requirements.",
            "impact": "Future builds may be affected.",
            "recommendation": "Verify the current supported dependency version before changing configuration.",
            "locations": [],
            "evidence": [],
        }
    ]
    payload = valid_plan(refs=["SRC-001"], priority="P2")
    payload["k"] = False
    payload["kr"] = ""
    plan = agent2.validate_plan(agent2.parse_model_output(json.dumps(payload)), request, findings)
    merged = agent2.merge_model_plan(plan, request, findings)
    assert merged["current_knowledge_required"] is True
    assert merged["current_knowledge_reason"]


def test_repair_contracts_are_sorted_and_renumbered_by_priority():
    contracts = [
        {"contract_id": "STITCH-RC-001", "priority": "P3"},
        {"contract_id": "STITCH-RC-002", "priority": "P1"},
        {"contract_id": "STITCH-RC-003", "priority": "P2"},
    ]
    ordered = agent2.sort_and_renumber_contracts(contracts)
    assert [item["priority"] for item in ordered] == ["P1", "P2", "P3"]
    assert [item["contract_id"] for item in ordered] == [
        "STITCH-RC-001",
        "STITCH-RC-002",
        "STITCH-RC-003",
    ]


def test_failed_execution_without_grounded_finding_does_not_claim_no_repair_needed():
    request = agent2.RepairRequest.model_validate(
        {
            "project_type": "Python Project",
            "command": "python -m pytest",
            "success": False,
            "exit_code": 1,
        }
    )
    result = agent2.build_fallback_plan(request, [])
    assert result["status"] == "NO_CONFIRMED_REPAIR_TARGET"
    assert "no source change should be guessed" in result["summary"].lower()



def test_passing_runtime_warning_is_preserved_as_repair_follow_up():
    warning = (
        "Mockito dynamic loading of agents was detected; future JDK versions may require explicit Java agent configuration."
    )
    request = agent2.RepairRequest.model_validate(
        {
            "project_type": "Java Maven Project",
            "command": "mvn test",
            "success": True,
            "exit_code": 0,
            "runtime_analysis": {
                "test_result": "PASS",
                "release_gate": "ALLOW_WITH_WARNINGS",
                "runtime_risk_level": "MEDIUM",
                "warnings": [warning],
                "root_cause_groups": [],
            },
            "runtime_evidence": {
                "test_result": "PASS",
                "warnings": [warning],
                "failures": [],
            },
        }
    )
    findings = agent2.collect_locked_findings(request)
    assert len(findings) == 1
    assert findings[0]["ref"] == "RWI-001"
    assert findings[0]["category"] == "RUNTIME_WARNING"
    assert findings[0]["severity"] == "MEDIUM"
    fallback = agent2.build_fallback_plan(request, findings)
    assert fallback["overall_priority"] == "P2"
    assert fallback["current_knowledge_required"] is True

