import importlib.util
import json
from pathlib import Path

import pytest


APP_PATH = Path(__file__).resolve().parents[1] / "app.py"
SPEC = importlib.util.spec_from_file_location("stitch_agent3_app", APP_PATH)
agent3 = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(agent3)


def source_request(project_type, path, content, has_tests=True):
    return agent3.SourceReviewRequest.model_validate(
        {
            "project_type": project_type,
            "has_tests": has_tests,
            "files": [
                {
                    "path": path,
                    "content": content,
                    "truncated": False,
                    "original_chars": len(content),
                }
            ],
            "discovered_files_count": 1,
            "submitted_files_count": 1,
            "submitted_chars": len(content),
        }
    )


def runtime_contract():
    return {
        "contract_id": "STITCH-RC-001",
        "finding_refs": ["RQI-001"],
        "title": "Repair contract for RQI-001",
        "priority": "P1",
        "priority_reason": "Validated runtime failures block the tested behavior.",
        "repair_objective": "Restore the expected ValueError behavior for invalid division inputs.",
        "repair_strategy": "Add targeted input validation before division and preserve valid calculations.",
        "change_boundary": "Limit changes to app.py:10 and app.py:14; avoid unrelated refactoring.",
        "protected_behavior": "Preserve valid division, valid averaging, and currently passing tests.",
        "side_effect_risk": "MEDIUM",
        "verification": "Rerun the affected tests, then run the complete test suite and confirm no new failures.",
        "done_condition": "The affected tests pass and the full suite has no regression.",
        "status": "PENDING_VERIFICATION",
    }


def environment_contract():
    return {
        "contract_id": "STITCH-RC-001",
        "finding_refs": ["RQI-001"],
        "title": "Repair contract for RQI-001",
        "priority": "P3",
        "priority_reason": "Runtime validation could not start because Maven is not installed or available in PATH.",
        "repair_objective": "Restore the execution capability required to run mvn test.",
        "repair_strategy": "Resolve only the environment or build-tool availability problem and do not modify application source code.",
        "change_boundary": "Limit changes to build-tool availability, environment configuration, or Maven Wrapper files; keep application source code outside this repair.",
        "protected_behavior": "Preserve application source and test behavior while restoring the environment needed to execute the existing test workflow.",
        "side_effect_risk": "MEDIUM",
        "verification": "Confirm mvn test can start and rerun Stitch QA to obtain runtime evidence.",
        "done_condition": "The validated Maven command starts successfully and runtime evidence is produced.",
        "status": "PENDING_VERIFICATION",
    }


def missing_tests_contract():
    return {
        "contract_id": "STITCH-RC-001",
        "finding_refs": ["SQ-SRC-001"],
        "title": "Repair contract for SQ-SRC-001",
        "priority": "P2",
        "priority_reason": "The MEDIUM source finding confirms that no automated tests were detected.",
        "repair_objective": "Add a focused automated test suite without changing production behavior solely to satisfy the missing-tests finding.",
        "repair_strategy": "Add focused tests using the detected project test conventions; keep production code unchanged unless a separate validated finding requires a source repair.",
        "change_boundary": "Limit changes to test files and test configuration needed for discovery and execution; do not modify application behavior unless a separate validated finding requires it.",
        "protected_behavior": "Preserve existing application behavior while adding tests; do not introduce production-code changes solely to resolve the missing-tests finding.",
        "side_effect_risk": "MEDIUM",
        "verification": "Confirm the new tests are discovered, execute them, then run all existing project checks and verify no regression.",
        "done_condition": "Automated tests are discovered and execute successfully while application behavior remains unchanged.",
        "status": "PENDING_VERIFICATION",
    }


def test_source_quality_python_deterministic_findings_and_missing_tests(monkeypatch):
    monkeypatch.setattr(agent3.model_service, "enabled", False)
    content = 'password = "production-secret"\n\ndef run(value):\n    return eval(value)\n'
    request = source_request("Python Project", "app.py", content, has_tests=False)
    result = agent3.review_source_request(request)

    assert result["agent_id"] == "source-quality-analyst"
    assert result["display_name"] == "Source Quality Intelligence Analyst"
    assert result["status"] == "COMPLETED"
    assert result["mode"] == "deterministic-validated"
    assert result["risk_level"] == "HIGH"
    assert result["release_recommendation"] == "BLOCK_RELEASE"
    assert result["findings_count"] == 3
    assert [item["id"] for item in result["findings"]] == [
        "SQ-SRC-001",
        "SQ-SRC-002",
        "SQ-SRC-003",
    ]
    assert {item["title"] for item in result["findings"]} == {
        "Possible hardcoded credential",
        "Dynamic code execution",
        "No automated tests detected",
    }


def test_source_quality_java_maven_detects_runtime_command_execution(monkeypatch):
    monkeypatch.setattr(agent3.model_service, "enabled", False)
    content = (
        "public class Runner {\n"
        "    public void run(String command) throws Exception {\n"
        "        Runtime.getRuntime().exec(command);\n"
        "    }\n"
        "}\n"
    )
    request = source_request(
        "Java Maven Project",
        "src/main/java/example/Runner.java",
        content,
        has_tests=True,
    )
    result = agent3.review_source_request(request)

    assert result["findings_count"] == 1
    finding = result["findings"][0]
    assert finding["title"] == "Runtime command execution"
    assert finding["severity"] == "HIGH"
    assert finding["file_path"] == "src/main/java/example/Runner.java"
    assert finding["line"] == 3


def test_source_quality_detects_zero_divisor_validation_risks(monkeypatch):
    monkeypatch.setattr(agent3.model_service, "enabled", False)
    content = (
        "def divide(a, b):\n"
        "    return a / b\n\n"
        "def average(values):\n"
        "    return sum(values) / len(values)\n"
    )
    request = source_request("Python Project", "app.py", content, has_tests=True)
    result = agent3.review_source_request(request)

    assert result["findings_count"] == 2
    assert {item["title"] for item in result["findings"]} == {
        "Potential unguarded divisor",
        "Potential empty-collection divisor",
    }
    assert {item["line"] for item in result["findings"]} == {2, 5}
    assert result["risk_level"] == "MEDIUM"


def test_source_ai_finding_is_file_line_grounded_and_high_is_clamped(monkeypatch):
    monkeypatch.setattr(agent3.model_service, "enabled", True)
    content = "def ratio(value, total):\n    return value / total\n"
    request = source_request("Python Project", "app.py", content, has_tests=True)

    payload = {
        "c": "HIGH",
        "x": [
            {
                "f": "app.py",
                "l": 2,
                "g": "reliability",
                "s": "HIGH",
                "t": "Possible missing denominator validation",
                "i": "A zero denominator could raise an unexpected exception.",
                "r": "Validate the denominator according to the documented input contract.",
                "k": False,
                "kr": "",
            }
        ],
    }
    monkeypatch.setattr(
        agent3.model_service,
        "generate_json",
        lambda *args, **kwargs: json.dumps(payload),
    )
    result = agent3.review_source_request(request)

    assert result["mode"] == "hybrid-ai-validated"
    assert result["confidence"] == "HIGH"
    assert result["findings_count"] == 2
    titles = {item["title"] for item in result["findings"]}
    assert "Potential unguarded divisor" in titles
    finding = next(item for item in result["findings"] if item["detector"] == "ai-contextual-validated")
    assert finding["file_path"] == "app.py"
    assert finding["line"] == 2
    assert finding["severity"] == "MEDIUM"
    assert finding["evidence"] == "return value / total"


def test_source_ai_unknown_location_is_discarded(monkeypatch):
    monkeypatch.setattr(agent3.model_service, "enabled", True)
    request = source_request(
        "Python Project",
        "app.py",
        "def add(a, b):\n    return a + b\n",
        has_tests=True,
    )
    payload = {
        "c": "HIGH",
        "x": [
            {
                "f": "invented.py",
                "l": 999,
                "g": "correctness",
                "s": "HIGH",
                "t": "Invented source defect",
                "i": "This issue is not grounded in supplied source evidence.",
                "r": "Change an invented file that is not part of the project.",
                "k": False,
                "kr": "",
            }
        ],
    }
    monkeypatch.setattr(
        agent3.model_service,
        "generate_json",
        lambda *args, **kwargs: json.dumps(payload),
    )
    result = agent3.review_source_request(request)

    assert result["findings_count"] == 0
    assert result["risk_level"] == "LOW"


def test_repair_assurance_without_agent2_contract_is_not_required(monkeypatch):
    monkeypatch.setattr(agent3.model_service, "enabled", False)
    request = agent3.RepairAssuranceRequest.model_validate(
        {
            "project_type": "Python Project",
            "command": "python -m pytest",
            "repair_plan": {"stitch_repair_contracts": []},
        }
    )
    result = agent3.repair_assurance_request(request)

    assert result["status"] == "NOT_REQUIRED"
    assert result["guidance"] == []
    assert result["auto_apply"] is False


def test_environment_contract_never_proposes_application_source_change(monkeypatch):
    monkeypatch.setattr(agent3.model_service, "enabled", False)
    request = agent3.RepairAssuranceRequest.model_validate(
        {
            "project_type": "Java Maven Project",
            "command": "mvn test",
            "success": False,
            "failure_type": "MAVEN_NOT_AVAILABLE",
            "repair_plan": {
                "stitch_repair_contracts": [environment_contract()]
            },
            "source_files": [
                {
                    "path": "src/main/java/example/Calculator.java",
                    "content": "public class Calculator {}",
                }
            ],
        }
    )
    result = agent3.repair_assurance_request(request)
    item = result["guidance"][0]

    assert result["status"] == "COMPLETED"
    assert result["mode"] == "deterministic-validated"
    assert item["status"] == "NO_CODE_CHANGE_REQUIRED"
    assert item["target_files"] == []
    assert item["suggested_patch"] is None
    assert "No application source change" in item["code_level_approach"]
    assert result["auto_apply"] is False
    assert result["current_knowledge_required"] is False


def test_testing_only_contract_is_bounded_to_tests(monkeypatch):
    monkeypatch.setattr(agent3.model_service, "enabled", False)
    source_review = {
        "status": "COMPLETED",
        "findings": [
            {
                "id": "SQ-SRC-001",
                "file_path": None,
                "line": None,
                "severity": "MEDIUM",
                "category": "testing",
                "title": "No automated tests detected",
            }
        ],
    }
    request = agent3.RepairAssuranceRequest.model_validate(
        {
            "project_type": "Python Project",
            "command": "python -m pytest",
            "source_review": source_review,
            "repair_plan": {
                "stitch_repair_contracts": [missing_tests_contract()]
            },
            "source_files": [
                {
                    "path": "app.py",
                    "content": "def add(a, b):\n    return a + b\n",
                }
            ],
        }
    )
    result = agent3.repair_assurance_request(request)
    item = result["guidance"][0]

    assert item["target_files"] == []
    assert "Add focused automated tests" in item["code_level_approach"]
    assert item["change_boundary"] == missing_tests_contract()["change_boundary"]
    assert item["protected_behavior"] == missing_tests_contract()["protected_behavior"]
    assert item["patch_validation_status"] == "NOT_GENERATED"
    assert result["auto_apply"] is False


def test_ai_repair_guidance_cannot_escape_contract_file_boundary(monkeypatch):
    monkeypatch.setattr(agent3.model_service, "enabled", True)
    runtime_analysis = {
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
    request = agent3.RepairAssuranceRequest.model_validate(
        {
            "project_type": "Python Project",
            "command": "python -m pytest",
            "success": False,
            "exit_code": 1,
            "runtime_analysis": runtime_analysis,
            "repair_plan": {
                "stitch_repair_contracts": [runtime_contract()]
            },
            "source_files": [
                {
                    "path": "app.py",
                    "content": (
                        "def divide(a, b):\n"
                        "    return a / b\n\n"
                        "def average(values):\n"
                        "    return sum(values) / len(values)\n"
                    ),
                }
            ],
        }
    )
    payload = {
        "c": "HIGH",
        "x": [
            {
                "r": "STITCH-RC-001",
                "f": ["RQI-001"],
                "t": ["invented.py"],
                "y": "invented_symbol",
                "i": "Restore the expected ValueError contract for invalid inputs.",
                "a": "Add explicit guards before the two divisions and raise ValueError for the validated invalid inputs.",
                "e": "Keep valid calculations unchanged and avoid unrelated refactoring.",
                "v": "Rerun the two affected failing tests and confirm they pass.",
                "g": "Run the complete pytest suite and confirm no new failures.",
                "k": True,
                "kr": "Current framework compatibility documentation is required.",
            }
        ],
    }
    monkeypatch.setattr(
        agent3.model_service,
        "generate_json",
        lambda *args, **kwargs: json.dumps(payload),
    )
    result = agent3.repair_assurance_request(request)
    item = result["guidance"][0]

    assert result["mode"] == "ai-reasoned-validated"
    assert item["target_files"] == ["app.py"]
    assert item["target_symbols"] == ["divide"]
    assert item["change_boundary"] == runtime_contract()["change_boundary"]
    assert item["protected_behavior"] == runtime_contract()["protected_behavior"]
    assert item["current_knowledge_required"] is False
    assert result["current_knowledge_required"] is False
    assert item["patch_validation_status"] == "NOT_GENERATED"


def test_deterministic_repair_guidance_targets_only_evidence_symbols(monkeypatch):
    monkeypatch.setattr(agent3.model_service, "enabled", False)
    runtime_analysis = {
        "root_cause_groups": [
            {
                "group_id": "RQI-001",
                "evidence": [
                    {"application_file": "app.py", "application_line": 5},
                    {"application_file": "app.py", "application_line": 8},
                ],
            }
        ]
    }
    request = agent3.RepairAssuranceRequest.model_validate(
        {
            "project_type": "Python Project",
            "command": "python -m pytest",
            "success": False,
            "exit_code": 1,
            "runtime_analysis": runtime_analysis,
            "repair_plan": {"stitch_repair_contracts": [runtime_contract()]},
            "source_files": [
                {
                    "path": "app.py",
                    "content": (
                        "def add(a, b):\n"
                        "    return a + b\n\n"
                        "def divide(a, b):\n"
                        "    return a / b\n\n"
                        "def average(values):\n"
                        "    return sum(values) / len(values)\n\n"
                        "def multiply(a, b):\n"
                        "    return a * b\n"
                    ),
                }
            ],
        }
    )
    result = agent3.repair_assurance_request(request)
    item = result["guidance"][0]

    assert result["mode"] == "deterministic-validated"
    assert item["target_files"] == ["app.py"]
    assert item["target_symbols"] == ["divide", "average"]


def test_health_exposes_both_agent3_roles_and_qwen_coder_default():
    status = agent3.health_check()
    capabilities = {item["agent_id"] for item in status["capabilities"]}

    assert capabilities == {
        "source-quality-analyst",
        "repair-assurance-analyst",
    }
    assert status["supported_project_types"] == [
        "Python Project",
        "Java Maven Project",
    ]
    assert agent3.model_service.model_repo == "Qwen/Qwen2.5-Coder-1.5B-Instruct-GGUF"
    assert agent3.model_service.model_file == "qwen2.5-coder-1.5b-instruct-q4_k_m.gguf"
    assert agent3.model_service.model_revision == "main"
    assert agent3.model_service.quantization == "Q4_K_M"


def test_model_service_uses_json_schema_and_stops_on_complete_json():
    payload = json.dumps({"c": "HIGH", "x": []}, separators=(",", ":"))
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

    service = agent3.ModelService()
    service.model = FakeModel()
    service.model_name = service.primary_model
    service.max_input_tokens = 10000
    text = service.generate_json(
        [
            {"role": "system", "content": "Return JSON."},
            {"role": "user", "content": "Review source."},
        ],
        agent3.SOURCE_AI_SCHEMA,
        200,
        "source-quality",
    )

    assert json.loads(text) == {"c": "HIGH", "x": []}
    assert captured["response_format"]["type"] == "json_object"
    assert captured["response_format"]["schema"] == agent3.SOURCE_AI_SCHEMA
    assert captured["stream"] is True
    assert service.last_generation["finish_reason"] == "json_complete"


def test_model_service_resets_state_across_sequential_generations():
    payload = json.dumps({"c": "HIGH", "x": []}, separators=(",", ":"))

    class StatefulFakeModel:
        def __init__(self):
            self.dirty = False
            self.reset_calls = 0
            self.generation_calls = 0

        def tokenize(self, value, add_bos=False, special=True):
            return list(range(max(1, len(value) // 8)))

        def reset(self):
            self.reset_calls += 1
            self.dirty = False

        def create_chat_completion(self, **kwargs):
            if self.dirty:
                raise RuntimeError("stale inference context")
            self.dirty = True
            self.generation_calls += 1
            yield {
                "choices": [
                    {
                        "delta": {"content": payload},
                        "finish_reason": None,
                    }
                ]
            }

    model = StatefulFakeModel()
    service = agent3.ModelService()
    service.model = model
    service.model_name = service.primary_model
    service.max_input_tokens = 10000
    messages = [
        {"role": "system", "content": "Return JSON."},
        {"role": "user", "content": "Review source."},
    ]

    first = service.generate_json(
        messages,
        agent3.SOURCE_AI_SCHEMA,
        200,
        "source-quality",
    )
    second = service.generate_json(
        messages,
        agent3.SOURCE_AI_SCHEMA,
        200,
        "repair-assurance",
    )

    assert json.loads(first) == {"c": "HIGH", "x": []}
    assert json.loads(second) == {"c": "HIGH", "x": []}
    assert model.generation_calls == 2
    assert model.reset_calls == 4


def test_model_service_resets_state_after_generation_failure():
    payload = json.dumps({"c": "HIGH", "x": []}, separators=(",", ":"))

    class RecoveringFakeModel:
        def __init__(self):
            self.dirty = False
            self.reset_calls = 0
            self.fail_next = True

        def tokenize(self, value, add_bos=False, special=True):
            return list(range(max(1, len(value) // 8)))

        def reset(self):
            self.reset_calls += 1
            self.dirty = False

        def create_chat_completion(self, **kwargs):
            if self.dirty:
                raise RuntimeError("stale inference context")
            self.dirty = True
            if self.fail_next:
                self.fail_next = False
                raise RuntimeError("simulated generation failure")
            yield {
                "choices": [
                    {
                        "delta": {"content": payload},
                        "finish_reason": None,
                    }
                ]
            }

    model = RecoveringFakeModel()
    service = agent3.ModelService()
    service.model = model
    service.model_name = service.primary_model
    service.max_input_tokens = 10000
    messages = [
        {"role": "system", "content": "Return JSON."},
        {"role": "user", "content": "Review source."},
    ]

    with pytest.raises(RuntimeError, match="simulated generation failure"):
        service.generate_json(
            messages,
            agent3.SOURCE_AI_SCHEMA,
            200,
            "source-quality",
        )

    recovered = service.generate_json(
        messages,
        agent3.SOURCE_AI_SCHEMA,
        200,
        "repair-assurance",
    )

    assert json.loads(recovered) == {"c": "HIGH", "x": []}
    assert model.reset_calls == 4



def test_repair_payload_keeps_only_contract_linked_evidence():
    runtime_analysis = {
        "summary": "duplicate runtime summary that should not be sent",
        "root_cause_groups": [
            {
                "group_id": "RQI-001",
                "category": "INPUT_VALIDATION",
                "root_cause": "Validated missing boundary validation.",
                "runtime_impact": "Two tested paths fail.",
                "required_action": "Add narrow validation.",
                "affected_tests": ["test_divide"],
                "evidence": [
                    {
                        "test_name": "test_divide",
                        "application_file": "app.py",
                        "application_line": 2,
                        "expected": "ValueError",
                        "actual": "ZeroDivisionError",
                    }
                ],
            },
            {
                "group_id": "RQI-999",
                "category": "OTHER",
                "root_cause": "Unrelated runtime group.",
                "evidence": [],
            },
        ],
    }
    source_review = {
        "status": "COMPLETED",
        "risk_level": "MEDIUM",
        "findings": [
            {
                "id": "SQ-SRC-001",
                "file_path": "app.py",
                "line": 2,
                "category": "reliability",
                "severity": "MEDIUM",
                "title": "Linked source evidence",
            },
            {
                "id": "SQ-SRC-999",
                "file_path": "other.py",
                "line": 1,
                "category": "other",
                "severity": "LOW",
                "title": "Unrelated source evidence",
            },
        ],
    }
    contract = runtime_contract()
    contract["finding_refs"] = ["RQI-001", "SQ-SRC-001"]
    content = "def divide(a, b):\n    return a / b\n" + "x = 1\n" * 5000
    request = agent3.RepairAssuranceRequest.model_validate(
        {
            "project_type": "Python Project",
            "command": "python -m pytest",
            "success": False,
            "exit_code": 1,
            "runtime_analysis": runtime_analysis,
            "source_review": source_review,
            "repair_plan": {"stitch_repair_contracts": [contract]},
            "source_files": [{"path": "app.py", "content": content}],
        }
    )
    contracts = agent3.repair_contracts_from_request(request)
    payload = agent3.repair_payload(request, contracts)

    assert "runtime_analysis" not in payload
    assert "source_review" not in payload
    assert [item["id"] for item in payload["runtime_groups"]] == ["RQI-001"]
    assert [item["id"] for item in payload["source_findings"]] == ["SQ-SRC-001"]
    assert len(payload["source_files"]) == 1
    assert len(payload["source_files"][0]["content"]) <= agent3.MAX_SOURCE_CONTEXT_CHARS
    assert payload["contracts"][0]["id"] == "STITCH-RC-001"


def test_repair_assurance_uses_task_specific_input_budget(monkeypatch):
    monkeypatch.setattr(agent3.model_service, "enabled", True)
    captured = {}
    request = agent3.RepairAssuranceRequest.model_validate(
        {
            "project_type": "Python Project",
            "command": "python -m pytest",
            "success": False,
            "exit_code": 1,
            "runtime_analysis": {
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
            },
            "repair_plan": {"stitch_repair_contracts": [runtime_contract()]},
            "source_files": [
                {
                    "path": "app.py",
                    "content": "def divide(a, b):\n    return a / b\n",
                }
            ],
        }
    )
    payload = {
        "c": "HIGH",
        "x": [
            {
                "r": "STITCH-RC-001",
                "f": ["RQI-001"],
                "t": ["app.py"],
                "y": "divide",
                "i": "Restore controlled invalid-input behavior.",
                "a": "Add narrow validation before the unsafe division.",
                "e": "Preserve valid calculations and avoid unrelated refactoring.",
                "v": "Rerun the affected test and confirm the expected behavior.",
                "g": "Run the complete suite and confirm no new failures.",
                "k": False,
                "kr": "",
            }
        ],
    }

    def fake_generate(*args):
        captured["args"] = args
        return json.dumps(payload)

    monkeypatch.setattr(agent3.model_service, "generate_json", fake_generate)
    result = agent3.repair_assurance_request(request)

    assert result["status"] == "COMPLETED"
    assert result["mode"] == "ai-reasoned-validated"
    assert captured["args"][4] == agent3.model_service.repair_max_input_tokens
    assert captured["args"][5] is False
    assert result["guidance"][0]["suggested_patch"] is None
    assert result["guidance"][0]["patch_validation_status"] == "NOT_GENERATED"


def test_model_service_repair_mode_uses_json_object_without_schema():
    payload = json.dumps({"c": "HIGH", "x": []}, separators=(",", ":"))
    captured = {}

    class FakeModel:
        def reset(self):
            return None

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

    service = agent3.ModelService()
    service.model = FakeModel()
    service.model_name = service.primary_model
    service.max_input_tokens = 10000
    text = service.generate_json(
        [
            {"role": "system", "content": "Return JSON."},
            {"role": "user", "content": "Return repair guidance."},
        ],
        agent3.REPAIR_AI_SCHEMA,
        200,
        "repair-assurance",
        2200,
        False,
    )

    assert json.loads(text) == {"c": "HIGH", "x": []}
    assert captured["response_format"] == {"type": "json_object"}


def test_model_service_recovers_json_object_from_wrapped_output():
    payload = 'Here is the JSON:\n```json\n{"c":"HIGH","x":[]}\n```'
    captured = {}

    class FakeModel:
        def reset(self):
            return None

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

    service = agent3.ModelService()
    service.model = FakeModel()
    service.model_name = service.primary_model
    service.max_input_tokens = 10000
    text = service.generate_json(
        [
            {"role": "system", "content": "Return JSON."},
            {"role": "user", "content": "Return repair guidance."},
        ],
        agent3.REPAIR_AI_SCHEMA,
        200,
        "repair-assurance",
        2200,
        False,
    )

    assert json.loads(text) == {"c": "HIGH", "x": []}
    assert service.last_generation["json_recovered"] is True


def test_current_knowledge_ignores_generic_dependency_boundary_word():
    contract = agent3.RepairContractInput.model_validate(
        {
            "contract_id": "STITCH-RC-001",
            "finding_refs": ["RQI-001"],
            "repair_objective": "Restore local ValueError behavior.",
            "repair_strategy": "Add input validation at the local boundary.",
            "change_boundary": "Limit the change to the component, input boundary, dependency, or configuration directly represented by this finding.",
            "protected_behavior": "Preserve valid-input behavior.",
        }
    )

    assert agent3.grounded_current_knowledge_for_contract(contract) is False


def test_current_knowledge_requires_real_external_version_context():
    contract = agent3.RepairContractInput.model_validate(
        {
            "contract_id": "STITCH-RC-001",
            "finding_refs": ["RQI-001"],
            "repair_objective": "Update a dependency after checking version compatibility.",
            "repair_strategy": "Review current trusted documentation and dependency version compatibility before changing the package.",
        }
    )

    assert agent3.grounded_current_knowledge_for_contract(contract) is True
