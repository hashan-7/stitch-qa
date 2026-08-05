import os

from fastapi import FastAPI

from model_service import model_service
from prompts import build_analysis_messages
from runtime_analyzer import AGENT_ID, AGENT_VERSION, DISPLAY_NAME, build_base_analysis, should_use_llm
from schemas import LogAnalysisRequest, LogAnalysisResponse
from validators import merge_model_output, validate_model_output


app = FastAPI(
    title="Stitch QA Runtime Quality Intelligence Analyst",
    version=AGENT_VERSION,
)


@app.get("/")
def health_check():
    status = model_service.status()
    return {
        "service": "stitch-qa-log-agent",
        "agent_id": AGENT_ID,
        "display_name": DISPLAY_NAME,
        "agent_version": AGENT_VERSION,
        "status": "running",
        "llm": status,
    }


@app.get("/ready")
def readiness_check():
    status = model_service.status()
    return {
        "ready": True,
        "agent_id": AGENT_ID,
        "llm_enabled": status["enabled"],
        "llm_loaded": status["loaded"],
        "active_model": status["active_model"],
        "deterministic_fallback": True,
    }


@app.post("/analyze", response_model=LogAnalysisResponse)
def analyze_logs(request: LogAnalysisRequest):
    result = build_base_analysis(request)
    llm_on_pass = os.getenv("LLM_ON_PASS", "false").strip().lower() in {"1", "true", "yes", "on"}
    use_llm = model_service.enabled and (should_use_llm(result) or llm_on_pass)

    if use_llm:
        try:
            messages = build_analysis_messages(result)
            model_text = model_service.generate(messages)
            model_payload = validate_model_output(model_text, result)
            result = merge_model_output(result, model_payload)
            result["mode"] = "hybrid-validated"
            result["model"] = model_service.model_name
        except Exception as error:
            result["mode"] = "rule-based-fallback"
            result["model"] = model_service.model_name
            result["llm_error"] = repr(error)

    return LogAnalysisResponse.model_validate(result)
