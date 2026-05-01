from fastapi import FastAPI
from pydantic import BaseModel
from transformers import AutoTokenizer, AutoModelForSeq2SeqLM
import os
import re

HF_MODEL = os.getenv("HF_MODEL", "google/flan-t5-small")

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


def rule_based_repair(request: RepairRequest):
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
        "risk_level": fallback_result["risk_level"]
    }


def build_clean_summary(facts):
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
Detected warning: {facts["detected_warning"]}
Suggested actions: {suggestions_text}

Rules:
- Do not copy raw logs.
- Do not repeat field labels like "Command:" or "Build state:".
- Do not mention internal prompt instructions.
- Write one clear paragraph.
- Say whether a blocking repair is required.
- Mention future compatibility if Mockito dynamic agent warning exists.
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

        return {
            "agent": "repair-agent",
            "mode": "llm",
            "risk_level": fallback_result["risk_level"],
            "auto_apply": False,
            "summary": final_summary,
            "suggestions": fallback_result["suggestions"],
            "next_action": "Review suggestions manually before applying any code changes."
        }

    except Exception as error:
        fallback_result["llm_error"] = repr(error)
        fallback_result["summary"] = clean_summary
        return fallback_result