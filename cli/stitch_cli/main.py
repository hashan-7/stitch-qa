import click
from rich.console import Console
from stitch_cli.scanner import scan_project
from stitch_cli.executor import execute_command
from stitch_cli.reporter import generate_report
from stitch_cli.agent_client import (
    analyze_logs_with_agent,
    suggest_repair_with_agent,
    suggest_code_fix_with_agent,
)
from stitch_cli.code_cli import run_analyze_code

console = Console()


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
@click.option("--run", is_flag=True, help="Run the suggested project command.")
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
        return

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

    console.print("\n[bold cyan]Static Mapping[/bold cyan]")
    console.print(f"[bold]Build File:[/bold] {static_map['build_file']}")
    console.print(f"[bold]Main Source Dir:[/bold] {static_map['main_source_dir']}")
    console.print(f"[bold]Test Source Dir:[/bold] {static_map['test_source_dir']}")
    console.print(f"[bold]Main File:[/bold] {static_map['main_file']}")
    console.print(f"[bold]Suggested Command:[/bold] {static_map['suggested_command']}")

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
        console.print("Use: stitch scan demo --run --analyze --repair --code-fix")
        return

    if code_fix and not repair:
        console.print("\n[bold yellow]Warning:[/bold yellow] --code-fix works best with --repair.")
        console.print("Recommended: stitch scan demo --run --analyze --repair --code-fix")

    if run:
        agent_data = None
        repair_data = None
        code_data = None

        console.print("\n[bold magenta]Execution Started[/bold magenta]")

        execution_result = execute_command(
            result["project_path"],
            static_map["suggested_command"],
        )

        console.print(f"[bold]Command:[/bold] {execution_result['command']}")
        console.print(f"[bold]Success:[/bold] {execution_result['success']}")
        console.print(f"[bold]Exit Code:[/bold] {execution_result['exit_code']}")

        console.print("\n[bold cyan]STDOUT[/bold cyan]")
        console.print(execution_result["stdout"][-3000:] or "No stdout output.")

        console.print("\n[bold red]STDERR[/bold red]")
        console.print(execution_result["stderr"][-3000:] or "No stderr output.")

        if analyze:
            console.print("\n[bold magenta]Log Agent Analysis Started[/bold magenta]")

            analysis_result = analyze_logs_with_agent(
                agent_url,
                result,
                execution_result,
            )

            if analysis_result["success"]:
                agent_data = analysis_result["data"]

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

                console.print("\n[bold yellow]Warnings[/bold yellow]")
                for warning in agent_data.get("warnings", []):
                    console.print(f"- {warning}")
            else:
                console.print("[bold red]Log agent request failed.[/bold red]")
                console.print(analysis_result["error"])

        if repair:
            console.print("\n[bold magenta]Repair Agent Started[/bold magenta]")

            repair_result = suggest_repair_with_agent(
                repair_agent_url,
                result,
                execution_result,
                agent_data,
            )

            if repair_result["success"]:
                repair_data = repair_result["data"]

                console.print(f"[bold]Agent:[/bold] {repair_data.get('agent')}")
                console.print(f"[bold]Mode:[/bold] {repair_data.get('mode', 'unknown')}")
                console.print(f"[bold]Risk Level:[/bold] {repair_data.get('risk_level')}")
                console.print(f"[bold]Auto Apply:[/bold] {repair_data.get('auto_apply')}")
                console.print(f"[bold]Summary:[/bold] {repair_data.get('summary')}")
                console.print(f"[bold]Next Action:[/bold] {repair_data.get('next_action')}")

                console.print("\n[bold cyan]Repair Suggestions[/bold cyan]")
                for suggestion in repair_data.get("suggestions", []):
                    console.print(f"- {suggestion}")
            else:
                console.print("[bold red]Repair agent request failed.[/bold red]")
                console.print(repair_result["error"])

        if code_fix:
            console.print("\n[bold magenta]Code Agent Started[/bold magenta]")

            code_result = suggest_code_fix_with_agent(
                code_agent_url,
                result,
                execution_result,
                agent_data,
                repair_data,
            )

            if code_result["success"]:
                code_data = code_result["data"]

                console.print(f"[bold]Agent:[/bold] {code_data.get('agent')}")
                console.print(f"[bold]Mode:[/bold] {code_data.get('mode', 'unknown')}")
                console.print(f"[bold]Risk Level:[/bold] {code_data.get('risk_level')}")
                console.print(f"[bold]Auto Apply:[/bold] {code_data.get('auto_apply')}")
                console.print(f"[bold]Summary:[/bold] {code_data.get('summary')}")
                console.print(f"[bold]Verification:[/bold] {code_data.get('verification')}")

                if code_data.get("llm_error"):
                    console.print("\n[bold red]Code Agent LLM Error[/bold red]")
                    console.print(code_data.get("llm_error"))
            else:
                console.print("[bold red]Code agent request failed.[/bold red]")
                console.print(code_result["error"])

        report_path = generate_report(
            result,
            execution_result,
            agent_data,
            repair_data,
            code_data,
        )
        console.print(f"\n[bold green]Report generated:[/bold green] {report_path}")

    console.print("\n[bold green]Stitch QA scan completed.[/bold green] Review the generated report for details.")
