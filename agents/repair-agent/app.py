from fastapi import FastAPI
from pydantic import BaseModel

app = FastAPI(title="Stitch QA Repair Agent")


class RepairRequest(BaseModel):
    project_type: str
    command: str
    success: bool
    exit_code: int | None
    stdout: str
    stderr: str
    root_cause: str | None = None


@app.get("/")
def health_check():
    return {
        "service": "stitch-qa-repair-agent",
        "status": "running"
    }


@app.post("/suggest")
def suggest_repair(request: RepairRequest):
    combined_logs = f"{request.stdout}\n{request.stderr}".lower()

    suggestions = []
    risk_level = "LOW" if request.success else "HIGH"

    if request.success:
        suggestions.append(
            "No blocking fix is required because the project build and tests passed."
        )

    if "mockito" in combined_logs and "dynamic loading of agents" in combined_logs:
        suggestions.append(
            "Mockito dynamic agent warning detected. Consider configuring Mockito as a Java agent in the Maven test configuration for future JDK compatibility."
        )

    if "compilation failure" in combined_logs:
        suggestions.append(
            "Compilation failure detected. Review the Java compiler error line and update the affected source file."
        )

    if "tests run" in combined_logs and ("failures: 1" in combined_logs or "errors: 1" in combined_logs):
        suggestions.append(
            "Test failure detected. Review the failing test method and compare expected vs actual behavior."
        )

    if not suggestions:
        suggestions.append(
            "No specific repair suggestion could be generated from the current logs."
        )

    return {
        "agent": "repair-agent",
        "risk_level": risk_level,
        "auto_apply": False,
        "summary": "Repair suggestions generated successfully.",
        "suggestions": suggestions,
        "next_action": "Review suggestions manually before applying any code changes."
    }