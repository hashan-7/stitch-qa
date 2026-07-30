import sys
import click
from rich.console import Console
from stitch_cli.scanner import scan_project
from stitch_cli.executor import build_skipped_result, execute_command
from stitch_cli.reporter import build_qa_decision, generate_report
from stitch_cli.agent_client import (
    analyze_logs_with_agent,
    build_unavailable_code_guidance,
    build_unavailable_log_analysis,
    build_unavailable_repair_guidance,
    build_unavailable_source_review,
    review_source_with_agent,
    suggest_repair_with_agent,
    suggest_code_fix_with_agent,
)
from stitch_cli.code_cli import run_analyze_code

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
        console.print(f"[bold yellow]Source Review Warning:[/bold yellow] {warning}")


def print_log_agent_result(agent_data):
    console.print(f"[bold]Agent:[/bold] {agent_data.get('agent')}")
    console.print(f"[bold]Mode:[/bold] {agent_data.get('mode', 'unknown')}")
    console.print(f"[bold]Final Status:[/bold] {agent_data.get('final_status')}")
    console.print(f"[bold]Summary:[/bold] {agent_data.get('summary')}")
    console.print(f"[bold]Root Cause:[/bold] {agent_data.get('root_cause')}")
    console.print(f"[bold]Recommendation:[/bold] {agent_data.get('recommendation')}")

    if agent_data.get("llm_error"):
        console.print("\n[bold red]LLM Error[/bold red]")
        console.print(agent_data.get("llm_error"))

    console.print("\n[bold cyan]Issues[/bold cyan]")
    for issue in agent_data.get("issues", []):
        console.print(f"- {issue}")

    if not agent_data.get("issues"):
        console.print("- None")

    console.print("\n[bold yellow]Warnings[/bold yellow]")
    for warning in agent_data.get("warnings", []):
        console.print(f"- {warning}")

    if not agent_data.get("warnings"):
        console.print("- None")


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
@click.option("--analyze", is_flag=True, help="Send execution logs to the log agent.")
@click.option("--repair", is_flag=True, help="Send execution logs to the repair agent.")
@click.option("--code-fix", is_flag=True, help="Send repair context to the code agent.")
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
def scan(path, run, analyze, repair, code_fix, agent_url, repair_agent_url, code_agent_url):
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
    console.print(f"[bold]Suggested Command:[/bold] {static_map['suggested_command']}")
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
        console.print("\n[bold red]Analyze/repair/code-fix requires --run.[/bold red]")
        console.print("Use: stitch scan <path> --run --analyze --repair --code-fix")
        sys.exit(1)

    if code_fix and not repair:
        console.print("\n[bold yellow]Warning:[/bold yellow] --code-fix works best with --repair.")
        console.print("Recommended: stitch scan <path> --run --analyze --repair --code-fix")

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
        console.print(f"\n[bold yellow]Project Type: {result['project_type']}[/bold yellow]")
        console.print(
            "[bold yellow]Skipping execution. This project type is not yet supported "
            "in this version.[/bold yellow]"
        )
        console.print(
            f"[bold yellow]{static_map.get('coming_soon_message', '')}[/bold yellow]"
        )
        console.print(
            "[bold yellow]Supported: Java Maven (pom.xml), Python "
            "(requirements.txt / pyproject.toml)[/bold yellow]"
        )
        console.print("[bold green]Exiting cleanly with exit code 0.[/bold green]")

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
        console.print(f"[bold]Command Profile:[/bold] {execution_result['command_profile']}")
        console.print(f"[bold]Execution Policy:[/bold] {execution_result['execution_policy']}")
        console.print(f"[bold]Execution Strategy:[/bold] {execution_result['execution_strategy']}")
        console.print(f"[bold]Shell Enabled:[/bold] {execution_result['shell_enabled']}")
        console.print(f"[bold]Command Not Run:[/bold] {execution_result['command']}")
        console.print(f"[bold]Reason:[/bold] {execution_result['skip_reason']}")
        console.print(f"[bold]Exit Code:[/bold] {execution_result['exit_code']}")

        if analyze or repair or code_fix:
            console.print(
                "\n[bold yellow]Agent 1 runtime analysis, Agent 2 repair guidance, and "
                "Agent 3 runtime code guidance were not run because no test command "
                "was executed. Agent 3 source review was completed independently.[/bold yellow]"
            )
    else:
        console.print("\n[bold magenta]Execution Started[/bold magenta]")

        execution_result = execute_command(
            result["project_path"],
            execution_profile,
            suggested_command,
        )

        console.print(f"[bold]Status:[/bold] {execution_result['status']}")
        console.print(f"[bold]Command Profile:[/bold] {execution_result['command_profile']}")
        console.print(f"[bold]Execution Policy:[/bold] {execution_result['execution_policy']}")
        console.print(f"[bold]Execution Strategy:[/bold] {execution_result['execution_strategy']}")
        console.print(f"[bold]Shell Enabled:[/bold] {execution_result['shell_enabled']}")
        console.print(f"[bold]Validation Status:[/bold] {execution_result['validation_status']}")
        console.print(f"[bold]Command:[/bold] {execution_result['command']}")
        console.print(
            f"[bold]Resolved Args:[/bold] "
            f"{format_console_list(execution_result.get('command_args', []))}"
        )
        console.print(f"[bold]Success:[/bold] {execution_result['success']}")
        console.print(f"[bold]Exit Code:[/bold] {execution_result['exit_code']}")

        console.print("\n[bold cyan]STDOUT[/bold cyan]")
        console.print(execution_result["stdout"][-3000:] or "No stdout output.")

        console.print("\n[bold red]STDERR[/bold red]")
        console.print(execution_result["stderr"][-3000:] or "No stderr output.")

        if analyze:
            console.print("\n[bold magenta]Agent 1 Runtime Log Analysis Started[/bold magenta]")

            analysis_result = analyze_logs_with_agent(
                agent_url,
                result,
                execution_result,
            )

            if analysis_result["success"]:
                agent_data = analysis_result["data"]
            else:
                agent_data = build_unavailable_log_analysis(analysis_result["error"])

            print_log_agent_result(agent_data)

        if repair:
            console.print("\n[bold magenta]Agent 2 Repair Guidance Started[/bold magenta]")

            repair_result = suggest_repair_with_agent(
                repair_agent_url,
                result,
                execution_result,
                agent_data,
            )

            if repair_result["success"]:
                repair_data = repair_result["data"]
            else:
                repair_data = build_unavailable_repair_guidance(repair_result["error"])

            print_repair_agent_result(repair_data)

        if code_fix:
            console.print("\n[bold magenta]Agent 3 Code Repair Guidance Started[/bold magenta]")

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
                code_data = build_unavailable_code_guidance(code_result["error"])

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
    console.print(f"\n[bold green]Report generated:[/bold green] {report_path}")
    console.print(
        "\n[bold green]Stitch QA scan completed.[/bold green] "
        "Review the generated report for details."
    )

    if qa_decision.get("ci_exit_code"):
        sys.exit(int(qa_decision["ci_exit_code"]))
