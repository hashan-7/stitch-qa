import requests
from rich.console import Console
from rich.prompt import Prompt

console = Console()

DEFAULT_CODE_AGENT_URL = "https://hashan-77-stitch-qa-code-agent.hf.space"
DEFAULT_TIMEOUT_SECONDS = 120
SOURCE_REVIEW_TIMEOUT_SECONDS = 240
REPAIR_ASSURANCE_TIMEOUT_SECONDS = 240


def post_code_agent(
    endpoint,
    payload,
    code_agent_url=DEFAULT_CODE_AGENT_URL,
    timeout_seconds=DEFAULT_TIMEOUT_SECONDS,
):
    url = f"{code_agent_url.rstrip('/')}/{endpoint.lstrip('/')}"

    try:
        response = requests.post(
            url,
            json=payload,
            timeout=timeout_seconds,
        )
        response.raise_for_status()

        try:
            data = response.json()
        except ValueError as error:
            return {
                "success": False,
                "data": None,
                "error": f"Code agent returned invalid JSON: {error}",
            }

        if not isinstance(data, dict):
            return {
                "success": False,
                "data": None,
                "error": "Code agent returned an unexpected response format.",
            }

        return {
            "success": True,
            "data": data,
            "error": None,
        }

    except requests.exceptions.RequestException as error:
        return {
            "success": False,
            "data": None,
            "error": str(error),
        }


def call_code_agent(payload, code_agent_url=DEFAULT_CODE_AGENT_URL):
    return post_code_agent(
        "/suggest-code-fix",
        payload,
        code_agent_url,
    )


def call_source_review_agent(payload, code_agent_url=DEFAULT_CODE_AGENT_URL):
    return post_code_agent(
        "/review-source",
        payload,
        code_agent_url,
        SOURCE_REVIEW_TIMEOUT_SECONDS,
    )


def call_repair_assurance_agent(payload, code_agent_url=DEFAULT_CODE_AGENT_URL):
    return post_code_agent(
        "/assure-repair",
        payload,
        code_agent_url,
        REPAIR_ASSURANCE_TIMEOUT_SECONDS,
    )


def read_multiline_input(title):
    console.print(f"\n[bold cyan]{title}[/bold cyan]")
    console.print(
        "Paste content below. Type [bold yellow]END[/bold yellow] "
        "on a new line when done.\n"
    )

    lines = []

    while True:
        line = input()
        if line.strip() == "END":
            break
        lines.append(line)

    return "\n".join(lines).strip()


def run_analyze_code(code_agent_url=DEFAULT_CODE_AGENT_URL):
    console.print("\n[bold green]Stitch QA Code Analysis Started[/bold green]")

    project_type = Prompt.ask(
        "Project type",
        default="Java Maven Project",
    )

    file_path = Prompt.ask(
        "File path",
        default="Unknown file",
    )

    code_snippet = read_multiline_input("Code Snippet")
    error_log = read_multiline_input("Error Log")

    root_cause = Prompt.ask(
        "Root cause",
        default="No root cause provided.",
    )

    repair_summary = Prompt.ask(
        "Repair summary",
        default="No repair summary provided.",
    )

    payload = {
        "project_type": project_type,
        "file_path": file_path,
        "code_snippet": code_snippet,
        "error_log": error_log,
        "root_cause": root_cause,
        "repair_summary": repair_summary,
    }

    console.print(
        "\n[bold magenta]Repair Assurance Intelligence Analyst Started[/bold magenta]"
    )

    result = call_code_agent(payload, code_agent_url)

    if not result["success"]:
        console.print("[bold red]Repair Assurance request failed.[/bold red]")
        console.print(result["error"])
        return

    data = result["data"]

    console.print(
        f"[bold]Agent:[/bold] "
        f"{data.get('display_name') or data.get('agent')}"
    )
    console.print(f"[bold]Mode:[/bold] {data.get('mode')}")
    console.print(f"[bold]Status:[/bold] {data.get('status')}")
    console.print(f"[bold]Risk Level:[/bold] {data.get('risk_level')}")
    console.print(f"[bold]Auto Apply:[/bold] {data.get('auto_apply')}")

    console.print("\n[bold cyan]Repair Assurance Summary[/bold cyan]")
    console.print(data.get("summary"))

    console.print("\n[bold cyan]Verification[/bold cyan]")
    console.print(data.get("verification"))
