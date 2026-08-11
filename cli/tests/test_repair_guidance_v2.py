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
        "agent": "code-agent",
        "mode": "rule-based",
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
    assert reporter.REPORT_SCHEMA_VERSION == "3.2"
    assert repair_json["display_name"] == "Defect Resolution Intelligence Analyst"
    assert repair_json["stitch_repair_contracts"][0]["done_condition"]
    assert repair_json["auto_apply"] is False


def test_main_source_only_branch_can_invoke_agent2_from_source_findings():
    text = MAIN_PATH.read_text(encoding="utf-8")
    no_tests = text.index('if not static_map.get(\n        "has_tests"\n    ):')
    execution_else = text.index('    else:\n        console.print(\n            "\\n[bold magenta]"\n            "Execution Started"', no_tests)
    block = text[no_tests:execution_else]
    assert "if repair:" in block
    assert "suggest_repair_with_agent" in block
    assert "source_review_data" in block
    assert "Runtime Quality Intelligence analysis and Agent 3 runtime code guidance" in block
