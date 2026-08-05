import sys
from pathlib import Path

import click
from rich.console import Console

from stitch_cli.agent_client import (
    analyze_logs_with_agent,
    build_unavailable_code_guidance,
    build_unavailable_log_analysis,
    build_unavailable_repair_guidance,
    build_unavailable_source_review,
    review_source_with_agent,
    suggest_code_fix_with_agent,
    suggest_repair_with_agent,
)
from stitch_cli.code_cli import run_analyze_code
from stitch_cli.executor import build_skipped_result, execute_command
from stitch_cli.reporter import build_qa_decision, generate_report
from stitch_cli.scanner import scan_project

console = Console()


def format_console_list(items):
    if not items:
        return "None"

    return ", ".join(str(item) for item in items)


def build_no_tests_skip_reason(static_map):
    framework = static_map.get("test_framework") or "the detected test framework"
    patterns = format_console_list(static_map.get("test_file_patterns", []))
    return (
        f"No test files compatible with {framework} were detected using the active "
        f"discovery patterns: {patterns}."
    )


def print_source_review_result(source_review_data):
    console.print("\n[bold magenta]Agent 3 Source Code QA Review[/bold magenta]")
    console.print(f"[bold]Status:[/bold] {source_review_data.get('status')}")
    console.print(f"[bold]Mode:[/bold] {source_review_data.get('mode')}")
    console.print(
        f"[bold]Reviewed Files:[/bold] "
        f"{source_review_data.get('reviewed_files_count', 0)}"
    )
    console.print(
        f"[bold]Findings:[/bold] "
        f"{source_review_data.get('findings_count', 0)}"
    )
    console.print(f"[bold]Risk Level:[/bold] {source_review_data.get('risk_level')}")
    console.print(
        f"[bold]Release Recommendation:[/bold] "
        f"{source_review_data.get('release_recommendation')}"
    )
    console.print(f"[bold]Summary:[/bold] {source_review_data.get('summary')}")

    findings = source_review_data.get("findings", [])

    if findings:
        console.print("\n[bold cyan]Source Review Findings[/bold cyan]")
        for finding in findings[:10]:
            location = finding.get("file_path") or "Project"
            if finding.get("line"):
                location = f"{location}:{finding.get('line')}"
            console.print(
                f"- [{finding.get('severity', 'UNKNOWN')}] "
                f"{finding.get('title', 'Source finding')} ({location})"
            )

        if len(findings) > 10:
            console.print(f"... and {len(findings) - 10} more source-review findings")

    for warning in source_review_data.get("warnings", []):
        console.print(
            f"[bold yellow]Source Review Warning:[/bold yellow] {warning}"
        )


def print_log_agent_result(agent_data):
    console.print("\n[bold magenta]Runtime Quality Intelligence Analyst[/bold magenta]")
    console.print(f"[bold]Agent ID:[/bold] {agent_data.get('agent_id')}")
    console.print(f"[bold]Version:[/bold] {agent_data.get('agent_version')}")
    console.print(f"[bold]Mode:[/bold] {agent_data.get('mode', 'unknown')}")
    console.print(f"[bold]Model:[/bold] {agent_data.get('model') or 'Deterministic fallback'}")
    console.print(f"[bold]Execution Status:[/bold] {agent_data.get('execution_status')}")
    console.print(f"[bold]Test Result:[/bold] {agent_data.get('test_result')}")
    console.print(f"[bold]Release Gate:[/bold] {agent_data.get('release_gate')}")
    console.print(f"[bold]Diagnosis Confidence:[/bold] {agent_data.get('diagnosis_confidence')}")
    console.print(f"[bold]Evidence Quality:[/bold] {agent_data.get('evidence_quality')}")
    console.print(f"[bold]Summary:[/bold] {agent_data.get('summary')}")

    run_summary = agent_data.get("run_summary") or {}
    if run_summary:
        console.print("\n[bold cyan]Validated Test Summary[/bold cyan]")
        console.print(f"- Framework: {run_summary.get('framework')}")
        console.print(f"- Command: {run_summary.get('command')}")
        console.print(f"- Total: {run_summary.get('total', 0)}")
        console.print(f"- Passed: {run_summary.get('passed', 0)}")
        console.print(f"- Failed: {run_summary.get('failed', 0)}")
        console.print(f"- Errors: {run_summary.get('errors', 0)}")
        console.print(f"- Skipped: {run_summary.get('skipped', 0)}")
        console.print(f"- Exit Code: {run_summary.get('exit_code')}")
        console.print(f"- Duration: {run_summary.get('duration_seconds')}")
        console.print(f"- Report Source: {run_summary.get('report_source')}")

    groups = agent_data.get("root_cause_groups", [])
    if groups:
        console.print("\n[bold cyan]Root Cause Groups[/bold cyan]")
        for group in groups:
            console.print(
                f"\n[bold]{group.get('group_id')} — {group.get('title')}[/bold]"
            )
            console.print(f"[bold]Category:[/bold] {group.get('category')}")
            console.print(f"[bold]Root Cause:[/bold] {group.get('root_cause')}")
            console.print(f"[bold]Runtime Impact:[/bold] {group.get('runtime_impact')}")
            console.print(f"[bold]Required Action:[/bold] {group.get('required_action')}")
            affected_tests = group.get("affected_tests", [])
            console.print(
                f"[bold]Affected Tests:[/bold] {format_console_list(affected_tests)}"
            )
            for evidence in group.get("evidence", [])[:10]:
                application_location = evidence.get("application_file")
                if application_location and evidence.get("application_line"):
                    application_location = f"{application_location}:{evidence.get('application_line')}"
                test_location = evidence.get("test_file")
                if test_location and evidence.get("test_line"):
                    test_location = f"{test_location}:{evidence.get('test_line')}"
                console.print(
                    "- Evidence: "
                    f"Test={evidence.get('test_name') or 'Unknown'}, "
                    f"Expected={evidence.get('expected') or 'Not available'}, "
                    f"Actual={evidence.get('actual') or evidence.get('exception_type') or 'Not available'}, "
                    f"Application={application_location or 'Not mapped'}, "
                    f"Test Location={test_location or 'Not mapped'}"
                )

    console.print("\n[bold cyan]Required Actions[/bold cyan]")
    for action in agent_data.get("required_actions", []):
        console.print(f"- {action}")
    if not agent_data.get("required_actions"):
        console.print("- None")

    console.print("\n[bold cyan]Verification[/bold cyan]")
    for step in agent_data.get("verification_steps", []):
        console.print(f"- {step}")
    if not agent_data.get("verification_steps"):
        console.print("- None")

    if agent_data.get("warnings"):
        console.print("\n[bold yellow]Warnings[/bold yellow]")
        for warning in agent_data.get("warnings", []):
            console.print(f"- {warning}")

    if agent_data.get("limitations"):
        console.print("\n[bold yellow]Limitations[/bold yellow]")
        for limitation in agent_data.get("limitations", []):
            console.print(f"- {limitation}")

    if agent_data.get("llm_error"):
        console.print("\n[bold red]LLM Fallback Reason[/bold red]")
        console.print(agent_data.get("llm_error"))

def print_repair_agent_result(repair_data):
    console.print(f"[bold]Agent:[/bold] {repair_data.get('agent')}")
    console.print(f"[bold]Mode:[/bold] {repair_data.get('mode', 'unknown')}")
    console.print(f"[bold]Status:[/bold] {repair_data.get('status', 'COMPLETED')}")
    console.print(f"[bold]Risk Level:[/bold] {repair_data.get('risk_level')}")
    console.print(f"[bold]Auto Apply:[/bold] {repair_data.get('auto_apply')}")
    console.print(f"[bold]Summary:[/bold] {repair_data.get('summary')}")
    console.print(f"[bold]Next Action:[/bold] {repair_data.get('next_action')}")

    console.print("\n[bold cyan]Repair Suggestions[/bold cyan]")
    for suggestion in repair_data.get("suggestions", []):
        console.print(f"- {suggestion}")

    if not repair_data.get("suggestions"):
        console.print("- None")

    for warning in repair_data.get("warnings", []):
        console.print(f"[bold yellow]Repair Warning:[/bold yellow] {warning}")


def print_code_agent_result(code_data):
    console.print(f"[bold]Agent:[/bold] {code_data.get('agent')}")
    console.print(f"[bold]Mode:[/bold] {code_data.get('mode', 'unknown')}")
    console.print(f"[bold]Status:[/bold] {code_data.get('status', 'COMPLETED')}")
    console.print(f"[bold]Risk Level:[/bold] {code_data.get('risk_level')}")
    console.print(f"[bold]Auto Apply:[/bold] {code_data.get('auto_apply')}")
    console.print(f"[bold]Summary:[/bold] {code_data.get('summary')}")
    console.print(f"[bold]Verification:[/bold] {code_data.get('verification')}")

    if code_data.get("llm_error"):
        console.print("\n[bold red]Code Agent LLM Error[/bold red]")
        console.print(code_data.get("llm_error"))

    for warning in code_data.get("warnings", []):
        console.print(f"[bold yellow]Code Agent Warning:[/bold yellow] {warning}")


def print_qa_decision(qa_decision):
    console.print("\n[bold green]Combined QA Decision[/bold green]")
    console.print(f"[bold]Final QA Status:[/bold] {qa_decision.get('status')}")
    console.print(f"[bold]Combined Risk Level:[/bold] {qa_decision.get('risk_level')}")
    console.print(
        f"[bold]Release Recommendation:[/bold] "
        f"{qa_decision.get('release_recommendation')}"
    )
    console.print(
        f"[bold]QA Evidence Completeness:[/bold] "
        f"{qa_decision.get('completeness')}"
    )
    console.print(f"[bold]CI Exit Code:[/bold] {qa_decision.get('ci_exit_code')}")

    workflow_status = qa_decision.get("workflow_status", {})
    console.print("\n[bold cyan]Agent Workflow Status[/bold cyan]")
    console.print(
        f"- Agent 3 Source Review: "
        f"{workflow_status.get('source_review', 'NOT_RUN')}"
    )
    console.print(
        f"- Validated Test Execution: "
        f"{workflow_status.get('test_execution', 'NOT_RUN')}"
    )
    console.print(
        f"- Runtime Quality Intelligence: "
        f"{workflow_status.get('log_analysis', 'NOT_REQUESTED')}"
    )
    console.print(
        f"- Agent 2 Repair Guidance: "
        f"{workflow_status.get('repair_guidance', 'NOT_REQUESTED')}"
    )
    console.print(
        f"- Agent 3 Code Repair Guidance: "
        f"{workflow_status.get('code_repair_guidance', 'NOT_REQUESTED')}"
    )

    console.print("\n[bold cyan]Decision Reasons[/bold cyan]")
    for reason in qa_decision.get("reasons", []):
        console.print(f"- {reason}")


@click.group()
def cli():
    pass


@cli.command("analyze-code")
@click.option(
    "--code-agent-url",
    default="https://hashan-77-stitch-qa-code-agent.hf.space",
)
def analyze_code(code_agent_url):
    run_analyze_code(code_agent_url)


@cli.command()
@click.argument("path", required=False, default=".")
@click.option("--run", is_flag=True, help="Run the supported QA workflow.")
@click.option(
    "--analyze",
    is_flag=True,
    help="Send execution logs to the log agent.",
)
@click.option(
    "--repair",
    is_flag=True,
    help="Send execution logs to the repair agent.",
)
@click.option(
    "--code-fix",
    is_flag=True,
    help="Send repair context to the code agent.",
)
@click.option(
    "--agent-url",
    default="https://hashan-77-stitch-qa-log-agent.hf.space",
)
@click.option(
    "--repair-agent-url",
    default="https://hashan-77-stitch-qa-repair-agent.hf.space",
)
@click.option(
    "--code-agent-url",
    default="https://hashan-77-stitch-qa-code-agent.hf.space",
)
def scan(
    path,
    run,
    analyze,
    repair,
    code_fix,
    agent_url,
    repair_agent_url,
    code_agent_url,
):
    try:
        result = scan_project(path)
    except Exception as error:
        console.print(f"[bold red]Scan failed:[/bold red] {error}")
        sys.exit(1)

    console.print("\n[bold green]Stitch QA Scan Started[/bold green]")
    console.print(f"[bold]Project Path:[/bold] {result['project_path']}")
    console.print(f"[bold]Detected Type:[/bold] {result['project_type']}")
    console.print(f"[bold]Total Files:[/bold] {result['total_files']}")
    console.print(f"[bold]Total Folders:[/bold] {result['total_folders']}")
    console.print(f"[bold]Ignored Items:[/bold] {result['ignored_items']}")

    console.print("\n[bold cyan]File Extension Summary[/bold cyan]")
    for extension, count in result["extension_counts"].items():
        console.print(f"- {extension}: {count}")

    static_map = result["static_map"]
    source_review = result.get("source_review", {})

    console.print("\n[bold cyan]Static Mapping[/bold cyan]")
    console.print(f"[bold]Build File:[/bold] {static_map['build_file']}")
    console.print(f"[bold]Main Source Dir:[/bold] {static_map['main_source_dir']}")
    console.print(f"[bold]Test Source Dir:[/bold] {static_map['test_source_dir']}")
    console.print(
        f"[bold]Test Source Dirs:[/bold] "
        f"{format_console_list(static_map.get('test_source_dirs', []))}"
    )
    console.print(f"[bold]Main File:[/bold] {static_map['main_file']}")
    console.print(
        f"[bold]Suggested Command:[/bold] {static_map['suggested_command']}"
    )
    console.print(
        f"[bold]Execution Profile:[/bold] "
        f"{static_map.get('execution_profile')}"
    )
    console.print(
        f"[bold]Execution Policy:[/bold] "
        f"{static_map.get('execution_policy')}"
    )
    console.print(
        f"[bold]Execution Strategy:[/bold] "
        f"{static_map.get('execution_strategy')}"
    )

    console.print("\n[bold cyan]Test Detection[/bold cyan]")
    console.print(
        f"[bold]Tests Found:[/bold] "
        f"{'Yes' if static_map.get('has_tests') else 'No'}"
    )
    console.print(
        f"[bold]Test Files Count:[/bold] "
        f"{static_map.get('test_files_count', 0)}"
    )
    console.print(
        f"[bold]Test Framework:[/bold] "
        f"{static_map.get('test_framework')}"
    )
    console.print(
        f"[bold]Detection Source:[/bold] "
        f"{static_map.get('test_detection_source')}"
    )
    console.print(
        f"[bold]Test File Patterns:[/bold] "
        f"{format_console_list(static_map.get('test_file_patterns', []))}"
    )
    console.print(
        f"[bold]Configured Test Paths:[/bold] "
        f"{format_console_list(static_map.get('configured_test_paths', []))}"
    )

    if static_map.get("test_detection_warning"):
        console.print(
            f"[bold yellow]Detection Warning:[/bold yellow] "
            f"{static_map.get('test_detection_warning')}"
        )

    if static_map.get("test_files"):
        console.print("\n[bold cyan]Detected Test Files[/bold cyan]")
        for file in static_map["test_files"][:20]:
            console.print(f"- {file}")

        if static_map["test_files_count"] > 20:
            console.print(
                f"... and {static_map['test_files_count'] - 20} more test files"
            )

    console.print("\n[bold cyan]Source Review Discovery[/bold cyan]")
    console.print(
        f"[bold]Supported:[/bold] "
        f"{'Yes' if source_review.get('supported') else 'No'}"
    )
    console.print(
        f"[bold]Application Source Files:[/bold] "
        f"{source_review.get('source_files_count', 0)}"
    )
    console.print(
        f"[bold]Source Extensions:[/bold] "
        f"{format_console_list(source_review.get('file_extensions', []))}"
    )
    console.print(
        f"[bold]Excluded Test Files:[/bold] "
        f"{source_review.get('excluded_test_files_count', 0)}"
    )

    if source_review.get("warning"):
        console.print(
            f"[bold yellow]Source Review Warning:[/bold yellow] "
            f"{source_review.get('warning')}"
        )

    if result.get("project_recommendations"):
        console.print("\n[bold yellow]Project Recommendations[/bold yellow]")
        for recommendation in result["project_recommendations"]:
            console.print(f"- {recommendation}")

    console.print("\n[bold cyan]Detected Files[/bold cyan]")
    for file in result["files"][:20]:
        console.print(f"- {file}")

    if result["total_files"] > 20:
        console.print(f"... and {result['total_files'] - 20} more files")

    if (analyze or repair or code_fix) and not run:
        console.print(
            "\n[bold red]Analyze/repair/code-fix requires --run.[/bold red]"
        )
        console.print(
            "Use: stitch scan <path> --run --analyze --repair --code-fix"
        )
        sys.exit(1)

    if code_fix and not repair:
        console.print(
            "\n[bold yellow]Warning:[/bold yellow] "
            "--code-fix works best with --repair."
        )
        console.print(
            "Recommended: stitch scan <path> "
            "--run --analyze --repair --code-fix"
        )

    if not run:
        console.print(
            "\n[bold green]Stitch QA scan completed.[/bold green] "
            "Use --run to start source review and supported test execution."
        )
        return

    agent_data = None
    repair_data = None
    code_data = None
    source_review_data = None
    suggested_command = static_map.get("suggested_command")
    execution_profile = static_map.get("execution_profile")

    if suggested_command is None or execution_profile is None:
        console.print(
            f"\n[bold yellow]Project Type: "
            f"{result['project_type']}[/bold yellow]"
        )
        console.print(
            "[bold yellow]Skipping execution. This project type is not yet "
            "supported in this version.[/bold yellow]"
        )
        console.print(
            f"[bold yellow]{static_map.get('coming_soon_message', '')}"
            f"[/bold yellow]"
        )
        console.print(
            "[bold yellow]Supported: Java Maven (pom.xml), Python "
            "(requirements.txt / pyproject.toml)[/bold yellow]"
        )
        console.print(
            "[bold green]Exiting cleanly with exit code 0.[/bold green]"
        )

        generate_report(
            result,
            None,
            None,
            None,
            None,
            None,
        )
        sys.exit(0)

    console.print("\n[bold magenta]Agent 3 Source Review Started[/bold magenta]")
    source_review_result = review_source_with_agent(
        code_agent_url,
        result,
    )

    if source_review_result["success"]:
        source_review_data = source_review_result["data"]
    else:
        source_review_data = build_unavailable_source_review(
            result,
            source_review_result["error"],
        )

    print_source_review_result(source_review_data)

    if not static_map.get("has_tests"):
        skip_reason = build_no_tests_skip_reason(static_map)
        execution_result = build_skipped_result(
            suggested_command,
            skip_reason,
            execution_profile,
        )

        console.print("\n[bold yellow]Test Execution Skipped[/bold yellow]")
        console.print(f"[bold]Status:[/bold] {execution_result['status']}")
        console.print(
            f"[bold]Command Profile:[/bold] "
            f"{execution_result['command_profile']}"
        )
        console.print(
            f"[bold]Execution Policy:[/bold] "
            f"{execution_result['execution_policy']}"
        )
        console.print(
            f"[bold]Execution Strategy:[/bold] "
            f"{execution_result['execution_strategy']}"
        )
        console.print(
            f"[bold]Shell Enabled:[/bold] "
            f"{execution_result['shell_enabled']}"
        )
        console.print(
            f"[bold]Command Not Run:[/bold] {execution_result['command']}"
        )
        console.print(
            f"[bold]Reason:[/bold] {execution_result['skip_reason']}"
        )
        console.print(
            f"[bold]Exit Code:[/bold] {execution_result['exit_code']}"
        )

        if analyze or repair or code_fix:
            console.print(
                "\n[bold yellow]Runtime Quality Intelligence analysis, Agent 2 repair "
                "guidance, and Agent 3 runtime code guidance were not run "
                "because no test command was executed. Agent 3 source review "
                "was completed independently.[/bold yellow]"
            )
    else:
        console.print("\n[bold magenta]Execution Started[/bold magenta]")

        execution_result = execute_command(
            result["project_path"],
            execution_profile,
            suggested_command,
        )

        console.print(f"[bold]Status:[/bold] {execution_result['status']}")
        console.print(
            f"[bold]Command Profile:[/bold] "
            f"{execution_result['command_profile']}"
        )
        console.print(
            f"[bold]Execution Policy:[/bold] "
            f"{execution_result['execution_policy']}"
        )
        console.print(
            f"[bold]Execution Strategy:[/bold] "
            f"{execution_result['execution_strategy']}"
        )
        console.print(
            f"[bold]Shell Enabled:[/bold] "
            f"{execution_result['shell_enabled']}"
        )
        console.print(
            f"[bold]Validation Status:[/bold] "
            f"{execution_result['validation_status']}"
        )
        console.print(
            f"[bold]Command:[/bold] {execution_result['command']}"
        )
        console.print(
            f"[bold]Resolved Args:[/bold] "
            f"{format_console_list(execution_result.get('command_args', []))}"
        )
        console.print(
            f"[bold]Success:[/bold] {execution_result['success']}"
        )
        console.print(
            f"[bold]Exit Code:[/bold] {execution_result['exit_code']}"
        )
        runtime_evidence = execution_result.get("runtime_evidence") or {}
        test_summary = runtime_evidence.get("test_summary") or {}
        console.print(
            f"[bold]Execution Status:[/bold] "
            f"{runtime_evidence.get('execution_status', 'UNKNOWN')}"
        )
        console.print(
            f"[bold]Test Result:[/bold] "
            f"{runtime_evidence.get('test_result', 'INCONCLUSIVE')}"
        )
        console.print(
            f"[bold]Structured Evidence:[/bold] "
            f"{runtime_evidence.get('evidence_quality', 'NONE')}"
        )
        console.print(
            f"[bold]Test Summary:[/bold] "
            f"Total={test_summary.get('total', 0)}, "
            f"Passed={test_summary.get('passed', 0)}, "
            f"Failed={test_summary.get('failed', 0)}, "
            f"Errors={test_summary.get('errors', 0)}, "
            f"Skipped={test_summary.get('skipped', 0)}"
        )

        console.print("\n[bold cyan]STDOUT[/bold cyan]")
        console.print(
            execution_result["stdout"][-3000:] or "No stdout output.",
            markup=False,
        )

        console.print("\n[bold red]STDERR[/bold red]")
        console.print(
            execution_result["stderr"][-3000:] or "No stderr output.",
            markup=False,
        )

        if analyze:
            console.print(
                "\n[bold magenta]Runtime Quality Intelligence Analyst Started"
                "[/bold magenta]"
            )

            analysis_result = analyze_logs_with_agent(
                agent_url,
                result,
                execution_result,
            )

            if analysis_result["success"]:
                agent_data = analysis_result["data"]
            else:
                agent_data = build_unavailable_log_analysis(
                    analysis_result["error"]
                )

            print_log_agent_result(agent_data)

        if repair:
            console.print(
                "\n[bold magenta]Agent 2 Repair Guidance Started"
                "[/bold magenta]"
            )

            repair_result = suggest_repair_with_agent(
                repair_agent_url,
                result,
                execution_result,
                agent_data,
            )

            if repair_result["success"]:
                repair_data = repair_result["data"]
            else:
                repair_data = build_unavailable_repair_guidance(
                    repair_result["error"]
                )

            print_repair_agent_result(repair_data)

        if code_fix:
            console.print(
                "\n[bold magenta]Agent 3 Code Repair Guidance Started"
                "[/bold magenta]"
            )

            code_result = suggest_code_fix_with_agent(
                code_agent_url,
                result,
                execution_result,
                agent_data,
                repair_data,
            )

            if code_result["success"]:
                code_data = code_result["data"]
            else:
                code_data = build_unavailable_code_guidance(
                    code_result["error"]
                )

            print_code_agent_result(code_data)

    workflow_context = {
        "analyze_requested": bool(analyze),
        "repair_requested": bool(repair),
        "code_fix_requested": bool(code_fix),
    }

    qa_decision = build_qa_decision(
        execution_result,
        source_review_data,
        agent_data,
        repair_data,
        code_data,
        workflow_context,
    )

    print_qa_decision(qa_decision)

    report_path = generate_report(
        result,
        execution_result,
        agent_data,
        repair_data,
        code_data,
        source_review_data,
        qa_decision,
        workflow_context,
    )

    markdown_report_path = Path(report_path)
    json_report_path = markdown_report_path.with_suffix(".json")

    console.print(
        f"\n[bold green]Markdown report generated:[/bold green] "
        f"{markdown_report_path}"
    )
    console.print(
        f"[bold green]JSON report generated:[/bold green] "
        f"{json_report_path}"
    )
    console.print(
        "\n[bold green]Stitch QA scan completed.[/bold green] "
        "Review the generated reports for details."
    )

    if qa_decision.get("ci_exit_code"):
        sys.exit(int(qa_decision["ci_exit_code"]))
