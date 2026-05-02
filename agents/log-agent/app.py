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
    failure_type: str | None = None
    help_message: str | None = None


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


def get_environment_issue(request: LogAnalysisRequest):
    if request.failure_type == "MAVEN_NOT_AVAILABLE":
        return {
            "root_cause": "Maven is not installed or not available in PATH.",
            "recommendation": "Install Apache Maven and add it to PATH, or add Maven Wrapper files to this project.",
            "summary": (
                f"The {request.project_type} project could not run `{request.command}` because Maven is not available "
                "in the current system environment. This is an environment setup issue, not a confirmed project code failure."
            ),
            "issue": "Maven command is not available in PATH."
        }

    if request.failure_type == "MAVEN_WRAPPER_NOT_AVAILABLE":
        return {
            "root_cause": "Maven Wrapper command is missing or cannot be executed.",
            "recommendation": "Check that mvnw.cmd exists in the project root or use a valid Maven installation.",
            "summary": (
                f"The {request.project_type} project could not run `{request.command}` because the Maven Wrapper "
                "command was not available. This should be fixed before judging project test results."
            ),
            "issue": "Maven Wrapper command is not available."
        }

    if request.failure_type == "COMMAND_TIMEOUT":
        return {
            "root_cause": "The execution command timed out.",
            "recommendation": "Increase the timeout or check whether the Maven build is stuck.",
            "summary": (
                f"The {request.project_type} project execution did not finish within the allowed time while running "
                f"`{request.command}`."
            ),
            "issue": "Command execution timed out."
        }

    return None


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

    environment_issue = get_environment_issue(request)

    return {
        "project_type": request.project_type,
        "command": request.command,
        "exit_code": request.exit_code,
        "success": request.success,
        "build_status": build_status,
        "test_result": test_result,
        "warnings": warning_items,
        "failure_type": request.failure_type,
        "help_message": request.help_message,
        "environment_issue": environment_issue
    }


def rule_based_analysis(request: LogAnalysisRequest):
    issues = []
    warnings = []
    final_status = "PASS" if request.success else "FAIL"

    combined_logs = f"{request.stdout}\n{request.stderr}".lower()
    environment_issue = get_environment_issue(request)

    if environment_issue:
        issues.append(environment_issue["issue"])

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

    if request.exit_code not in (0, None) and not environment_issue:
        issues.append(f"Process exited with non-zero exit code: {request.exit_code}")

    if environment_issue:
        return {
            "agent": "log-agent",
            "mode": "rule-based",
            "final_status": final_status,
            "summary": environment_issue["summary"],
            "issues": issues,
            "warnings": warnings,
            "root_cause": environment_issue["root_cause"],
            "recommendation": environment_issue["recommendation"]
        }

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
    environment_issue = facts.get("environment_issue")

    if environment_issue:
        return environment_issue["summary"]

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
    failure_type = facts.get("failure_type") or "None"
    help_message = facts.get("help_message") or "None"

    return f"""
Write one short professional QA summary paragraph.

Project type: {facts["project_type"]}
Command: {facts["command"]}
Build status: {facts["build_status"]}
Exit code: {facts["exit_code"]}
Execution success: {facts["success"]}
Test result: {facts["test_result"]}
Failure type: {failure_type}
Help message: {help_message}
Warnings: {warnings_text}

Rules:
- Write only one paragraph.
- Do not repeat the same phrase.
- Do not copy raw logs.
- Do not include field labels.
- Do not include [INFO] lines.
- Do not include separator lines.
- If failure type is MAVEN_NOT_AVAILABLE, say it is an environment setup issue, not a confirmed code failure.
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
        max_new_tokens=140,
        do_sample=False,
        num_beams=2,
        no_repeat_ngram_size=3
    )

    return active_tokenizer.decode(outputs[0], skip_special_tokens=True)


def has_repeated_phrase(text: str, phrase: str, max_count: int = 1):
    return text.lower().count(phrase.lower()) > max_count


def clean_llm_output(text: str):
    cleaned = " ".join(text.strip().split())

    bad_patterns = [
        "[INFO]",
        "-----",
        "=====",
        "org.springframework",
        "junitplatform",
        "DemoApplicationTests",
        "Project type:",
        "Command:",
        "Build status:",
        "Exit code:",
        "Execution success:",
        "Test result:",
        "Failure type:",
        "Help message:",
        "Warnings:",
        "QA summary:",
        "Rewrite these QA facts",
        "Write one short professional QA summary",
        "Do not copy raw logs",
        "Do not include"
    ]

    if not cleaned:
        return None

    if any(pattern.lower() in cleaned.lower() for pattern in bad_patterns):
        return None

    if has_repeated_phrase(cleaned, "Tests run:", 1):
        return None

    if has_repeated_phrase(cleaned, "Failures:", 1):
        return None

    if has_repeated_phrase(cleaned, "Errors:", 1):
        return None

    if len(cleaned) < 40:
        return None

    if len(cleaned) > 700:
        return None

    return cleaned


@app.post("/analyze")
def analyze_logs(request: LogAnalysisRequest):
    fallback_result = rule_based_analysis(request)
    facts = extract_facts(request)
    clean_summary = build_clean_summary(facts, fallback_result)
    environment_issue = facts.get("environment_issue")

    try:
        prompt = build_prompt(facts)
        llm_text = call_llm(prompt)
        cleaned_llm_text = clean_llm_output(llm_text)

        final_summary = cleaned_llm_text if cleaned_llm_text else clean_summary

        if environment_issue:
            final_summary = clean_summary

        return {
            "agent": "log-agent",
            "mode": "llm",
            "final_status": "PASS" if request.success else "FAIL",
            "summary": final_summary,
            "issues": fallback_result["issues"],
            "warnings": fallback_result["warnings"],
            "root_cause": environment_issue["root_cause"] if environment_issue else ("No blocking runtime error detected." if request.success else "Execution failed. Review logs and stack traces."),
            "recommendation": environment_issue["recommendation"] if environment_issue else ("Project passed current test execution. Review warnings for future compatibility." if request.success else "Fix the detected failure and rerun Stitch QA.")
        }

    except Exception as error:
        fallback_result["llm_error"] = repr(error)
        fallback_result["summary"] = clean_summary
        return fallback_result