from fastapi import FastAPI
from pydantic import BaseModel
from transformers import AutoTokenizer, AutoModelForCausalLM
import os
import torch
import re

HF_MODEL = os.getenv("HF_MODEL", "Qwen/Qwen2.5-0.5B-Instruct")

tokenizer = None
model = None

app = FastAPI(title="Stitch QA Code Agent")


class CodeRepairRequest(BaseModel):
    project_type: str
    file_path: str | None = None
    code_snippet: str | None = None
    error_log: str | None = None
    root_cause: str | None = None
    repair_summary: str | None = None


@app.get("/")
def health_check():
    return {
        "service": "stitch-qa-code-agent",
        "status": "running",
        "llm_enabled": True,
        "llm_mode": "local-transformers",
        "model": HF_MODEL
    }


def load_model():
    global tokenizer, model

    if tokenizer is None or model is None:
        tokenizer = AutoTokenizer.from_pretrained(HF_MODEL)
        model = AutoModelForCausalLM.from_pretrained(
            HF_MODEL,
            torch_dtype=torch.float32,
            low_cpu_mem_usage=True
        )

    return tokenizer, model


def build_prompt(request: CodeRepairRequest):
    code = request.code_snippet or "No code snippet provided."
    error = request.error_log or "No error log provided."
    root_cause = request.root_cause or "No root cause provided."
    repair_summary = request.repair_summary or "No repair summary provided."
    file_path = request.file_path or "Unknown file"

    return f"""
Analyze the following code repair context and provide safe code-level guidance.

Project type:
{request.project_type}

File path:
{file_path}

Root cause:
{root_cause}

Repair summary:
{repair_summary}

Error log:
{error}

Code snippet:
{code}

Return only these sections:
1. Problem
2. Safe fix approach
3. Suggested code change
4. Verification step

Do not include system/user/assistant labels.
Do not repeat the prompt.
Do not invent files that are not shown.
Do not apply changes automatically.
Keep the answer concise.
"""


def call_llm(prompt: str):
    active_tokenizer, active_model = load_model()

    messages = [
        {
            "role": "system",
            "content": "You are a careful code repair assistant. Return only the final repair guidance."
        },
        {
            "role": "user",
            "content": prompt
        }
    ]

    if hasattr(active_tokenizer, "apply_chat_template"):
        formatted_prompt = active_tokenizer.apply_chat_template(
            messages,
            tokenize=False,
            add_generation_prompt=True
        )
    else:
        formatted_prompt = prompt

    inputs = active_tokenizer(
        formatted_prompt,
        return_tensors="pt",
        truncation=True,
        max_length=1024
    )

    outputs = active_model.generate(
        **inputs,
        max_new_tokens=256,
        do_sample=False,
        pad_token_id=active_tokenizer.eos_token_id
    )

    generated_text = active_tokenizer.decode(outputs[0], skip_special_tokens=True)

    return generated_text.strip()


def fallback_code_guidance(request: CodeRepairRequest):
    if request.error_log:
        summary = (
            "A code-level issue may exist based on the provided error log. "
            "Review the affected file, identify the failing line, apply the smallest safe change, "
            "and rerun the project tests."
        )
    else:
        summary = (
            "No specific error log was provided. Review the code snippet manually and run the project tests "
            "after applying any change."
        )

    return {
        "agent": "code-agent",
        "mode": "fallback",
        "summary": summary,
        "risk_level": "MEDIUM",
        "auto_apply": False,
        "suggested_patch": None,
        "verification": "Rerun Stitch QA after applying any manual code changes."
    }


def remove_prompt_leak(text: str):
    cleaned = text.strip()

    marker_patterns = [
        r"assistant\s*###",
        r"assistant\s*1\.",
        r"assistant\s*Problem",
        r"###\s*1\.\s*Problem",
        r"1\.\s*Problem"
    ]

    for pattern in marker_patterns:
        match = re.search(pattern, cleaned, flags=re.IGNORECASE | re.DOTALL)
        if match:
            cleaned = cleaned[match.start():]
            break

    cleaned = re.sub(r"^\s*assistant\s*", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"^\s*system\s+.*?\s+user\s+", "", cleaned, flags=re.IGNORECASE | re.DOTALL)

    bad_prefixes = [
        "system You are",
        "user You are",
        "Analyze the following code repair context"
    ]

    for prefix in bad_prefixes:
        index = cleaned.lower().find(prefix.lower())
        if index == 0:
            return None

    return cleaned.strip()


def clean_output(text: str):
    cleaned = remove_prompt_leak(text)
    if not cleaned:
        return None

    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    cleaned = cleaned.strip()

    if not cleaned:
        return None

    if len(cleaned) < 30:
        return None

    if "system You are" in cleaned or "user You are" in cleaned:
        return None

    return cleaned


@app.post("/suggest-code-fix")
def suggest_code_fix(request: CodeRepairRequest):
    fallback_result = fallback_code_guidance(request)

    try:
        prompt = build_prompt(request)
        llm_text = call_llm(prompt)
        cleaned_text = clean_output(llm_text)

        if not cleaned_text:
            return fallback_result

        return {
            "agent": "code-agent",
            "mode": "llm",
            "summary": cleaned_text,
            "risk_level": "MEDIUM",
            "auto_apply": False,
            "suggested_patch": None,
            "verification": "Apply the suggested change manually, then rerun Stitch QA verification."
        }

    except Exception as error:
        fallback_result["llm_error"] = repr(error)
        return fallback_result