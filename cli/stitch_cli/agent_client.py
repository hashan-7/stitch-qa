import ast
import re
from pathlib import Path

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from stitch_cli.code_cli import (
    call_code_agent,
    call_repair_assurance_agent,
    call_source_review_agent,
)
from stitch_cli.runtime_fallback import build_client_runtime_fallback


DEFAULT_AGENT_TIMEOUT_SECONDS = 120
RUNTIME_AGENT_CONNECT_TIMEOUT_SECONDS = 15
RUNTIME_AGENT_READ_TIMEOUT_SECONDS = 120
RUNTIME_AGENT_RETRY_TOTAL = 1
MAX_CODE_SNIPPET_CHARS = 8000
MAX_ERROR_LOG_CHARS = 12000
MAX_RUNTIME_AGENT_LOG_CHARS = 24000
MAX_REPAIR_AGENT_LOG_CHARS = 8000
MAX_REPAIR_SOURCE_FINDINGS = 100
MAX_RUNTIME_FAILURE_RECORDS = 100
MAX_RUNTIME_TRACE_CHARS = 1500
MAX_RUNTIME_RAW_FAILURE_CHARS = 2000
MAX_SOURCE_REVIEW_FILES = 100
MAX_SOURCE_FILE_CHARS = 50000
MAX_SOURCE_REVIEW_CHARS = 300000
MAX_REPAIR_ASSURANCE_FILES = 4
MAX_REPAIR_ASSURANCE_FILE_CHARS = 12000
MAX_REPAIR_ASSURANCE_CHARS = 16000


def normalize_list(value):
    if isinstance(
        value,
        list,
    ):
        return value

    if value is None:
        return []

    return [value]


def build_runtime_evidence_payload(
    execution_result,
):
    source = execution_result.get(
        "runtime_evidence"
    )

    if not isinstance(
        source,
        dict,
    ):
        return None

    evidence = dict(
        source
    )
    source_failures = normalize_list(
        source.get(
            "failures"
        )
    )
    submitted_failures = []

    for item in source_failures[
        :MAX_RUNTIME_FAILURE_RECORDS
    ]:
        if not isinstance(
            item,
            dict,
        ):
            continue

        normalized = dict(
            item
        )

        if normalized.get(
            "traceback_excerpt"
        ):
            normalized[
                "traceback_excerpt"
            ] = str(
                normalized[
                    "traceback_excerpt"
                ]
            )[
                -MAX_RUNTIME_TRACE_CHARS:
            ]

        if normalized.get(
            "raw_failure"
        ):
            normalized[
                "raw_failure"
            ] = str(
                normalized[
                    "raw_failure"
                ]
            )[
                -MAX_RUNTIME_RAW_FAILURE_CHARS:
            ]

        submitted_failures.append(
            normalized
        )

    total_failures = int(
        source.get(
            "failure_records_total",
            len(
                source_failures
            ),
        )
    )

    evidence["failures"] = (
        submitted_failures
    )
    evidence[
        "failure_records_total"
    ] = total_failures
    evidence[
        "failure_records_submitted"
    ] = len(
        submitted_failures
    )
    evidence[
        "evidence_truncated"
    ] = (
        total_failures
        > len(
            submitted_failures
        )
    )
    evidence["warnings"] = normalize_list(
        source.get(
            "warnings"
        )
    )[:100]
    evidence[
        "collection_errors"
    ] = normalize_list(
        source.get(
            "collection_errors"
        )
    )[:50]
    evidence["report_files"] = normalize_list(
        source.get(
            "report_files"
        )
    )[:100]

    return evidence


def get_failure_context(
    execution_result,
):
    return {
        "failure_type": execution_result.get(
            "failure_type"
        ),
        "help_message": execution_result.get(
            "help_message"
        ),
    }


def get_root_cause(
    agent_data,
    execution_result,
):
    if agent_data:
        if agent_data.get(
            "primary_root_cause"
        ):
            return agent_data.get(
                "primary_root_cause"
            )

        groups = (
            agent_data.get(
                "root_cause_groups"
            )
            or []
        )

        if (
            groups
            and isinstance(
                groups[0],
                dict,
            )
            and groups[0].get(
                "root_cause"
            )
        ):
            return groups[0].get(
                "root_cause"
            )

        if agent_data.get(
            "root_cause"
        ):
            return agent_data.get(
                "root_cause"
            )

    if execution_result.get(
        "help_message"
    ):
        return execution_result.get(
            "help_message"
        )

    return None


def resolve_project_file(
    project_path,
    relative_file_path,
):
    if not relative_file_path:
        return None

    project_root = Path(
        project_path
    ).resolve()
    absolute_path = (
        project_root
        / relative_file_path
    ).resolve()

    try:
        absolute_path.relative_to(
            project_root
        )
    except ValueError:
        return None

    if not absolute_path.is_file():
        return None

    return absolute_path


def read_project_file(
    project_path,
    relative_file_path,
):
    try:
        absolute_path = resolve_project_file(
            project_path,
            relative_file_path,
        )

        if absolute_path is None:
            return None

        content = absolute_path.read_text(
            encoding="utf-8",
            errors="ignore",
        )

        if (
            len(content)
            > MAX_CODE_SNIPPET_CHARS
        ):
            return content[
                -MAX_CODE_SNIPPET_CHARS:
            ]

        return content

    except OSError:
        return None


def build_error_log(
    execution_result,
):
    stdout = execution_result.get(
        "stdout"
    ) or ""
    stderr = execution_result.get(
        "stderr"
    ) or ""

    combined_log = (
        "STDOUT:\n"
        f"{stdout}\n\n"
        "STDERR:\n"
        f"{stderr}"
    )

    if (
        len(combined_log)
        > MAX_ERROR_LOG_CHARS
    ):
        return combined_log[
            -MAX_ERROR_LOG_CHARS:
        ]

    return combined_log


def build_source_review_payload(
    scan_result,
):
    source_review = scan_result.get(
        "source_review",
        {},
    )
    project_path = scan_result[
        "project_path"
    ]
    source_files = source_review.get(
        "source_files",
        [],
    )
    submitted_files = []
    omitted_files = []
    read_errors = []
    submitted_chars = 0
    truncated_files_count = 0

    for relative_path in source_files:
        if (
            len(
                submitted_files
            )
            >= MAX_SOURCE_REVIEW_FILES
        ):
            omitted_files.append(
                relative_path
            )
            continue

        absolute_path = resolve_project_file(
            project_path,
            relative_path,
        )

        if absolute_path is None:
            read_errors.append(
                relative_path
            )
            continue

        try:
            content = absolute_path.read_text(
                encoding="utf-8",
                errors="ignore",
            )
        except OSError:
            read_errors.append(
                relative_path
            )
            continue

        original_chars = len(
            content
        )
        truncated = (
            original_chars
            > MAX_SOURCE_FILE_CHARS
        )

        if truncated:
            content = content[
                :MAX_SOURCE_FILE_CHARS
            ]

        remaining_chars = (
            MAX_SOURCE_REVIEW_CHARS
            - submitted_chars
        )

        if remaining_chars <= 0:
            omitted_files.append(
                relative_path
            )
            continue

        if (
            len(content)
            > remaining_chars
        ):
            if remaining_chars < 1000:
                omitted_files.append(
                    relative_path
                )
                continue

            content = content[
                :remaining_chars
            ]
            truncated = True

        if truncated:
            truncated_files_count += 1

        submitted_files.append(
            {
                "path": relative_path,
                "content": content,
                "truncated": truncated,
                "original_chars": original_chars,
            }
        )
        submitted_chars += len(
            content
        )

    static_map = scan_result.get(
        "static_map",
        {},
    )

    payload = {
        "project_type": scan_result[
            "project_type"
        ],
        "has_tests": bool(
            static_map.get(
                "has_tests"
            )
        ),
        "files": submitted_files,
        "discovered_files_count": int(
            source_review.get(
                "source_files_count",
                0,
            )
        ),
        "submitted_files_count": len(
            submitted_files
        ),
        "submitted_chars": submitted_chars,
        "truncated_files_count": (
            truncated_files_count
        ),
        "omitted_files_count": len(
            omitted_files
        ),
        "read_error_files_count": len(
            read_errors
        ),
    }

    collection = {
        "discovered_files_count": int(
            source_review.get(
                "source_files_count",
                0,
            )
        ),
        "submitted_files_count": len(
            submitted_files
        ),
        "submitted_chars": submitted_chars,
        "truncated_files_count": (
            truncated_files_count
        ),
        "omitted_files_count": len(
            omitted_files
        ),
        "read_error_files_count": len(
            read_errors
        ),
        "omitted_files": omitted_files,
        "read_error_files": read_errors,
    }

    return (
        payload,
        collection,
    )


def build_local_no_source_review(
    scan_result,
    collection,
):
    source_review = scan_result.get(
        "source_review",
        {},
    )
    warning = (
        source_review.get(
            "warning"
        )
        or "No reviewable source files were detected."
    )

    return {
        "agent_id": "source-quality-analyst",
        "display_name": "Source Quality Intelligence Analyst",
        "agent_version": "3.0",
        "agent": "code-agent",
        "mode": "local-guard",
        "model": None,
        "status": "NO_SOURCE_FILES",
        "confidence": "HIGH",
        "summary": warning,
        "risk_level": "UNKNOWN",
        "release_recommendation": "REVIEW_REQUIRED",
        "reviewed_files_count": 0,
        "findings_count": 0,
        "severity_summary": {
            "CRITICAL": 0,
            "HIGH": 0,
            "MEDIUM": 0,
            "LOW": 0,
            "INFO": 0,
        },
        "category_summary": {},
        "findings": [],
        "warnings": [warning],
        "limitations": [
            "Source-code QA review could not run because no eligible application source files were available."
        ],
        "verification": (
            "Confirm whether the project intentionally contains tests only, then review the runtime evidence."
        ),
        "current_knowledge_required": False,
        "current_knowledge_reason": None,
        "llm_metrics": None,
        "llm_error": None,
        "coverage": collection,
    }


def normalize_source_review_data(
    data,
    collection,
):
    normalized = dict(
        data
    )
    normalized["findings"] = normalize_list(
        data.get(
            "findings"
        )
    )
    normalized["warnings"] = normalize_list(
        data.get(
            "warnings"
        )
    )
    normalized["limitations"] = normalize_list(
        data.get(
            "limitations"
        )
    )
    normalized[
        "severity_summary"
    ] = (
        data.get(
            "severity_summary"
        )
        if isinstance(
            data.get(
                "severity_summary"
            ),
            dict,
        )
        else {}
    )
    normalized[
        "category_summary"
    ] = (
        data.get(
            "category_summary"
        )
        if isinstance(
            data.get(
                "category_summary"
            ),
            dict,
        )
        else {}
    )
    normalized[
        "reviewed_files_count"
    ] = int(
        data.get(
            "reviewed_files_count",
            collection[
                "submitted_files_count"
            ],
        )
    )
    normalized[
        "findings_count"
    ] = int(
        data.get(
            "findings_count",
            len(
                normalized[
                    "findings"
                ]
            ),
        )
    )
    normalized[
        "coverage"
    ] = collection

    return normalized


def review_source_with_agent(
    code_agent_url,
    scan_result,
):
    payload, collection = build_source_review_payload(
        scan_result
    )

    if not payload[
        "files"
    ]:
        return {
            "success": True,
            "data": build_local_no_source_review(
                scan_result,
                collection,
            ),
            "error": None,
        }

    result = call_source_review_agent(
        payload,
        code_agent_url,
    )

    if not result[
        "success"
    ]:
        return result

    data = result.get(
        "data"
    )

    if (
        not isinstance(
            data,
            dict,
        )
        or not data.get(
            "status"
        )
    ):
        return {
            "success": False,
            "data": None,
            "error": (
                "Code agent returned an invalid source-review response."
            ),
        }

    return {
        "success": True,
        "data": normalize_source_review_data(
            data,
            collection,
        ),
        "error": None,
    }


def build_unavailable_source_review(
    scan_result,
    error,
):
    source_review = scan_result.get(
        "source_review",
        {},
    )

    return {
        "agent_id": "source-quality-analyst",
        "display_name": "Source Quality Intelligence Analyst",
        "agent_version": "3.0",
        "agent": "code-agent",
        "mode": "unavailable",
        "model": None,
        "status": "UNAVAILABLE",
        "confidence": "LOW",
        "summary": (
            "Source Quality Intelligence analysis could not be completed because Agent 3 was unavailable."
        ),
        "risk_level": "UNKNOWN",
        "release_recommendation": "QA_INCOMPLETE",
        "reviewed_files_count": 0,
        "findings_count": 0,
        "severity_summary": {},
        "category_summary": {},
        "findings": [],
        "warnings": [str(error)],
        "limitations": [
            "No Source Quality Intelligence result was available for this run."
        ],
        "verification": (
            "Check the Agent 3 deployment and rerun Stitch QA."
        ),
        "current_knowledge_required": False,
        "current_knowledge_reason": None,
        "llm_metrics": None,
        "llm_error": None,
        "coverage": {
            "discovered_files_count": int(
                source_review.get(
                    "source_files_count",
                    0,
                )
            ),
            "submitted_files_count": 0,
            "submitted_chars": 0,
            "truncated_files_count": 0,
            "omitted_files_count": 0,
            "read_error_files_count": 0,
            "omitted_files": [],
            "read_error_files": [],
        },
    }


def normalize_log_agent_data(data):
    if not isinstance(
        data,
        dict,
    ):
        return None

    execution_status = data.get(
        "execution_status"
    )
    test_result = data.get(
        "test_result"
    )
    release_gate = data.get(
        "release_gate"
    )
    final_status = data.get(
        "final_status"
    )

    if (
        not execution_status
        or not test_result
        or not release_gate
    ):
        if not final_status:
            return None

        execution_status = "COMPLETED"
        test_result = (
            "PASS"
            if str(
                final_status
            ).upper()
            == "PASS"
            else "FAIL"
        )
        release_gate = (
            "ALLOW_RELEASE"
            if test_result
            == "PASS"
            else "BLOCK_RELEASE"
        )

    root_cause_groups = normalize_list(
        data.get(
            "root_cause_groups"
        )
    )
    primary_root_cause = (
        data.get(
            "primary_root_cause"
        )
        or data.get(
            "root_cause"
        )
    )

    if (
        not primary_root_cause
        and root_cause_groups
        and isinstance(
            root_cause_groups[0],
            dict,
        )
    ):
        primary_root_cause = (
            root_cause_groups[0].get(
                "root_cause"
            )
        )

    required_actions = normalize_list(
        data.get(
            "required_actions"
        )
    )

    if (
        not required_actions
        and data.get(
            "recommendation"
        )
    ):
        required_actions = [
            data.get(
                "recommendation"
            )
        ]

    verification_steps = normalize_list(
        data.get(
            "verification_steps"
        )
    )

    return {
        "agent_id": (
            data.get(
                "agent_id"
            )
            or "runtime-quality-analyst"
        ),
        "display_name": (
            data.get(
                "display_name"
            )
            or "Runtime Quality Intelligence Analyst"
        ),
        "agent_version": (
            data.get(
                "agent_version"
            )
            or "2.0"
        ),
        "agent": (
            data.get(
                "agent"
            )
            or "log-agent"
        ),
        "mode": (
            data.get(
                "mode"
            )
            or "unknown"
        ),
        "model": data.get(
            "model"
        ),
        "execution_status": (
            execution_status
        ),
        "test_result": (
            test_result
        ),
        "release_gate": (
            release_gate
        ),
        "runtime_risk_level": (
            data.get(
                "runtime_risk_level"
            )
            or "UNKNOWN"
        ),
        "failure_origin": (
            data.get(
                "failure_origin"
            )
            or "NOT_ESTABLISHED"
        ),
        "diagnosis_confidence": (
            data.get(
                "diagnosis_confidence"
            )
            or "LOW"
        ),
        "final_status": (
            final_status
            or (
                "PASS"
                if release_gate
                in {
                    "ALLOW_RELEASE",
                    "ALLOW_WITH_WARNINGS",
                }
                else "FAIL"
            )
        ),
        "summary": data.get(
            "summary"
        ),
        "outcome_interpretation": data.get(
            "outcome_interpretation"
        ),
        "scope_assurance": data.get(
            "scope_assurance"
        ),
        "residual_runtime_risk": data.get(
            "residual_runtime_risk"
        ),
        "next_verification": data.get(
            "next_verification"
        ),
        "run_summary": (
            data.get(
                "run_summary"
            )
            if isinstance(
                data.get(
                    "run_summary"
                ),
                dict,
            )
            else {}
        ),
        "root_cause_groups": (
            root_cause_groups
        ),
        "primary_root_cause": (
            primary_root_cause
        ),
        "root_cause": (
            primary_root_cause
        ),
        "runtime_impact": data.get(
            "runtime_impact"
        ),
        "required_actions": (
            required_actions
        ),
        "recommendation": (
            data.get(
                "recommendation"
            )
            or (
                required_actions[0]
                if required_actions
                else None
            )
        ),
        "verification_steps": (
            verification_steps
        ),
        "issues": normalize_list(
            data.get(
                "issues"
            )
        ),
        "warnings": normalize_list(
            data.get(
                "warnings"
            )
        ),
        "limitations": normalize_list(
            data.get(
                "limitations"
            )
        ),
        "evidence_quality": (
            data.get(
                "evidence_quality"
            )
            or "NONE"
        ),
        "llm_metrics": (
            data.get(
                "llm_metrics"
            )
            if isinstance(
                data.get(
                    "llm_metrics"
                ),
                dict,
            )
            else None
        ),
        "llm_error": data.get(
            "llm_error"
        ),
    }


def build_unavailable_log_analysis(
    error,
    scan_result=None,
    execution_result=None,
):
    if isinstance(scan_result, dict) and isinstance(execution_result, dict):
        return build_client_runtime_fallback(
            scan_result,
            execution_result,
            str(error),
        )

    return {
        "agent_id": "runtime-quality-analyst",
        "display_name": "Runtime Quality Intelligence Analyst",
        "agent_version": "2.0",
        "agent": "log-agent",
        "mode": "unavailable",
        "model": None,
        "execution_status": "UNKNOWN",
        "test_result": "INCONCLUSIVE",
        "release_gate": "REVIEW_REQUIRED",
        "runtime_risk_level": "UNKNOWN",
        "failure_origin": "NOT_ESTABLISHED",
        "diagnosis_confidence": "LOW",
        "final_status": "UNAVAILABLE",
        "summary": "Runtime Quality Intelligence analysis could not be completed because no validated local runtime evidence was available for fallback analysis.",
        "run_summary": {},
        "root_cause_groups": [],
        "primary_root_cause": None,
        "root_cause": None,
        "runtime_impact": "Runtime QA evidence is incomplete because neither the remote analyst nor a validated local fallback result was available.",
        "required_actions": [
            "Restore the Runtime Quality Intelligence Analyst service or rerun Stitch QA with valid runtime evidence."
        ],
        "recommendation": "Restore the Runtime Quality Intelligence Analyst service or rerun Stitch QA with valid runtime evidence.",
        "verification_steps": [
            "Confirm the Runtime Quality Intelligence Analyst service is reachable and rerun the validated test workflow."
        ],
        "issues": [],
        "warnings": [str(error)],
        "limitations": [
            "No Runtime Quality Intelligence Analyst response or validated local runtime evidence was available for this run."
        ],
        "evidence_quality": "NONE",
        "llm_error": None,
    }


def normalize_repair_agent_data(data):
    if not isinstance(data, dict):
        return None

    if not data.get("status"):
        return None

    contracts = []
    for item in normalize_list(data.get("stitch_repair_contracts")):
        if not isinstance(item, dict):
            continue
        contracts.append(
            {
                "contract_id": item.get("contract_id"),
                "finding_refs": normalize_list(item.get("finding_refs")),
                "title": item.get("title"),
                "priority": item.get("priority"),
                "priority_reason": item.get("priority_reason"),
                "repair_objective": item.get("repair_objective"),
                "repair_strategy": item.get("repair_strategy"),
                "change_boundary": item.get("change_boundary"),
                "protected_behavior": item.get("protected_behavior"),
                "side_effect_risk": item.get("side_effect_risk"),
                "verification": item.get("verification"),
                "done_condition": item.get("done_condition"),
                "status": item.get("status") or "PENDING_VERIFICATION",
            }
        )

    repair_risk = (
        data.get("repair_risk_level")
        or data.get("risk_level")
        or "UNKNOWN"
    )

    return {
        "agent_id": data.get("agent_id") or "defect-resolution-analyst",
        "display_name": (
            data.get("display_name")
            or "Defect Resolution Intelligence Analyst"
        ),
        "agent_version": data.get("agent_version") or "2.0",
        "agent": data.get("agent") or "repair-agent",
        "mode": data.get("mode") or "unknown",
        "model": data.get("model"),
        "status": data.get("status"),
        "overall_priority": data.get("overall_priority") or "NONE",
        "confidence": data.get("confidence") or "LOW",
        "repair_risk_level": repair_risk,
        "risk_level": repair_risk,
        "auto_apply": False,
        "summary": data.get("summary"),
        "stitch_repair_contracts": contracts,
        "current_knowledge_required": bool(
            data.get("current_knowledge_required", False)
        ),
        "current_knowledge_reason": data.get("current_knowledge_reason"),
        "suggestions": normalize_list(data.get("suggestions")),
        "next_action": data.get("next_action"),
        "warnings": normalize_list(data.get("warnings")),
        "limitations": normalize_list(data.get("limitations")),
        "llm_metrics": (
            data.get("llm_metrics")
            if isinstance(data.get("llm_metrics"), dict)
            else None
        ),
        "llm_error": data.get("llm_error"),
    }


def build_unavailable_repair_guidance(error):
    return {
        "agent_id": "defect-resolution-analyst",
        "display_name": "Defect Resolution Intelligence Analyst",
        "agent_version": "2.0",
        "agent": "repair-agent",
        "mode": "unavailable",
        "model": None,
        "status": "UNAVAILABLE",
        "overall_priority": "NONE",
        "confidence": "LOW",
        "repair_risk_level": "UNKNOWN",
        "risk_level": "UNKNOWN",
        "auto_apply": False,
        "summary": (
            "Defect resolution planning could not be completed because Agent 2 was unavailable."
        ),
        "stitch_repair_contracts": [],
        "current_knowledge_required": False,
        "current_knowledge_reason": None,
        "suggestions": [],
        "next_action": (
            "Check the Defect Resolution Intelligence Analyst deployment and rerun Stitch QA."
        ),
        "warnings": [str(error)],
        "limitations": [
            "No Agent 2 repair plan was available; validated QA evidence remains unchanged."
        ],
        "llm_metrics": None,
        "llm_error": None,
    }


def trim_repair_text(value, limit):
    text = str(value or "")
    if len(text) <= limit:
        return text
    return text[: limit - 3].rstrip() + "..."


def build_repair_source_review_payload(source_review_data):
    source = source_review_data if isinstance(source_review_data, dict) else {}
    findings = []

    for item in normalize_list(source.get("findings"))[:MAX_REPAIR_SOURCE_FINDINGS]:
        if not isinstance(item, dict):
            continue
        finding = {
            "id": item.get("id"),
            "severity": item.get("severity"),
            "title": trim_repair_text(item.get("title"), 240),
            "category": trim_repair_text(item.get("category"), 120),
            "file_path": trim_repair_text(item.get("file_path"), 500),
            "line": item.get("line"),
            "confidence": item.get("confidence"),
            "evidence": trim_repair_text(item.get("evidence"), 1000),
            "impact": trim_repair_text(item.get("impact"), 600),
            "recommendation": trim_repair_text(item.get("recommendation"), 600),
        }
        findings.append(
            {key: value for key, value in finding.items() if value not in {None, ""}}
        )

    return {
        "status": source.get("status"),
        "risk_level": source.get("risk_level"),
        "release_recommendation": source.get("release_recommendation"),
        "findings_count": int(source.get("findings_count", len(findings)) or 0),
        "findings": findings,
        "warnings": normalize_list(source.get("warnings"))[:20],
        "limitations": normalize_list(source.get("limitations"))[:20],
    }


def normalize_code_agent_data(data):
    if not isinstance(data, dict):
        return None

    if not data.get("status"):
        return None

    guidance = []
    for item in normalize_list(data.get("guidance")):
        if not isinstance(item, dict):
            continue
        guidance.append(
            {
                "guidance_id": item.get("guidance_id"),
                "repair_contract_ref": item.get("repair_contract_ref"),
                "finding_refs": normalize_list(item.get("finding_refs")),
                "target_files": normalize_list(item.get("target_files")),
                "target_symbols": normalize_list(item.get("target_symbols")),
                "implementation_intent": item.get("implementation_intent"),
                "code_level_approach": item.get("code_level_approach"),
                "change_boundary": item.get("change_boundary"),
                "protected_behavior": item.get("protected_behavior"),
                "side_effect_considerations": item.get("side_effect_considerations"),
                "targeted_verification": item.get("targeted_verification"),
                "regression_verification": item.get("regression_verification"),
                "suggested_patch": item.get("suggested_patch"),
                "patch_validation_status": item.get("patch_validation_status") or "NOT_VALIDATED",
                "current_knowledge_required": bool(
                    item.get("current_knowledge_required", False)
                ),
                "current_knowledge_reason": item.get("current_knowledge_reason"),
                "status": item.get("status") or "PENDING_IMPLEMENTATION",
            }
        )

    return {
        "agent_id": data.get("agent_id") or "repair-assurance-analyst",
        "display_name": (
            data.get("display_name")
            or "Repair Assurance Intelligence Analyst"
        ),
        "agent_version": data.get("agent_version") or "3.0",
        "agent": data.get("agent") or "code-agent",
        "mode": data.get("mode") or "unknown",
        "model": data.get("model"),
        "status": data.get("status"),
        "confidence": data.get("confidence") or "LOW",
        "risk_level": data.get("risk_level") or "UNKNOWN",
        "auto_apply": False,
        "summary": data.get("summary"),
        "guidance": guidance,
        "suggested_patch": data.get("suggested_patch"),
        "verification": data.get("verification"),
        "current_knowledge_required": bool(
            data.get("current_knowledge_required", False)
        ),
        "current_knowledge_reason": data.get("current_knowledge_reason"),
        "evidence_lineage": [
            item
            for item in normalize_list(data.get("evidence_lineage"))
            if isinstance(item, dict)
        ],
        "shadow_validation_status": (
            data.get("shadow_validation_status") or "NOT_RUN"
        ),
        "warnings": normalize_list(data.get("warnings")),
        "limitations": normalize_list(data.get("limitations")),
        "llm_metrics": (
            data.get("llm_metrics")
            if isinstance(data.get("llm_metrics"), dict)
            else None
        ),
        "llm_error": data.get("llm_error"),
    }


def build_unavailable_code_guidance(
    error,
):
    return {
        "agent_id": "repair-assurance-analyst",
        "display_name": "Repair Assurance Intelligence Analyst",
        "agent_version": "3.0",
        "agent": "code-agent",
        "mode": "unavailable",
        "model": None,
        "status": "UNAVAILABLE",
        "confidence": "LOW",
        "risk_level": "UNKNOWN",
        "auto_apply": False,
        "summary": (
            "Repair Assurance could not be completed because Agent 3 was unavailable."
        ),
        "guidance": [],
        "suggested_patch": None,
        "verification": (
            "Check the Agent 3 deployment and rerun Stitch QA."
        ),
        "current_knowledge_required": False,
        "current_knowledge_reason": None,
        "evidence_lineage": [],
        "shadow_validation_status": "NOT_RUN",
        "warnings": [str(error)],
        "limitations": [
            "No Repair Assurance result was available; Agent 1, Agent 2, and source-review evidence remain unchanged."
        ],
        "llm_metrics": None,
        "llm_error": None,
    }


def build_runtime_agent_session():
    retry = Retry(
        total=RUNTIME_AGENT_RETRY_TOTAL,
        connect=RUNTIME_AGENT_RETRY_TOTAL,
        read=RUNTIME_AGENT_RETRY_TOTAL,
        status=RUNTIME_AGENT_RETRY_TOTAL,
        backoff_factor=0.75,
        status_forcelist=(
            408,
            425,
            429,
            500,
            502,
            503,
            504,
        ),
        allowed_methods=frozenset({"POST"}),
        respect_retry_after_header=True,
        raise_on_status=False,
    )
    adapter = HTTPAdapter(
        max_retries=retry
    )
    session = requests.Session()
    session.mount(
        "https://",
        adapter,
    )
    session.mount(
        "http://",
        adapter,
    )
    return session


def analyze_logs_with_agent(
    agent_url,
    scan_result,
    execution_result,
):
    failure_context = get_failure_context(
        execution_result
    )
    stdout = execution_result.get(
        "stdout"
    ) or ""
    stderr = execution_result.get(
        "stderr"
    ) or ""

    payload = {
        "project_type": scan_result[
            "project_type"
        ],
        "command": execution_result.get(
            "command"
        )
        or "",
        "success": bool(
            execution_result.get(
                "success"
            )
        ),
        "exit_code": execution_result.get(
            "exit_code"
        ),
        "stdout": stdout[
            -MAX_RUNTIME_AGENT_LOG_CHARS:
        ],
        "stderr": stderr[
            -MAX_RUNTIME_AGENT_LOG_CHARS:
        ],
        "failure_type": failure_context[
            "failure_type"
        ],
        "help_message": failure_context[
            "help_message"
        ],
        "runtime_evidence": build_runtime_evidence_payload(
            execution_result
        ),
    }

    try:
        with build_runtime_agent_session() as session:
            response = session.post(
                f"{agent_url.rstrip('/')}/analyze",
                json=payload,
                timeout=(
                    RUNTIME_AGENT_CONNECT_TIMEOUT_SECONDS,
                    RUNTIME_AGENT_READ_TIMEOUT_SECONDS,
                ),
            )
            response.raise_for_status()
            data = normalize_log_agent_data(
                response.json()
            )

        if data is None:
            error = "Runtime Quality Intelligence Analyst returned an invalid response."
            return {
                "success": True,
                "data": build_client_runtime_fallback(
                    scan_result,
                    execution_result,
                    error,
                ),
                "error": error,
                "degraded": True,
            }

        return {
            "success": True,
            "data": data,
            "error": None,
            "degraded": False,
        }

    except (
        requests.exceptions.RequestException,
        ValueError,
    ) as error:
        error_text = str(
            error
        )
        return {
            "success": True,
            "data": build_client_runtime_fallback(
                scan_result,
                execution_result,
                error_text,
            ),
            "error": error_text,
            "degraded": True,
        }


def suggest_repair_with_agent(
    repair_agent_url,
    scan_result,
    execution_result,
    agent_data=None,
    source_review_data=None,
):
    failure_context = get_failure_context(execution_result)
    stdout = execution_result.get("stdout") or ""
    stderr = execution_result.get("stderr") or ""

    payload = {
        "project_type": scan_result["project_type"],
        "command": execution_result.get("command") or "",
        "success": bool(execution_result.get("success")),
        "exit_code": execution_result.get("exit_code"),
        "stdout": stdout[-MAX_REPAIR_AGENT_LOG_CHARS:],
        "stderr": stderr[-MAX_REPAIR_AGENT_LOG_CHARS:],
        "failure_type": failure_context["failure_type"],
        "help_message": failure_context["help_message"],
        "runtime_evidence": build_runtime_evidence_payload(execution_result),
        "runtime_analysis": agent_data if isinstance(agent_data, dict) else None,
        "source_review": build_repair_source_review_payload(source_review_data),
    }

    try:
        response = requests.post(
            f"{repair_agent_url.rstrip('/')}/suggest",
            json=payload,
            timeout=(15, DEFAULT_AGENT_TIMEOUT_SECONDS),
        )
        response.raise_for_status()
        data = normalize_repair_agent_data(response.json())

        if data is None:
            return {
                "success": False,
                "data": None,
                "error": (
                    "Defect Resolution Intelligence Analyst returned an invalid guidance response."
                ),
            }

        return {
            "success": True,
            "data": data,
            "error": None,
        }

    except (requests.exceptions.RequestException, ValueError) as error:
        return {
            "success": False,
            "data": None,
            "error": str(error),
        }


def repair_assurance_candidate_paths(
    scan_result,
    source_review_data,
    agent_data,
    repair_data,
):
    source_review = source_review_data if isinstance(source_review_data, dict) else {}
    runtime_analysis = agent_data if isinstance(agent_data, dict) else {}
    repair_plan = repair_data if isinstance(repair_data, dict) else {}
    discovered = normalize_list(
        scan_result.get("source_review", {}).get("source_files")
    )
    source_by_id = {
        str(item.get("id")): item
        for item in normalize_list(source_review.get("findings"))
        if isinstance(item, dict) and item.get("id")
    }
    runtime_by_id = {
        str(item.get("group_id")): item
        for item in normalize_list(runtime_analysis.get("root_cause_groups"))
        if isinstance(item, dict) and item.get("group_id")
    }
    paths = []

    def add(value):
        path = str(value or "").strip()
        if path and path in discovered and path not in paths:
            paths.append(path)

    for contract in normalize_list(repair_plan.get("stitch_repair_contracts")):
        if not isinstance(contract, dict):
            continue
        for ref in normalize_list(contract.get("finding_refs")):
            source_item = source_by_id.get(str(ref))
            if source_item:
                add(source_item.get("file_path"))
            runtime_item = runtime_by_id.get(str(ref))
            if runtime_item:
                for evidence in normalize_list(runtime_item.get("evidence")):
                    if isinstance(evidence, dict):
                        add(evidence.get("application_file"))

    if not paths:
        for path in discovered:
            add(path)
            if len(paths) >= MAX_REPAIR_ASSURANCE_FILES:
                break

    return paths[:MAX_REPAIR_ASSURANCE_FILES]


def build_repair_assurance_source_files(
    scan_result,
    candidate_paths,
):
    files = []
    total_chars = 0

    for relative_path in candidate_paths:
        if len(files) >= MAX_REPAIR_ASSURANCE_FILES:
            break
        absolute_path = resolve_project_file(
            scan_result["project_path"],
            relative_path,
        )
        if absolute_path is None:
            continue
        try:
            content = absolute_path.read_text(
                encoding="utf-8",
                errors="ignore",
            )
        except OSError:
            continue

        original_chars = len(content)
        content = content[:MAX_REPAIR_ASSURANCE_FILE_CHARS]
        remaining = MAX_REPAIR_ASSURANCE_CHARS - total_chars
        if remaining <= 0:
            break
        if len(content) > remaining:
            content = content[:remaining]
        truncated = len(content) < original_chars
        if not content:
            continue
        files.append(
            {
                "path": relative_path,
                "content": content,
                "truncated": truncated,
                "original_chars": original_chars,
            }
        )
        total_chars += len(content)

    return files


def build_repair_assurance_source_review(source_review_data):
    source = source_review_data if isinstance(source_review_data, dict) else {}
    return {
        "agent_id": source.get("agent_id"),
        "display_name": source.get("display_name"),
        "agent_version": source.get("agent_version"),
        "status": source.get("status"),
        "risk_level": source.get("risk_level"),
        "release_recommendation": source.get("release_recommendation"),
        "findings_count": source.get("findings_count"),
        "findings": normalize_list(source.get("findings"))[:MAX_REPAIR_SOURCE_FINDINGS],
        "warnings": normalize_list(source.get("warnings"))[:20],
        "limitations": normalize_list(source.get("limitations"))[:20],
    }


def repair_assurance_contract_text(contract):
    return " ".join(
        str(contract.get(key) or "").lower()
        for key in (
            "title",
            "priority_reason",
            "repair_objective",
            "repair_strategy",
            "change_boundary",
            "protected_behavior",
            "verification",
            "done_condition",
        )
    )


def repair_assurance_environment_only(contract):
    text = repair_assurance_contract_text(contract)
    environment_signal = any(
        value in text
        for value in (
            "maven is not installed",
            "maven wrapper",
            "environment",
            "build-tool availability",
            "build tool availability",
            "python is not installed",
            "pytest is not installed",
        )
    )
    source_exclusion = any(
        value in text
        for value in (
            "do not modify application source",
            "keep application source code outside this repair",
            "application source remains outside this repair",
        )
    )
    return environment_signal and source_exclusion


def repair_assurance_testing_only(contract):
    text = repair_assurance_contract_text(contract)
    testing_signal = any(
        value in text
        for value in (
            "no automated tests",
            "missing tests",
            "add focused tests",
            "test files and test configuration",
        )
    )
    source_exclusion = any(
        value in text
        for value in (
            "do not modify application behavior",
            "keep production code unchanged",
            "preserve existing application behavior",
        )
    )
    return testing_signal and source_exclusion


def repair_assurance_current_knowledge(contract, repair_data):
    if not bool((repair_data or {}).get("current_knowledge_required")):
        return False
    text = repair_assurance_contract_text(contract)
    return any(
        value in text
        for value in (
            "version",
            "compatibility",
            "deprecation",
            "deprecated",
            "security advisory",
            "cve",
            "vendor",
            "jdk",
            "plugin",
            "dependency version",
            "dependency compatibility",
        )
    )


def repair_assurance_extract_symbols(path, content):
    path = str(path or "").lower()
    symbols = []
    if path.endswith(".py"):
        try:
            tree = ast.parse(content or "")
        except SyntaxError:
            return []
        for node in tree.body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                if node.name not in symbols:
                    symbols.append(node.name)
    elif path.endswith(".java"):
        class_match = re.search(r"\bclass\s+([A-Za-z_$][A-Za-z0-9_$]*)", content or "")
        if class_match:
            symbols.append(class_match.group(1))
        for match in re.finditer(
            r"\b(?:public|protected|private)?\s*(?:static\s+)?(?:final\s+)?(?:[A-Za-z_$][A-Za-z0-9_$<>\[\], ?.]*?)\s+([A-Za-z_$][A-Za-z0-9_$]*)\s*\(",
            content or "",
        ):
            name = match.group(1)
            if name not in symbols:
                symbols.append(name)
    return symbols[:12]


def repair_assurance_contract_paths(
    contract,
    scan_result,
    source_review_data,
    agent_data,
):
    source_review = source_review_data if isinstance(source_review_data, dict) else {}
    runtime_analysis = agent_data if isinstance(agent_data, dict) else {}
    discovered = normalize_list(scan_result.get("source_review", {}).get("source_files"))
    source_by_id = {
        str(item.get("id")): item
        for item in normalize_list(source_review.get("findings"))
        if isinstance(item, dict) and item.get("id")
    }
    runtime_by_id = {
        str(item.get("group_id")): item
        for item in normalize_list(runtime_analysis.get("root_cause_groups"))
        if isinstance(item, dict) and item.get("group_id")
    }
    paths = []

    def add(value):
        path = str(value or "").strip()
        if path and path in discovered and path not in paths:
            paths.append(path)

    for ref in normalize_list(contract.get("finding_refs")):
        source_item = source_by_id.get(str(ref))
        if source_item:
            add(source_item.get("file_path"))
        runtime_item = runtime_by_id.get(str(ref))
        if runtime_item:
            for evidence in normalize_list(runtime_item.get("evidence")):
                if isinstance(evidence, dict):
                    add(evidence.get("application_file"))
    return paths[:MAX_REPAIR_ASSURANCE_FILES]


def build_client_repair_assurance_fallback(
    scan_result,
    execution_result,
    agent_data,
    repair_data,
    source_review_data,
    source_files,
    error,
):
    repair_plan = repair_data if isinstance(repair_data, dict) else {}
    contracts = [
        item
        for item in normalize_list(repair_plan.get("stitch_repair_contracts"))
        if isinstance(item, dict) and item.get("contract_id")
    ]
    if not contracts:
        return None

    source_file_map = {
        str(item.get("path")): item
        for item in source_files
        if isinstance(item, dict) and item.get("path")
    }
    guidance = []
    risk_order = {
        "UNKNOWN": -1,
        "NONE": 0,
        "INFO": 1,
        "LOW": 2,
        "MEDIUM": 3,
        "HIGH": 4,
        "CRITICAL": 5,
    }
    risks = []

    for index, contract in enumerate(contracts, start=1):
        contract_id = str(contract.get("contract_id"))
        finding_refs = list(dict.fromkeys(str(ref) for ref in normalize_list(contract.get("finding_refs")) if ref))
        environment_only = repair_assurance_environment_only(contract)
        testing_only = repair_assurance_testing_only(contract)
        target_files = repair_assurance_contract_paths(
            contract,
            scan_result,
            source_review_data,
            agent_data,
        )
        if environment_only or testing_only:
            target_files = []

        target_symbols = []
        for path in target_files:
            source_item = source_file_map.get(path) or {}
            for symbol in repair_assurance_extract_symbols(path, source_item.get("content") or ""):
                if symbol not in target_symbols:
                    target_symbols.append(symbol)

        objective = str(contract.get("repair_objective") or "Implement the Agent 2 repair objective within the approved boundary.")
        strategy = str(contract.get("repair_strategy") or "Apply the smallest evidence-backed change allowed by the Agent 2 contract.")
        verification = str(contract.get("verification") or "Confirm the repair objective, then run the relevant regression workflow.")
        side_effect_risk = str(contract.get("side_effect_risk") or "UNKNOWN").upper()
        if side_effect_risk not in risk_order:
            side_effect_risk = "UNKNOWN"
        risks.append(side_effect_risk)

        if environment_only:
            approach = "No application source change is justified. Resolve only the environment, build-tool, or wrapper availability problem defined by Agent 2."
            status = "NO_CODE_CHANGE_REQUIRED"
            patch_status = "NOT_APPLICABLE"
            regression = "After the environment blocker is removed, use the resulting complete build or test run as runtime regression evidence."
        elif testing_only:
            approach = "Add focused automated tests using the detected project conventions and keep production behavior unchanged unless a separate validated finding requires a source repair."
            status = "PENDING_IMPLEMENTATION"
            patch_status = "NOT_GENERATED"
            regression = "After the new tests are discovered and pass, run all existing project checks and confirm no regression."
        else:
            approach = strategy
            status = "PENDING_IMPLEMENTATION"
            patch_status = "NOT_GENERATED"
            regression = "After targeted confirmation, run the complete available test suite or project checks and confirm no new failure is introduced."

        current_required = repair_assurance_current_knowledge(contract, repair_plan)
        current_reason = None
        if current_required:
            current_reason = str(
                repair_plan.get("current_knowledge_reason")
                or "Current trusted documentation is required for this repair contract before implementation."
            )

        guidance.append(
            {
                "guidance_id": f"RAI-{index:03d}",
                "repair_contract_ref": contract_id,
                "finding_refs": finding_refs,
                "target_files": target_files,
                "target_symbols": target_symbols,
                "implementation_intent": objective,
                "code_level_approach": approach,
                "change_boundary": str(contract.get("change_boundary") or "Do not broaden the repair beyond the Agent 2 contract."),
                "protected_behavior": str(contract.get("protected_behavior") or "Preserve unaffected behavior represented by the validated evidence."),
                "side_effect_considerations": f"Respect the Agent 2 side-effect risk classification ({side_effect_risk}) and avoid unrelated refactoring.",
                "targeted_verification": verification,
                "regression_verification": regression,
                "suggested_patch": None,
                "patch_validation_status": patch_status,
                "current_knowledge_required": current_required,
                "current_knowledge_reason": current_reason,
                "status": status,
            }
        )

    risk_level = max(risks, key=lambda value: risk_order.get(value, -1), default="UNKNOWN")
    current_required = any(item["current_knowledge_required"] for item in guidance)
    current_reason = next(
        (item["current_knowledge_reason"] for item in guidance if item["current_knowledge_required"] and item["current_knowledge_reason"]),
        None,
    )
    return {
        "agent_id": "repair-assurance-analyst",
        "display_name": "Repair Assurance Intelligence Analyst",
        "agent_version": "3.0",
        "agent": "code-agent",
        "mode": "deterministic-client-fallback",
        "model": None,
        "status": "COMPLETED",
        "confidence": "MEDIUM",
        "risk_level": risk_level,
        "auto_apply": False,
        "summary": (
            f"Prepared {len(guidance)} contract-bound deterministic repair assurance item(s) from Agent 2 evidence because remote AI enrichment was unavailable. "
            "The fallback preserves repair boundaries and does not modify the project automatically."
        ),
        "guidance": guidance,
        "suggested_patch": None,
        "verification": "Complete targeted confirmation for each repair assurance item, then run the relevant full regression workflow before considering the repair verified.",
        "current_knowledge_required": current_required,
        "current_knowledge_reason": current_reason,
        "evidence_lineage": [
            {
                "repair_contract_ref": item["repair_contract_ref"],
                "finding_refs": item["finding_refs"],
                "guidance_status": "LINKED",
            }
            for item in guidance
        ],
        "shadow_validation_status": "NOT_RUN",
        "warnings": [f"Remote Repair Assurance AI was unavailable: {error}"],
        "limitations": [
            "Remote AI enrichment was unavailable for this request; deterministic client-side Repair Assurance was built only from validated Agent 2, runtime, source-review, and local source evidence.",
            "Repair Assurance never modifies the original project automatically.",
            "Shadow Repair Validation was not executed and no patch was generated.",
        ],
        "llm_metrics": None,
        "llm_error": str(error),
    }


def suggest_code_fix_with_agent(
    code_agent_url,
    scan_result,
    execution_result,
    agent_data=None,
    repair_data=None,
    source_review_data=None,
):
    failure_context = get_failure_context(execution_result)
    candidate_paths = repair_assurance_candidate_paths(
        scan_result,
        source_review_data,
        agent_data,
        repair_data,
    )
    source_files = build_repair_assurance_source_files(
        scan_result,
        candidate_paths,
    )

    payload = {
        "project_type": scan_result["project_type"],
        "command": execution_result.get("command") or "",
        "success": execution_result.get("success"),
        "exit_code": execution_result.get("exit_code"),
        "failure_type": failure_context["failure_type"],
        "help_message": failure_context["help_message"],
        "runtime_analysis": agent_data if isinstance(agent_data, dict) else None,
        "source_review": build_repair_assurance_source_review(
            source_review_data
        ),
        "repair_plan": repair_data if isinstance(repair_data, dict) else None,
        "source_files": source_files,
    }

    result = call_repair_assurance_agent(
        payload,
        code_agent_url,
    )

    if not result.get("success"):
        fallback = build_client_repair_assurance_fallback(
            scan_result,
            execution_result,
            agent_data,
            repair_data,
            source_review_data,
            source_files,
            result.get("error") or "Remote Repair Assurance request failed.",
        )
        if fallback is not None:
            return {
                "success": True,
                "data": normalize_code_agent_data(fallback),
                "error": None,
            }
        return result

    data = normalize_code_agent_data(
        result.get("data")
    )

    if data is None:
        fallback = build_client_repair_assurance_fallback(
            scan_result,
            execution_result,
            agent_data,
            repair_data,
            source_review_data,
            source_files,
            "Repair Assurance Intelligence Analyst returned an invalid response.",
        )
        if fallback is not None:
            return {
                "success": True,
                "data": normalize_code_agent_data(fallback),
                "error": None,
            }
        return {
            "success": False,
            "data": None,
            "error": "Repair Assurance Intelligence Analyst returned an invalid response.",
        }

    return {
        "success": True,
        "data": data,
        "error": None,
    }
