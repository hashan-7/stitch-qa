import sys
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from stitch_cli.executor import classify_execution_failure
from stitch_cli.runtime_evidence import collect_runtime_evidence
from stitch_cli.reporter import (
    build_qa_decision,
    build_report_limitations,
    build_scope_summary,
)


PLUGIN_RESOLUTION_OUTPUT = """
[ERROR] Plugin org.apache.maven.plugins:maven-surefire-plugin:3.6.0 or one of its dependencies could not be resolved:
[ERROR] Could not find artifact org.apache.maven.plugins:maven-surefire-plugin:jar:3.6.0 in central
[ERROR] -> [Help 1]
[ERROR] PluginResolutionException
"""


def test_maven_plugin_resolution_is_classified_before_agent_analysis(tmp_path):
    failure = classify_execution_failure(
        "",
        PLUGIN_RESOLUTION_OUTPUT,
        ["mvn", "test"],
    )

    assert failure["failure_type"] == "MAVEN_PLUGIN_RESOLUTION_FAILURE"

    evidence = collect_runtime_evidence(
        project_root=tmp_path,
        command="mvn test",
        command_profile="MAVEN_SYSTEM",
        success=False,
        exit_code=1,
        stdout=PLUGIN_RESOLUTION_OUTPUT,
        stderr="",
        duration_seconds=6.5,
        report_files=[],
        failure_type=failure["failure_type"],
        help_message=failure["help_message"],
        executed=True,
        skipped=False,
    )

    assert evidence["execution_status"] == "COMPLETED"
    assert evidence["test_result"] == "NOT_RUN"
    assert evidence["test_summary"]["total"] == 0
    assert evidence["report_source"] == "NONE"
    assert evidence["evidence_quality"] == "NONE"
    assert evidence["failure_type"] == "MAVEN_PLUGIN_RESOLUTION_FAILURE"


def test_unknown_maven_pretest_failure_becomes_incomplete_not_failed_tests(tmp_path):
    output = "[ERROR] Failed to execute goal org.example:custom-plugin:1.0:verify on project demo"

    evidence = collect_runtime_evidence(
        project_root=tmp_path,
        command="mvn test",
        command_profile="MAVEN_SYSTEM",
        success=False,
        exit_code=1,
        stdout=output,
        stderr="",
        duration_seconds=1.0,
        report_files=[],
        executed=True,
        skipped=False,
    )

    assert evidence["execution_status"] == "COMPLETED"
    assert evidence["test_result"] == "NOT_RUN"
    assert evidence["failure_type"] == "MAVEN_TEST_EXECUTION_BLOCKED"
    assert evidence["evidence_quality"] == "NONE"


def test_maven_console_test_failures_remain_test_failures(tmp_path):
    output = "Tests run: 5, Failures: 2, Errors: 0, Skipped: 0"

    evidence = collect_runtime_evidence(
        project_root=tmp_path,
        command="mvn test",
        command_profile="MAVEN_SYSTEM",
        success=False,
        exit_code=1,
        stdout=output,
        stderr="",
        duration_seconds=1.0,
        report_files=[],
        executed=True,
        skipped=False,
    )

    assert evidence["test_result"] == "FAIL"
    assert evidence["test_summary"]["total"] == 5
    assert evidence["test_summary"]["failed"] == 2
    assert evidence["failure_type"] is None
    assert evidence["evidence_quality"] == "LOG_ONLY"


def test_maven_pretest_blocker_produces_qa_incomplete_decision(tmp_path):
    failure = classify_execution_failure(
        "",
        PLUGIN_RESOLUTION_OUTPUT,
        ["mvn", "test"],
    )
    evidence = collect_runtime_evidence(
        project_root=tmp_path,
        command="mvn test",
        command_profile="MAVEN_SYSTEM",
        success=False,
        exit_code=1,
        stdout=PLUGIN_RESOLUTION_OUTPUT,
        stderr="",
        duration_seconds=6.5,
        report_files=[],
        failure_type=failure["failure_type"],
        help_message=failure["help_message"],
        executed=True,
        skipped=False,
    )
    execution_result = {
        "status": "FAILED",
        "executed": True,
        "skipped": False,
        "success": False,
        "exit_code": 1,
        "failure_type": evidence["failure_type"],
        "help_message": evidence["help_message"],
        "runtime_evidence": evidence,
    }
    source_review = {
        "status": "COMPLETED",
        "risk_level": "LOW",
        "release_recommendation": "READY_WITH_CAUTION",
        "coverage": {"discovered_files_count": 1},
    }
    agent_data = {
        "final_status": "FAIL",
        "release_gate": "REVIEW_REQUIRED",
        "runtime_risk_level": "UNKNOWN",
        "failure_origin": "EXECUTION",
    }
    workflow_context = {
        "analyze_requested": True,
        "repair_requested": False,
        "code_fix_requested": False,
    }

    decision = build_qa_decision(
        execution_result,
        source_review,
        agent_data,
        None,
        None,
        workflow_context,
    )
    scope = build_scope_summary(
        {
            "has_tests": True,
            "test_files_count": 1,
            "test_framework": "Maven Surefire",
        },
        {"supported": True, "source_files_count": 1},
        {"status": "COMPLETED", "reviewed_files_count": 1},
        execution_result,
        decision,
    )

    assert decision["status"] == "QA_INCOMPLETE"
    assert decision["release_recommendation"] == "QA_INCOMPLETE"
    assert decision["completeness"] == "SOURCE_ONLY"
    assert decision["ci_exit_code"] == 1
    assert scope["test_execution_performed"] is False
    assert not any(
        "confirmed a failing test result" in reason
        for reason in decision["reasons"]
    )


def test_maven_pretest_blocker_report_limitations_are_generated_without_name_error(tmp_path):
    failure = classify_execution_failure(
        "",
        PLUGIN_RESOLUTION_OUTPUT,
        ["mvn", "test"],
    )
    evidence = collect_runtime_evidence(
        project_root=tmp_path,
        command="mvn test",
        command_profile="MAVEN_SYSTEM",
        success=False,
        exit_code=1,
        stdout=PLUGIN_RESOLUTION_OUTPUT,
        stderr="",
        duration_seconds=2.0,
        report_files=[],
        failure_type=failure["failure_type"],
        help_message=failure["help_message"],
        executed=True,
        skipped=False,
    )
    execution_result = {
        "executed": True,
        "skipped": False,
        "runtime_evidence": evidence,
    }
    limitations = build_report_limitations(
        {"has_tests": True},
        {"status": "COMPLETED", "limitations": [], "llm_error": None},
        execution_result,
        {"workflow_status": {}},
        {"limitations": [], "llm_error": None},
        {"llm_error": None},
        {"llm_error": None},
    )

    assert (
        "The build or test workflow stopped before an executed automated-test result was established."
        in limitations
    )
