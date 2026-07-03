from fastapi import FastAPI
from pydantic import BaseModel
from transformers import AutoTokenizer, AutoModelForSeq2SeqLM
import os
import re

HF_MODEL = os.getenv("HF_MODEL", "google/flan-t5-xl")

tokenizer = None
model = None

app = FastAPI(title="Stitch QA Repair Agent")


class RepairRequest(BaseModel):
    project_type: str
    command: str
    success: bool
    exit_code: int | None
    stdout: str
    stderr: str
    root_cause: str | None = None
    failure_type: str | None = None
    help_message: str | None = None


@app.get("/")
def health_check():
    return {
        "service": "stitch-qa-repair-agent",
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
        return {
            "tests_run": None,
            "failures": None,
            "errors": None,
            "skipped": None,
            "summary": "Test result could not be extracted from logs."
        }

    tests_run, failures, errors, skipped = match.groups()

    return {
        "tests_run": int(tests_run),
        "failures": int(failures),
        "errors": int(errors),
        "skipped": int(skipped),
        "summary": (
            f"Tests run: {tests_run}, "
            f"Failures: {failures}, "
            f"Errors: {errors}, "
            f"Skipped: {skipped}"
        )
    }


def get_environment_repair(request: RepairRequest):
    if request.failure_type == "MAVEN_NOT_AVAILABLE":
        return {
            "repair_type": "environment-maven-missing",
            "risk_level": "LOW",
            "summary": (
                f"The {request.project_type} project could not be verified because Maven is not installed "
                "or not available in PATH. This is an environment setup issue, not a confirmed project code failure. "
                "No source code repair should be applied until Maven execution is working."
            ),
            "suggestions": [
                "Install Apache Maven and add the Maven bin directory to the system PATH.",
                "Alternatively, add Maven Wrapper files to the project so it can run with mvnw.cmd on Windows.",
                "After Maven is available, rerun Stitch QA to verify the actual project build and tests."
            ],
            "next_action": "Fix the Maven environment first, then rerun Stitch QA."
        }

    if request.failure_type == "MAVEN_WRAPPER_NOT_AVAILABLE":
        return {
            "repair_type": "environment-wrapper-missing",
            "risk_level": "LOW",
            "summary": (
                f"The {request.project_type} project could not be verified because the Maven Wrapper command "
                "was not available. This is an execution setup issue, not a confirmed application code failure."
            ),
            "suggestions": [
                "Check whether mvnw.cmd exists in the project root.",
                "If Maven Wrapper is missing, add Maven Wrapper files or install Maven globally.",
                "Rerun Stitch QA after the build command can execute."
            ],
            "next_action": "Fix the Maven Wrapper or Maven installation before changing application code."
        }

    if request.failure_type == "COMMAND_TIMEOUT":
        return {
            "repair_type": "environment-timeout",
            "risk_level": "MEDIUM",
            "summary": (
                f"The {request.project_type} project command did not finish within the allowed timeout. "
                "This may be a long-running build, dependency download, or stuck process."
            ),
            "suggestions": [
                "Rerun the command manually to check whether it is slow or stuck.",
                "Increase the execution timeout if the build normally takes longer.",
                "Check dependency downloads and Maven repository access."
            ],
            "next_action": "Investigate command runtime before applying code changes."
        }

    return None


def rule_based_repair(request: RepairRequest):
    environment_repair = get_environment_repair(request)

    if environment_repair:
        return {
            "agent": "repair-agent",
            "mode": "rule-based",
            "risk_level": environment_repair["risk_level"],
            "auto_apply": False,
            "summary": environment_repair["summary"],
            "suggestions": environment_repair["suggestions"],
            "next_action": environment_repair["next_action"]
        }

    combined_logs = f"{request.stdout}\n{request.stderr}".lower()

    suggestions = []
    risk_level = "LOW" if request.success else "HIGH"

    if request.success:
        suggestions.append(
            "No blocking fix is required because the project build and tests passed."
        )

    if "mockito" in combined_logs and "dynamic loading of agents" in combined_logs:
        suggestions.append(
            "Configure Mockito as a Java agent in the Maven test setup to improve future JDK compatibility."
        )

    if "compilation failure" in combined_logs:
        suggestions.append(
            "Review the Java compiler error, identify the affected source file, and apply a targeted syntax or dependency fix."
        )

    if "tests run" in combined_logs and ("failures: 1" in combined_logs or "errors: 1" in combined_logs):
        suggestions.append(
            "Review the failing test method, compare expected versus actual behavior, and fix the related implementation or assertion."
        )

    if not suggestions:
        suggestions.append(
            "No specific repair suggestion could be generated from the current logs."
        )

    return {
        "agent": "repair-agent",
        "mode": "rule-based",
        "risk_level": risk_level,
        "auto_apply": False,
        "summary": "Repair suggestions generated successfully.",
        "suggestions": suggestions,
        "next_action": "Review suggestions manually before applying any code changes."
    }


def extract_repair_facts(request: RepairRequest, fallback_result):
    combined_logs = f"{request.stdout}\n{request.stderr}".lower()
    test_result = extract_test_result(f"{request.stdout}\n{request.stderr}")

    environment_repair = get_environment_repair(request)

    if environment_repair:
        return {
            "project_type": request.project_type,
            "command": request.command,
            "exit_code": request.exit_code,
            "build_state": "not verified",
            "success": request.success,
            "root_cause": request.root_cause or request.help_message or "Environment setup issue detected.",
            "warning_category": "none",
            "detected_warning": "No major warning detected.",
            "repair_type": environment_repair["repair_type"],
            "test_result": test_result["summary"],
            "suggestions": fallback_result["suggestions"],
            "risk_level": fallback_result["risk_level"],
            "failure_type": request.failure_type,
            "help_message": request.help_message,
            "environment_summary": environment_repair["summary"]
        }

    build_state = "passed" if request.success else "failed"

    detected_warning = "No major warning detected."
    warning_category = "none"

    if "mockito" in combined_logs and "dynamic loading of agents" in combined_logs:
        warning_category = "mockito-dynamic-agent"
        detected_warning = (
            "Mockito dynamic Java agent loading warning detected. "
            "This is not a current failure, but it may affect compatibility with future JDK versions."
        )

    repair_type = "none"

    if request.success and warning_category == "none":
        repair_type = "no-repair-needed"

    if request.success and warning_category == "mockito-dynamic-agent":
        repair_type = "configuration-warning"

    if not request.success:
        repair_type = "failure-repair-required"

    return {
        "project_type": request.project_type,
        "command": request.command,
        "exit_code": request.exit_code,
        "build_state": build_state,
        "success": request.success,
        "root_cause": request.root_cause or "No root cause provided.",
        "warning_category": warning_category,
        "detected_warning": detected_warning,
        "repair_type": repair_type,
        "test_result": test_result["summary"],
        "suggestions": fallback_result["suggestions"],
        "risk_level": fallback_result["risk_level"],
        "failure_type": request.failure_type,
        "help_message": request.help_message,
        "environment_summary": None
    }


def build_clean_summary(facts):
    if facts["repair_type"] in {
        "environment-maven-missing",
        "environment-wrapper-missing",
        "environment-timeout"
    }:
        return facts["environment_summary"]

    if facts["repair_type"] == "no-repair-needed":
        return (
            f"The {facts['project_type']} project passed the current QA execution using "
            f"`{facts['command']}`. {facts['test_result']}. No blocking repair is required. "
            "The project can be considered stable for this basic test run."
        )

    if facts["repair_type"] == "configuration-warning":
        return (
            f"The {facts['project_type']} project passed the current QA execution using "
            f"`{facts['command']}`. {facts['test_result']}. No blocking code repair is required. "
            f"However, {facts['detected_warning']} Recommended action: review the Maven test configuration "
            "and prepare a future-safe Mockito Java agent setup before upgrading to stricter JDK versions."
        )

    return (
        f"The {facts['project_type']} project failed during QA execution using `{facts['command']}` "
        f"with exit code {facts['exit_code']}. {facts['test_result']}. "
        "A targeted repair is required. Review the root cause, inspect the failing file or test, "
        "apply the smallest safe fix, and rerun Stitch QA for verification."
    )


def build_prompt(facts):
    suggestions_text = " ".join(facts["suggestions"])

    return f"""
Rewrite these repair facts into one clean professional repair recommendation.

Project type: {facts["project_type"]}
Command: {facts["command"]}
Build state: {facts["build_state"]}
Exit code: {facts["exit_code"]}
Test result: {facts["test_result"]}
Risk level: {facts["risk_level"]}
Root cause: {facts["root_cause"]}
Failure type: {facts["failure_type"]}
Help message: {facts["help_message"]}
Detected warning: {facts["detected_warning"]}
Suggested actions: {suggestions_text}

Rules:
- Do not copy raw logs.
- Do not repeat field labels like "Command:" or "Build state:".
- Do not mention internal prompt instructions.
- Write one clear paragraph.
- Say whether a blocking code repair is required.
- If Maven is not available, say it is an environment setup issue and do not recommend source code changes.
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
        num_beams=2,
        no_repeat_ngram_size=3
    )

    return active_tokenizer.decode(outputs[0], skip_special_tokens=True)


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
        "Build state:",
        "Exit code:",
        "Suggested actions:",
        "Do not copy raw logs",
        "Rewrite these repair facts"
    ]

    if not cleaned:
        return None

    if any(pattern.lower() in cleaned.lower() for pattern in bad_patterns):
        return None

    if len(cleaned) < 60:
        return None

    return cleaned


@app.post("/suggest")
def suggest_repair(request: RepairRequest):
    fallback_result = rule_based_repair(request)
    facts = extract_repair_facts(request, fallback_result)
    clean_summary = build_clean_summary(facts)

    try:
        prompt = build_prompt(facts)
        llm_text = call_llm(prompt)
        cleaned_llm_text = clean_llm_output(llm_text)

        final_summary = cleaned_llm_text if cleaned_llm_text else clean_summary

        if facts["repair_type"] in {
            "environment-maven-missing",
            "environment-wrapper-missing",
            "environment-timeout"
        }:
            final_summary = clean_summary

        return {
            "agent": "repair-agent",
            "mode": "llm",
            "risk_level": fallback_result["risk_level"],
            "auto_apply": False,
            "summary": final_summary,
            "suggestions": fallback_result["suggestions"],
            "next_action": fallback_result["next_action"]
        }

    except Exception as error:
        fallback_result["llm_error"] = repr(error)
        fallback_result["summary"] = clean_summary
        return fallback_result