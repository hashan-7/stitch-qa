import importlib.util
import sys
import types
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[2]
CLIENT_PATH = ROOT / "cli" / "stitch_cli" / "agent_client.py"
REPORTER_PATH = ROOT / "cli" / "stitch_cli" / "reporter.py"
MAIN_PATH = ROOT / "cli" / "stitch_cli" / "main.py"


def load_reporter():
    spec = importlib.util.spec_from_file_location("stitch_reporter_v2", REPORTER_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def load_client():
    pkg = types.ModuleType("stitch_cli")
    pkg.__path__ = []
    sys.modules.setdefault("stitch_cli", pkg)

    code_cli = types.ModuleType("stitch_cli.code_cli")
    code_cli.call_code_agent = lambda *args, **kwargs: None
    code_cli.call_source_review_agent = lambda *args, **kwargs: None
    code_cli.call_repair_assurance_agent = lambda *args, **kwargs: None
    sys.modules["stitch_cli.code_cli"] = code_cli

    runtime_fallback = types.ModuleType("stitch_cli.runtime_fallback")
    runtime_fallback.build_client_runtime_fallback = lambda *args, **kwargs: {}
    sys.modules["stitch_cli.runtime_fallback"] = runtime_fallback

    spec = importlib.util.spec_from_file_location(
        "stitch_cli.agent_client",
        CLIENT_PATH,
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules["stitch_cli.agent_client"] = module
    spec.loader.exec_module(module)
    return module


def sample_repair_response():
    return {
        "agent_id": "defect-resolution-analyst",
        "display_name": "Defect Resolution Intelligence Analyst",
        "agent_version": "2.0",
        "agent": "repair-agent",
        "mode": "ai-reasoned-validated",
        "model": "ibm-granite/granite-4.0-1b-GGUF:Q4_K_M",
        "status": "COMPLETED",
        "overall_priority": "P1",
        "confidence": "HIGH",
        "repair_risk_level": "MEDIUM",
        "auto_apply": False,
        "summary": "Resolve the confirmed failure using the smallest safe change.",
        "stitch_repair_contracts": [
            {
                "contract_id": "STITCH-RC-001",
                "finding_refs": ["RQI-001"],
                "title": "Restore input handling",
                "priority": "P1",
                "priority_reason": "The runtime failure blocks a confirmed tested path.",
                "repair_objective": "Restore controlled invalid-input behavior.",
                "repair_strategy": "Add narrow validation at the affected boundary.",
                "change_boundary": "Input validation only.",
                "protected_behavior": "Preserve valid calculations.",
                "side_effect_risk": "MEDIUM",
                "verification": "Rerun the failed test and full regression suite.",
                "done_condition": "The expected behavior is restored without regression.",
                "status": "PENDING_VERIFICATION",
            }
        ],
        "current_knowledge_required": False,
        "current_knowledge_reason": None,
        "next_action": "Start with STITCH-RC-001.",
        "suggestions": ["Add narrow validation at the affected boundary."],
        "warnings": [],
        "limitations": ["No automatic code modification."],
        "llm_metrics": {"completion_tokens": 100},
        "llm_error": None,
    }


def source_review_data(risk="LOW"):
    return {
        "agent_id": "source-quality-analyst",
        "display_name": "Source Quality Intelligence Analyst",
        "agent_version": "3.0",
        "agent": "code-agent",
        "mode": "deterministic-validated",
        "model": None,
        "confidence": "HIGH",
        "status": "COMPLETED",
        "risk_level": risk,
        "release_recommendation": "READY_WITH_CAUTION",
        "findings_count": 1,
        "findings": [
            {
                "id": "SRC-001",
                "severity": "MEDIUM",
                "title": "Missing validation",
                "category": "RELIABILITY",
                "file_path": "app.py",
                "line": 10,
                "confidence": "HIGH",
                "evidence": "Division has no boundary guard.",
                "impact": "Invalid input can fail.",
                "recommendation": "Add targeted validation.",
            }
        ],
        "warnings": [],
        "limitations": [],
        "coverage": {
            "discovered_files_count": 1,
            "submitted_files_count": 1,
        },
    }


def passing_execution():
    return {
        "executed": True,
        "skipped": False,
        "success": True,
        "status": "PASSED",
        "command": "python -m pytest",
        "exit_code": 0,
        "stdout": "",
        "stderr": "",
        "failure_type": None,
        "help_message": None,
        "runtime_evidence": {
            "execution_status": "COMPLETED",
            "test_result": "PASS",
            "evidence_quality": "STRUCTURED",
            "test_summary": {
                "total": 4,
                "passed": 4,
                "failed": 0,
                "errors": 0,
                "skipped": 0,
            },
            "failures": [],
        },
    }


def test_normalize_repair_response_preserves_v2_contract():
    client = load_client()
    normalized = client.normalize_repair_agent_data(sample_repair_response())
    assert normalized["agent_id"] == "defect-resolution-analyst"
    assert normalized["overall_priority"] == "P1"
    assert normalized["repair_risk_level"] == "MEDIUM"
    assert normalized["stitch_repair_contracts"][0]["contract_id"] == "STITCH-RC-001"
    assert normalized["auto_apply"] is False


def test_repair_request_sends_runtime_and_source_evidence(monkeypatch):
    client = load_client()
    captured = {}

    class Response:
        def raise_for_status(self):
            return None

        def json(self):
            return sample_repair_response()

    def fake_post(url, json, timeout):
        captured["url"] = url
        captured["json"] = json
        captured["timeout"] = timeout
        return Response()

    monkeypatch.setattr(client.requests, "post", fake_post)
    scan_result = {"project_type": "Python Project"}
    execution = passing_execution()
    execution["success"] = False
    execution["exit_code"] = 1
    execution["stdout"] = "x" * 9000
    execution["runtime_evidence"]["test_result"] = "FAIL"
    execution["runtime_evidence"]["failures"] = [
        {
            "id": "FAIL-0001",
            "test_name": "test_divide",
            "exception_type": "ZeroDivisionError",
        }
    ]
    runtime_analysis = {
        "release_gate": "BLOCK_RELEASE",
        "root_cause_groups": [{"group_id": "RQI-001", "root_cause": "Cause"}],
    }

    result = client.suggest_repair_with_agent(
        "https://example.invalid",
        scan_result,
        execution,
        runtime_analysis,
        source_review_data(),
    )
    assert result["success"] is True
    payload = captured["json"]
    assert payload["runtime_analysis"]["release_gate"] == "BLOCK_RELEASE"
    assert payload["runtime_evidence"]["failures"][0]["id"] == "FAIL-0001"
    assert payload["source_review"]["findings"][0]["id"] == "SRC-001"
    assert len(payload["stdout"]) == client.MAX_REPAIR_AGENT_LOG_CHARS


def test_source_review_payload_caps_and_trims_evidence():
    client = load_client()
    review = source_review_data()
    review["findings"] = [
        {
            **review["findings"][0],
            "id": f"SRC-{index:03d}",
            "evidence": "e" * 2000,
        }
        for index in range(1, 105)
    ]
    payload = client.build_repair_source_review_payload(review)
    assert len(payload["findings"]) == client.MAX_REPAIR_SOURCE_FINDINGS
    assert len(payload["findings"][0]["evidence"]) <= 1000


def test_reporter_does_not_treat_repair_side_effect_risk_as_release_risk():
    reporter = load_reporter()
    repair = sample_repair_response()
    repair["repair_risk_level"] = "CRITICAL"
    repair["risk_level"] = "CRITICAL"
    decision = reporter.build_qa_decision(
        passing_execution(),
        source_review_data("LOW"),
        agent_data=None,
        repair_data=repair,
        code_data=None,
        workflow_context={"repair_requested": True},
    )
    assert decision["risk_level"] == "LOW"
    assert decision["status"] != "BLOCK_RELEASE"


def test_advisory_agent_unavailable_does_not_make_qa_evidence_incomplete():
    reporter = load_reporter()
    unavailable = {
        "status": "UNAVAILABLE",
        "repair_risk_level": "UNKNOWN",
        "risk_level": "UNKNOWN",
    }
    decision = reporter.build_qa_decision(
        passing_execution(),
        source_review_data("LOW"),
        agent_data=None,
        repair_data=unavailable,
        code_data=None,
        workflow_context={"repair_requested": True},
    )
    assert decision["completeness"] == "COMPLETE"
    assert decision["status"] != "QA_INCOMPLETE"


def test_repair_contracts_drive_top_level_next_actions():
    reporter = load_reporter()
    repair_json = reporter.build_repair_agent_json(sample_repair_response())
    decision = {
        "status": "BLOCK_RELEASE",
        "workflow_status": {},
    }
    execution = passing_execution()
    execution["runtime_evidence"]["test_result"] = "FAIL"
    actions = reporter.build_next_actions(
        decision,
        {"has_tests": True},
        source_review_data(),
        execution,
        {"required_actions": ["Old runtime action"]},
        repair_json,
    )
    contract_actions = [
        item for item in actions if item.get("source") == "defect-resolution-analyst"
    ]
    assert contract_actions
    assert contract_actions[0]["contract_id"] == "STITCH-RC-001"
    assert all(item.get("action") != "Old runtime action" for item in actions)


def test_report_json_preserves_repair_contract_and_schema_version():
    reporter = load_reporter()
    repair_json = reporter.build_repair_agent_json(sample_repair_response())
    assert reporter.REPORT_SCHEMA_VERSION == "3.3"
    assert repair_json["display_name"] == "Defect Resolution Intelligence Analyst"
    assert repair_json["stitch_repair_contracts"][0]["done_condition"]
    assert repair_json["auto_apply"] is False


def test_main_source_only_branch_runs_agent2_and_repair_assurance():
    text = MAIN_PATH.read_text(encoding="utf-8")
    no_tests = text.index('if not static_map.get(\n        "has_tests"\n    ):')
    execution_else = text.index('    else:\n        console.print(\n            "\\n[bold magenta]"\n            "Execution Started"', no_tests)
    block = text[no_tests:execution_else]
    assert "if repair_requested:" in block
    assert "suggest_repair_with_agent" in block
    assert "Repair Assurance Intelligence Analyst Started" in block
    assert "suggest_code_fix_with_agent" in block
    assert "source_review_data" in block
    assert "Runtime Quality Intelligence analysis was not run" in block


def test_combined_risk_preserves_critical_runtime_risk():
    reporter = load_reporter()
    execution = passing_execution()
    execution["success"] = False
    execution["status"] = "FAILED"
    execution["exit_code"] = 1
    execution["runtime_evidence"]["test_result"] = "FAIL"
    execution["runtime_evidence"]["execution_status"] = "COMPLETED"
    runtime_analysis = {
        "execution_status": "COMPLETED",
        "test_result": "FAIL",
        "release_gate": "BLOCK_RELEASE",
        "runtime_risk_level": "CRITICAL",
        "failure_origin": "APPLICATION_DEFECT",
        "final_status": "FAIL",
    }

    decision = reporter.build_qa_decision(
        execution,
        source_review_data("LOW"),
        agent_data=runtime_analysis,
        repair_data=sample_repair_response(),
        code_data=None,
        workflow_context={
            "analyze_requested": True,
            "repair_requested": True,
        },
    )

    assert decision["status"] == "BLOCK_RELEASE"
    assert decision["risk_level"] == "CRITICAL"
    assert decision["runtime_gate"]["runtime_risk_level"] == "CRITICAL"

def sample_repair_assurance_response():
    return {
        "agent_id": "repair-assurance-analyst",
        "display_name": "Repair Assurance Intelligence Analyst",
        "agent_version": "3.0",
        "agent": "code-agent",
        "mode": "ai-reasoned-validated",
        "model": "ibm-granite/granite-4.1-3b-GGUF:Q4_K_M",
        "status": "COMPLETED",
        "confidence": "HIGH",
        "risk_level": "MEDIUM",
        "auto_apply": False,
        "summary": "Prepared contract-bound repair assurance.",
        "guidance": [
            {
                "guidance_id": "RAI-001",
                "repair_contract_ref": "STITCH-RC-001",
                "finding_refs": ["RQI-001"],
                "target_files": ["app.py"],
                "target_symbols": ["divide"],
                "implementation_intent": "Restore the expected ValueError behavior.",
                "code_level_approach": "Add narrow input validation before division.",
                "change_boundary": "Input validation only.",
                "protected_behavior": "Preserve valid calculations.",
                "side_effect_considerations": "Avoid unrelated refactoring.",
                "targeted_verification": "Rerun the failing test.",
                "regression_verification": "Run the complete test suite.",
                "suggested_patch": None,
                "patch_validation_status": "NOT_GENERATED",
                "current_knowledge_required": False,
                "current_knowledge_reason": None,
                "status": "PENDING_IMPLEMENTATION",
            }
        ],
        "suggested_patch": None,
        "verification": "Run targeted and regression verification.",
        "current_knowledge_required": False,
        "current_knowledge_reason": None,
        "evidence_lineage": [
            {
                "repair_contract_ref": "STITCH-RC-001",
                "finding_refs": ["RQI-001"],
                "guidance_status": "LINKED",
            }
        ],
        "shadow_validation_status": "NOT_RUN",
        "warnings": [],
        "limitations": ["No automatic project modification."],
        "llm_metrics": {"completion_tokens": 120},
        "llm_error": None,
    }


def test_repair_assurance_payload_uses_contract_linked_source_file(monkeypatch, tmp_path):
    client = load_client()
    captured = {}
    project = tmp_path / "project"
    project.mkdir()
    (project / "app.py").write_text(
        "def divide(a, b):\n    return a / b\n",
        encoding="utf-8",
    )
    scan_result = {
        "project_type": "Python Project",
        "project_path": str(project),
        "source_review": {"source_files": ["app.py"]},
    }
    execution = passing_execution()
    execution["success"] = False
    execution["exit_code"] = 1
    runtime = {
        "root_cause_groups": [
            {
                "group_id": "RQI-001",
                "evidence": [
                    {
                        "application_file": "app.py",
                        "application_line": 2,
                    }
                ],
            }
        ]
    }
    review = source_review_data()
    repair = sample_repair_response()

    def fake_call(payload, code_agent_url):
        captured["payload"] = payload
        captured["url"] = code_agent_url
        return {
            "success": True,
            "data": sample_repair_assurance_response(),
            "error": None,
        }

    monkeypatch.setattr(client, "call_repair_assurance_agent", fake_call)
    result = client.suggest_code_fix_with_agent(
        "https://example.invalid",
        scan_result,
        execution,
        runtime,
        repair,
        review,
    )

    assert result["success"] is True
    payload = captured["payload"]
    assert payload["repair_plan"]["stitch_repair_contracts"][0]["contract_id"] == "STITCH-RC-001"
    assert payload["runtime_analysis"]["root_cause_groups"][0]["group_id"] == "RQI-001"
    assert payload["source_review"]["agent_id"] == "source-quality-analyst"
    assert payload["source_files"][0]["path"] == "app.py"
    assert "return a / b" in payload["source_files"][0]["content"]
    assert result["data"]["agent_id"] == "repair-assurance-analyst"
    assert result["data"]["guidance"][0]["repair_contract_ref"] == "STITCH-RC-001"


def test_repair_assurance_payload_supports_maven_when_main_file_is_absent(monkeypatch, tmp_path):
    client = load_client()
    project = tmp_path / "maven"
    source = project / "src" / "main" / "java" / "demo"
    source.mkdir(parents=True)
    java_path = source / "Calculator.java"
    java_path.write_text(
        "package demo; public class Calculator { int add(int a, int b) { return a + b; } }",
        encoding="utf-8",
    )
    scan_result = {
        "project_type": "Java Maven Project",
        "project_path": str(project),
        "static_map": {"main_file": None},
        "source_review": {
            "source_files": ["src/main/java/demo/Calculator.java"]
        },
    }
    execution = passing_execution()
    execution["command"] = "mvn test"
    repair = sample_repair_response()
    repair["stitch_repair_contracts"][0]["finding_refs"] = ["SRC-001"]
    review = source_review_data()
    review["findings"][0]["id"] = "SRC-001"
    review["findings"][0]["file_path"] = "src/main/java/demo/Calculator.java"
    captured = {}

    def fake_call(payload, code_agent_url):
        captured["payload"] = payload
        response = sample_repair_assurance_response()
        response["guidance"][0]["finding_refs"] = ["SRC-001"]
        response["guidance"][0]["target_files"] = [
            "src/main/java/demo/Calculator.java"
        ]
        return {"success": True, "data": response, "error": None}

    monkeypatch.setattr(client, "call_repair_assurance_agent", fake_call)
    result = client.suggest_code_fix_with_agent(
        "https://example.invalid",
        scan_result,
        execution,
        None,
        repair,
        review,
    )

    assert result["success"] is True
    assert captured["payload"]["source_files"][0]["path"] == "src/main/java/demo/Calculator.java"


def test_reporter_preserves_agent3_professional_contracts():
    reporter = load_reporter()
    source_json = reporter.build_source_review_json(source_review_data())
    assurance_json = reporter.build_code_agent_json(
        sample_repair_assurance_response()
    )

    assert source_json["agent_id"] == "source-quality-analyst"
    assert source_json["display_name"] == "Source Quality Intelligence Analyst"
    assert assurance_json["agent_id"] == "repair-assurance-analyst"
    assert assurance_json["display_name"] == "Repair Assurance Intelligence Analyst"
    assert assurance_json["guidance"][0]["repair_contract_ref"] == "STITCH-RC-001"
    assert assurance_json["shadow_validation_status"] == "NOT_RUN"
    assert assurance_json["auto_apply"] is False

