import os

from fastapi import FastAPI

from model_service import model_service
from prompts import build_analysis_messages
from runtime_analyzer import (
    AGENT_ID,
    AGENT_VERSION,
    DISPLAY_NAME,
    build_base_analysis,
    should_use_llm,
)
from schemas import LogAnalysisRequest, LogAnalysisResponse
from validators import merge_model_output, validate_model_output


LLM_POLICIES = {
    "ALWAYS",
    "ADAPTIVE",
    "FAILURES_ONLY",
    "DISABLED",
}

app = FastAPI(
    title="Stitch QA Runtime Quality Intelligence Analyst",
    version=AGENT_VERSION,
)


def get_llm_policy():
    value = os.getenv("LLM_POLICY", "ADAPTIVE").strip().upper()
    return value if value in LLM_POLICIES else "ADAPTIVE"


def should_attempt_llm(result, policy):
    if not model_service.enabled:
        return False

    if policy == "DISABLED":
        return False

    if policy == "ALWAYS":
        return True

    return should_use_llm(result)


@app.get("/")
def health_check():
    status = model_service.status()
    return {
        "service": "stitch-qa-log-agent",
        "agent_id": AGENT_ID,
        "display_name": DISPLAY_NAME,
        "agent_version": AGENT_VERSION,
        "status": "running",
        "llm_policy": get_llm_policy(),
        "llm": status,
    }


@app.get("/ready")
def readiness_check():
    status = model_service.status()
    return {
        "ready": True,
        "analysis_ready": True,
        "agent_id": AGENT_ID,
        "llm_policy": get_llm_policy(),
        "llm_enabled": status["enabled"],
        "llm_loaded": status["loaded"],
        "llm_state": status["state"],
        "configured_model": status["configured_model"],
        "active_model": status["active_model"],
        "deterministic_fallback": True,
    }


@app.post("/analyze", response_model=LogAnalysisResponse)
def analyze_logs(request: LogAnalysisRequest):
    result = build_base_analysis(request)
    policy = get_llm_policy()

    if not should_attempt_llm(result, policy):
        result["mode"] = "rule-based-validated"
        result["model"] = None
        return LogAnalysisResponse.model_validate(result)

    try:
        messages = build_analysis_messages(result)
        model_text = model_service.generate(messages)
        model_payload = validate_model_output(model_text, result)
        result = merge_model_output(result, model_payload)
        result["mode"] = "hybrid-validated"
        result["model"] = model_service.model_name or model_service.primary_model
        result["llm_metrics"] = model_service.last_generation
        result["llm_error"] = None
    except Exception as error:
        result["mode"] = "rule-based-fallback"
        result["model"] = model_service.model_name or model_service.primary_model
        result["llm_metrics"] = model_service.last_generation
        result["llm_error"] = repr(error)

    return LogAnalysisResponse.model_validate(result)

