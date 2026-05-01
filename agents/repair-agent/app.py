from fastapi import FastAPI
from pydantic import BaseModel
from transformers import AutoTokenizer, AutoModelForSeq2SeqLM
import os

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
        "mode": "rule-based",
        "risk_level": risk_level,
        "auto_apply": False,
        "summary": "Repair suggestions generated successfully.",
        "suggestions": suggestions,
        "next_action": "Review suggestions manually before applying any code changes."
    }


def extract_repair_facts(request: RepairRequest, fallback_result):
    combined_logs = f"{request.stdout}\n{request.stderr}".lower()

    warning_type = "None"

    if "mockito" in combined_logs and "dynamic loading of agents" in combined_logs:
        warning_type = "Mockito dynamic Java agent loading warning"

    build_state = "passed" if request.success else "failed"

    return {
        "project_type": request.project_type,
        "command": request.command,
        "exit_code": request.exit_code,
        "build_state": build_state,
        "root_cause": request.root_cause or "No root cause provided.",
        "warning_type": warning_type,
        "suggestions": fallback_result["suggestions"]
    }


def build_prompt(facts):
    suggestions_text = " ".join(facts["suggestions"])

    return f"""
Rewrite these software repair facts into a short professional repair recommendation.

Project type: {facts["project_type"]}
Command: {facts["command"]}
Build state: {facts["build_state"]}
Exit code: {facts["exit_code"]}
Root cause: {facts["root_cause"]}
Warning type: {facts["warning_type"]}
Suggested actions: {suggestions_text}

Do not copy raw logs.
Write one clear paragraph only.
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


def build_clean_summary(facts):
    if facts["build_state"] == "passed":
        return (
            f"The project passed its current build and test execution, so no blocking code repair is required. "
            f"The main recommendation is to review the detected {facts['warning_type']} and prepare a future-safe Maven/JDK configuration if needed."
        )

    return (
        f"The project execution failed with exit code {facts['exit_code']}. "
        f"Review the detected root cause and apply a targeted code or configuration fix before rerunning Stitch QA."
    )


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