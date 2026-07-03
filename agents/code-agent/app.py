from fastapi import FastAPI
from pydantic import BaseModel
from transformers import AutoTokenizer, AutoModelForCausalLM
import os
import torch
import re

HF_MODEL = os.getenv("HF_MODEL", "Qwen/Qwen2.5-Coder-1.5B-Instruct")

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
    failure_type: str | None = None
    help_message: str | None = None
    success: bool | None = None
    exit_code: int | None = None


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


def combined_context(request: CodeRepairRequest):
    return f"""
{request.error_log or ""}
{request.root_cause or ""}
{request.repair_summary or ""}
{request.code_snippet or ""}
""".lower()


def has_mockito_warning(request: CodeRepairRequest):
    context = combined_context(request)

    return (
        "mockito" in context
        and (
            "dynamic loading of agents" in context
            or "dynamic java agent" in context
            or "self-attaching" in context
            or "java agent" in context
        )
    )


def is_successful_execution(request: CodeRepairRequest):
    context = combined_context(request)

    if request.success is True:
        return True

    if request.exit_code == 0:
        return True

    if "passed the current qa execution" in context:
        return True

    if "build completed successfully" in context:
        return True

    if "tests run:" in context and "failures: 0" in context and "errors: 0" in context:
        return True

    if "no blocking runtime error detected" in context:
        return True

    return False


def extract_compile_error_details(request: CodeRepairRequest):
    logs = request.error_log or ""

    if "cannot find symbol" not in logs.lower():
        return None

    file_match = re.search(
        r"([A-Za-z]:[/\\].*?\.java):\[(\d+),(\d+)\]",
        logs
    )

    symbol_match = re.search(
        r"symbol:\s+class\s+([A-Za-z_][A-Za-z0-9_]*)",
        logs,
        re.IGNORECASE
    )

    location_match = re.search(
        r"location:\s+class\s+([A-Za-z0-9_.$]+)",
        logs,
        re.IGNORECASE
    )

    missing_symbol = symbol_match.group(1) if symbol_match else None
    location_class = location_match.group(1) if location_match else None

    line_number = file_match.group(2) if file_match else None
    column_number = file_match.group(3) if file_match else None
    file_path = file_match.group(1) if file_match else request.file_path

    return {
        "error_type": "cannot-find-symbol",
        "file_path": file_path,
        "line_number": line_number,
        "column_number": column_number,
        "missing_symbol": missing_symbol,
        "location_class": location_class,
    }


def get_compile_error_guidance(request: CodeRepairRequest):
    details = extract_compile_error_details(request)

    if not details:
        return None

    code = request.code_snippet or ""
    missing_symbol = details.get("missing_symbol")
    location_class = details.get("location_class") or ""
    short_location_class = location_class.split(".")[-1] if location_class else None

    if (
        missing_symbol
        and short_location_class
        and missing_symbol in code
        and f"{missing_symbol}.class" in code
        and f"{short_location_class}.class" not in code
    ):
        summary = (
            f"Problem: The Maven compile step failed because `{missing_symbol}` cannot be found. "
            f"In `{request.file_path}`, the code references `{missing_symbol}.class`, but the current application class is `{short_location_class}`.\n\n"
            f"Safe fix approach: Replace the incorrect class reference with the existing application class. This is a targeted compile fix for the detected line.\n\n"
            f"Suggested code change: Change `SpringApplication.run({missing_symbol}.class, args);` to "
            f"`SpringApplication.run({short_location_class}.class, args);`.\n\n"
            "Verification step: Rerun `mvnw.cmd test` or Stitch QA and confirm the compilation error is gone."
        )

        return {
            "agent": "code-agent",
            "mode": "rule-based",
            "summary": summary,
            "risk_level": "MEDIUM",
            "auto_apply": False,
            "suggested_patch": (
                f"Replace `{missing_symbol}.class` with `{short_location_class}.class` in `{request.file_path}`."
            ),
            "verification": "Rerun Stitch QA and confirm the Maven compile phase succeeds."
        }

    if missing_symbol:
        summary = (
            f"Problem: The Maven compile step failed because the symbol `{missing_symbol}` could not be found.\n\n"
            "Safe fix approach: Check whether the symbol name is misspelled, whether the class exists, or whether the required import/dependency is missing.\n\n"
            f"Suggested code change: Fix the reference to `{missing_symbol}` by using the correct existing class name, adding the missing import, or adding the required dependency.\n\n"
            "Verification step: Rerun the Maven test command and confirm the compile error is resolved."
        )

        return {
            "agent": "code-agent",
            "mode": "rule-based",
            "summary": summary,
            "risk_level": "MEDIUM",
            "auto_apply": False,
            "suggested_patch": None,
            "verification": "Rerun Stitch QA after applying the targeted compile fix."
        }

    summary = (
        "Problem: The Maven compile step failed with a cannot-find-symbol error.\n\n"
        "Safe fix approach: Inspect the compiler error location, identify the missing class, method, or variable, and apply the smallest targeted fix.\n\n"
        "Suggested code change: Correct the missing or invalid symbol reference in the affected Java file.\n\n"
        "Verification step: Rerun the Maven test command and confirm compilation succeeds."
    )

    return {
        "agent": "code-agent",
        "mode": "rule-based",
        "summary": summary,
        "risk_level": "MEDIUM",
        "auto_apply": False,
        "suggested_patch": None,
        "verification": "Rerun Stitch QA after fixing the cannot-find-symbol error."
    }


def get_successful_execution_guidance(request: CodeRepairRequest):
    if not is_successful_execution(request):
        return None

    if has_mockito_warning(request):
        summary = (
            "Problem: The project build and tests passed successfully, but a Mockito dynamic Java agent loading warning was detected.\n\n"
            "Safe fix approach: This is not a blocking application code failure. Do not change Java source files just because of this warning. "
            "Review the Maven test configuration and prepare a future-safe Mockito Java agent setup for newer JDK compatibility.\n\n"
            "Suggested code change: No application source code change is required. If you want to remove the warning, update the Maven test configuration "
            "to load Mockito as a Java agent according to Mockito documentation.\n\n"
            "Verification step: Rerun the Maven test command and confirm tests still pass with zero failures and zero errors."
        )

        return {
            "agent": "code-agent",
            "mode": "rule-based",
            "summary": summary,
            "risk_level": "LOW",
            "auto_apply": False,
            "suggested_patch": None,
            "verification": "No source-code fix is required. Review Maven test configuration only if you want to address the Mockito warning."
        }

    summary = (
        "Problem: No blocking code-level failure was detected.\n\n"
        "Safe fix approach: The project build and tests passed successfully. No repair should be applied to application source files.\n\n"
        "Suggested code change: No code change is required.\n\n"
        "Verification step: Keep the current passing state and rerun Stitch QA after future changes."
    )

    return {
        "agent": "code-agent",
        "mode": "rule-based",
        "summary": summary,
        "risk_level": "LOW",
        "auto_apply": False,
        "suggested_patch": None,
        "verification": "No code fix is required because the current execution passed."
    }


def get_environment_guidance(request: CodeRepairRequest):
    if request.failure_type == "MAVEN_NOT_AVAILABLE":
        summary = (
            "Problem: Maven is not installed or not available in PATH.\n\n"
            "Safe fix approach: This is an environment setup issue, not an application source code issue. "
            "Do not modify Java source files for this failure.\n\n"
            "Suggested code change: No application code change is required. Install Apache Maven and add the Maven bin directory "
            "to PATH, or add Maven Wrapper files (mvnw, mvnw.cmd, .mvn/wrapper) to the project.\n\n"
            "Verification step: Run `mvn -v` or `mvnw.cmd test` after fixing the environment, then rerun Stitch QA."
        )

        return {
            "agent": "code-agent",
            "mode": "rule-based",
            "summary": summary,
            "risk_level": "LOW",
            "auto_apply": False,
            "suggested_patch": None,
            "verification": "Fix the Maven environment first, then rerun Stitch QA verification."
        }

    if request.failure_type == "MAVEN_WRAPPER_NOT_AVAILABLE":
        summary = (
            "Problem: Maven Wrapper command is missing or cannot be executed.\n\n"
            "Safe fix approach: This is a project execution setup issue, not a confirmed Java source code issue.\n\n"
            "Suggested code change: No application source code change is required. Check whether mvnw.cmd exists in the project root, "
            "or add Maven Wrapper files to the project.\n\n"
            "Verification step: Run `mvnw.cmd test` from the project root after adding or fixing the wrapper."
        )

        return {
            "agent": "code-agent",
            "mode": "rule-based",
            "summary": summary,
            "risk_level": "LOW",
            "auto_apply": False,
            "suggested_patch": None,
            "verification": "Fix Maven Wrapper availability first, then rerun Stitch QA verification."
        }

    if request.failure_type == "COMMAND_TIMEOUT":
        summary = (
            "Problem: The build or test command timed out.\n\n"
            "Safe fix approach: Treat this as an execution/runtime environment issue first. "
            "Do not modify source code until the command behavior is verified manually.\n\n"
            "Suggested code change: No direct code change is recommended from this timeout alone. "
            "Check whether dependency downloads, tests, or build steps are hanging.\n\n"
            "Verification step: Rerun the Maven command manually with a longer timeout and inspect where it stalls."
        )

        return {
            "agent": "code-agent",
            "mode": "rule-based",
            "summary": summary,
            "risk_level": "MEDIUM",
            "auto_apply": False,
            "suggested_patch": None,
            "verification": "Investigate command timeout first, then rerun Stitch QA."
        }

    return None


def build_prompt(request: CodeRepairRequest):
    code = request.code_snippet or "No code snippet provided."
    error = request.error_log or "No error log provided."
    root_cause = request.root_cause or "No root cause provided."
    repair_summary = request.repair_summary or "No repair summary provided."
    file_path = request.file_path or "Unknown file"
    failure_type = request.failure_type or "None"
    help_message = request.help_message or "None"

    return f"""
Analyze the following code repair context and provide safe code-level guidance.

Project type:
{request.project_type}

File path:
{file_path}

Execution success:
{request.success}

Exit code:
{request.exit_code}

Failure type:
{failure_type}

Help message:
{help_message}

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

If execution success is true or exit code is 0, do not say the project failed.
If tests passed and only warnings exist, say no blocking application source code change is required.
If the failure is Maven not available or Maven Wrapper missing, clearly say no application source code change is required.
If the error says cannot find symbol, identify the missing symbol and suggest the smallest targeted fix.
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
    environment_guidance = get_environment_guidance(request)

    if environment_guidance:
        return environment_guidance

    successful_guidance = get_successful_execution_guidance(request)

    if successful_guidance:
        return successful_guidance

    compile_error_guidance = get_compile_error_guidance(request)

    if compile_error_guidance:
        return compile_error_guidance

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
        r"1\.\s*Problem",
        r"\*\*Problem:\*\*",
        r"Problem:"
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
        "Analyze the following code repair context",
        "Return only these sections"
    ]

    for prefix in bad_prefixes:
        index = cleaned.lower().find(prefix.lower())
        if index == 0:
            return None

    return cleaned.strip()


def clean_output(text: str, request: CodeRepairRequest):
    cleaned = remove_prompt_leak(text)
    if not cleaned:
        return None

    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    cleaned = cleaned.strip()

    if not cleaned:
        return None

    if len(cleaned) < 30:
        return None

    bad_patterns = [
        "system You are",
        "user You are",
        "Do not include system/user/assistant labels",
        "Do not repeat the prompt",
        "Do not invent files that are not shown",
        "Do not apply changes automatically",
        "Keep the answer concise"
    ]

    if any(pattern.lower() in cleaned.lower() for pattern in bad_patterns):
        return None

    if is_successful_execution(request):
        incorrect_failure_phrases = [
            "failed to pass",
            "project failed",
            "build failed",
            "tests failed",
            "failed during qa execution"
        ]

        if any(phrase in cleaned.lower() for phrase in incorrect_failure_phrases):
            return None

    return cleaned


@app.post("/suggest-code-fix")
def suggest_code_fix(request: CodeRepairRequest):
    environment_guidance = get_environment_guidance(request)

    if environment_guidance:
        return environment_guidance

    successful_guidance = get_successful_execution_guidance(request)

    if successful_guidance:
        return successful_guidance

    compile_error_guidance = get_compile_error_guidance(request)

    if compile_error_guidance:
        return compile_error_guidance

    fallback_result = fallback_code_guidance(request)

    try:
        prompt = build_prompt(request)
        llm_text = call_llm(prompt)
        cleaned_text = clean_output(llm_text, request)

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