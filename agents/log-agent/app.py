from fastapi import FastAPI
from pydantic import BaseModel

app = FastAPI(title="Stitch QA Log Agent")


class LogAnalysisRequest(BaseModel):
    project_type: str
    command: str
    success: bool
    exit_code: int | None
    stdout: str
    stderr: str


@app.get("/")
def health_check():
    return {
        "service": "stitch-qa-log-agent",
        "status": "running"
    }


@app.post("/analyze")
def analyze_logs(request: LogAnalysisRequest):
    issues = []
    warnings = []
    final_status = "PASS" if request.success else "FAIL"

    combined_logs = f"{request.stdout}\n{request.stderr}".lower()

    if "build success" in combined_logs:
        issues.append("Build completed successfully.")

    if "build failure" in combined_logs or "compilation failure" in combined_logs:
        issues.append("Build or compilation failure detected.")

    if "failures: 0" in combined_logs and "errors: 0" in combined_logs:
        issues.append("Tests completed without failures.")

    if "warning" in combined_logs:
        warnings.append("Warnings detected in execution logs.")

    if "mockito" in combined_logs and "dynamic loading of agents" in combined_logs:
        warnings.append(
            "Mockito dynamic agent warning detected. This is not a test failure, but it may require configuration updates for future JDK versions."
        )

    if request.exit_code not in (0, None):
        issues.append(f"Process exited with non-zero exit code: {request.exit_code}")

    return {
        "agent": "log-agent",
        "final_status": final_status,
        "summary": "Execution logs analyzed successfully.",
        "issues": issues,
        "warnings": warnings,
        "root_cause": "No blocking runtime error detected." if request.success else "Execution failed. Review errors and stack traces.",
        "recommendation": "Project passed current test execution." if request.success else "Fix the detected error and rerun Stitch QA."
    }