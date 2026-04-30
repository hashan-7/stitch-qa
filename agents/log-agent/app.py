from fastapi import FastAPI
from pydantic import BaseModel
from transformers import AutoTokenizer, AutoModelForSeq2SeqLM
import os
import re

HF_MODEL = os.getenv("HF_MODEL", "google/flan-t5-small")

tokenizer = None
model = None

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
        "status": "running",
        "llm_enabled": True,
        "llm_mode": "local-transformers",
        "model": HF_MODEL
    }


def load_model():
    global tokenizer, model

    if tokenizer is None or model is None:
        tokenizer = AutoTokenizer.from_pretrained(HF_MODEL)
        model = AutoModelForSeq2SeqLM.from_pretrained(HF_MODEL)

    return tokenizer, model


def extract_test_result(logs: str):
    match = re.search(
        r"Tests run:\s*(\d+),\s*Failures:\s*(\d+),\s*Errors:\s*(\d+),\s*Skipped:\s*(\d+)",
        logs,
        re.IGNORECASE
    )

    if not match:
        return "Test result could not be extracted from logs."

    tests_run, failures, errors, skipped = match.groups()

    return (
        f"Tests run: {tests_run}, "
        f"Failures: {failures}, "
        f"Errors: {errors}, "
        f"Skipped: {skipped}"
    )


def extract_facts(request: LogAnalysisRequest):
    combined_logs = f"{request.stdout}\n{request.stderr}"
    lower_logs = combined_logs.lower()

    build_status = "SUCCESS" if "build success" in lower_logs else "FAILED"

    test_result = extract_test_result(combined_logs)

    warning_items = []

    if "warning" in lower_logs:
        warning_items.append("Warnings were detected in execution logs.")

    if "mockito" in lower_logs and "dynamic loading of agents" in lower_logs:
        warning_items.append(
            "Mockito dynamic Java agent loading warning was detected. This is not a current test failure, but it may affect future JDK compatibility."
        )

    if not warning_items:
        warning_items.append("No important warning was detected.")

    return {
        "project_type": request.project_type,
        "command": request.command,
        "exit_code": request.exit_code,
        "success": request.success,
        "build_status": build_status,
        "test_result": test_result,
        "warnings": warning_items
    }


def rule_based_analysis(request: LogAnalysisRequest):
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
        "mode": "rule-based",
        "final_status": final_status,
        "summary": "Execution logs analyzed successfully.",
        "issues": issues,
        "warnings": warnings,
        "root_cause": "No blocking runtime error detected." if request.success else "Execution failed. Review errors and stack traces.",
        "recommendation": "Project passed current test execution." if request.success else "Fix the detected error and rerun Stitch QA."
    }


def build_clean_summary(facts, fallback_result):
    warning_text = " ".join(facts["warnings"])

    if facts["success"]:
        return (
            f"The {facts['project_type']} project was executed using `{facts['command']}`. "
            f"The build completed successfully with exit code {facts['exit_code']}. "
            f"{facts['test_result']}. "
            f"No blocking runtime error was detected. "
            f"{warning_text}"
        )

    return (
        f"The {facts['project_type']} project execution failed while running `{facts['command']}`. "
        f"The process ended with exit code {facts['exit_code']}. "
        f"{facts['test_result']}. "
        f"Review the execution logs and stack traces to identify the failing file or test. "
        f"{warning_text}"
    )


def build_prompt(facts):
    warnings_text = " ".join(facts["warnings"])

    return f"""
Rewrite these QA facts into a short professional QA summary.

Project type: {facts["project_type"]}
Command: {facts["command"]}
Build status: {facts["build_status"]}
Exit code: {facts["exit_code"]}
Execution success: {facts["success"]}
Test result: {facts["test_result"]}
Warnings: {warnings_text}

Do not copy raw logs.
Do not include [INFO] lines.
Do not include separator lines.
Write one clean paragraph only.
"""


def call_llm(prompt: str):
    active_tokenizer, active_model = load_model()

    inputs = active_tokenizer(
        prompt,
        return_tensors="pt",
        truncation=True,
        max_length=512
    )

    outputs = active_model.generate(
        **inputs,
        max_new_tokens=160,
        do_sample=False,
        num_beams=2
    )

    return active_tokenizer.decode(outputs[0], skip_special_tokens=True)


def clean_llm_output(text: str):
    cleaned = text.strip()

    bad_patterns = [
        "[INFO]",
        "-----",
        "=====",
        "org.springframework",
        "junitplatform",
        "DemoApplicationTests"
    ]

    if not cleaned:
        return None

    if any(pattern.lower() in cleaned.lower() for pattern in bad_patterns):
        return None

    if len(cleaned) < 25:
        return None

    return cleaned


@app.post("/analyze")
def analyze_logs(request: LogAnalysisRequest):
    fallback_result = rule_based_analysis(request)
    facts = extract_facts(request)
    clean_summary = build_clean_summary(facts, fallback_result)

    try:
        prompt = build_prompt(facts)
        llm_text = call_llm(prompt)
        cleaned_llm_text = clean_llm_output(llm_text)

        final_summary = cleaned_llm_text if cleaned_llm_text else clean_summary

        return {
            "agent": "log-agent",
            "mode": "llm",
            "final_status": "PASS" if request.success else "FAIL",
            "summary": final_summary,
            "issues": fallback_result["issues"],
            "warnings": fallback_result["warnings"],
            "root_cause": "No blocking runtime error detected." if request.success else "Execution failed. Review logs and stack traces.",
            "recommendation": "Project passed current test execution. Review warnings for future compatibility." if request.success else "Fix the detected failure and rerun Stitch QA."
        }

    except Exception as error:
        fallback_result["llm_error"] = repr(error)
        fallback_result["summary"] = clean_summary
        return fallback_result