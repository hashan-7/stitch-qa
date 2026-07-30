from fastapi import FastAPI
from pydantic import BaseModel, Field
from transformers import AutoTokenizer, AutoModelForCausalLM, AutoConfig
import ast
import os
import torch
import re
from collections import Counter

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


class SourceFileInput(BaseModel):
    path: str
    content: str
    truncated: bool = False
    original_chars: int = 0


class SourceReviewRequest(BaseModel):
    project_type: str
    has_tests: bool = False
    files: list[SourceFileInput] = Field(default_factory=list)
    discovered_files_count: int = 0
    submitted_files_count: int = 0
    submitted_chars: int = 0
    truncated_files_count: int = 0
    omitted_files_count: int = 0
    read_error_files_count: int = 0


class SourceFinding(BaseModel):
    id: str
    file_path: str | None = None
    line: int | None = None
    category: str
    severity: str
    confidence: str
    title: str
    evidence: str
    impact: str
    recommendation: str


class SourceReviewResponse(BaseModel):
    agent: str
    mode: str
    status: str
    summary: str
    risk_level: str
    release_recommendation: str
    reviewed_files_count: int
    findings_count: int
    severity_summary: dict[str, int]
    category_summary: dict[str, int]
    findings: list[SourceFinding] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)
    verification: str
    llm_error: str | None = None


@app.get("/")
def health_check():
    return {
        "service": "stitch-qa-code-agent",
        "status": "running",
        "llm_enabled": True,
        "llm_mode": "local-transformers",
        "model": HF_MODEL,
        "capabilities": ["source-review", "code-repair"],
        "endpoints": ["/review-source", "/suggest-code-fix"],
    }


def load_model():
    global tokenizer, model

    if tokenizer is None or model is None:
        config = AutoConfig.from_pretrained(HF_MODEL)
        config.tie_word_embeddings = False

        tokenizer = AutoTokenizer.from_pretrained(HF_MODEL)
        model = AutoModelForCausalLM.from_pretrained(
            HF_MODEL,
            config=config,
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
If the error is "No module named pytest", suggest installing pytest with `pip install pytest`. Do NOT suggest adding `import pytest` to source code.
Do not include system/user/assistant labels.
Do not repeat the prompt.
Do not invent files that are not shown.
Do not apply changes automatically.
Keep the answer concise.
"""


def call_llm(
    prompt: str,
    system_prompt: str = "You are a careful code repair assistant. Return only the final repair guidance.",
    max_input_tokens: int = 1024,
    max_new_tokens: int = 256,
):
    active_tokenizer, active_model = load_model()

    messages = [
        {
            "role": "system",
            "content": system_prompt,
        },
        {
            "role": "user",
            "content": prompt,
        },
    ]

    if hasattr(active_tokenizer, "apply_chat_template"):
        formatted_prompt = active_tokenizer.apply_chat_template(
            messages,
            tokenize=False,
            add_generation_prompt=True,
        )
    else:
        formatted_prompt = prompt

    inputs = active_tokenizer(
        formatted_prompt,
        return_tensors="pt",
        truncation=True,
        max_length=max_input_tokens,
    )

    outputs = active_model.generate(
        **inputs,
        max_new_tokens=max_new_tokens,
        do_sample=False,
        pad_token_id=active_tokenizer.eos_token_id,
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

SEVERITY_ORDER = {
    "CRITICAL": 0,
    "HIGH": 1,
    "MEDIUM": 2,
    "LOW": 3,
    "INFO": 4,
}

SECRET_NAME_PATTERN = re.compile(
    r"(?:password|passwd|secret|token|api[_-]?key|private[_-]?key|access[_-]?key)",
    re.IGNORECASE,
)

PLACEHOLDER_SECRET_VALUES = {
    "",
    "change-me",
    "changeme",
    "example",
    "placeholder",
    "secret",
    "password",
    "token",
    "your-secret",
    "your-token",
}


def dotted_name(node):
    if isinstance(node, ast.Name):
        return node.id

    if isinstance(node, ast.Attribute):
        parent = dotted_name(node.value)
        return f"{parent}.{node.attr}" if parent else node.attr

    return ""


def line_evidence(content, line_number, fallback):
    lines = content.splitlines()

    if line_number and 0 < line_number <= len(lines):
        value = lines[line_number - 1].strip()
        if value:
            return value[:240]

    return fallback


def is_placeholder_secret(value):
    normalized = str(value).strip().lower()

    if normalized in PLACEHOLDER_SECRET_VALUES:
        return True

    return any(
        marker in normalized
        for marker in ("${", "{{", "env.", "process.env", "os.getenv", "system.getenv")
    )


def assignment_target_names(node):
    names = []

    if isinstance(node, ast.Name):
        names.append(node.id)
    elif isinstance(node, (ast.Tuple, ast.List)):
        for item in node.elts:
            names.extend(assignment_target_names(item))
    elif isinstance(node, ast.Attribute):
        names.append(node.attr)

    return names


def keyword_value(call, keyword_name):
    for keyword in call.keywords:
        if keyword.arg == keyword_name:
            return keyword.value

    return None


def is_true_literal(node):
    return isinstance(node, ast.Constant) and node.value is True


def is_false_literal(node):
    return isinstance(node, ast.Constant) and node.value is False


def add_finding(
    findings,
    file_path,
    line,
    category,
    severity,
    confidence,
    title,
    evidence,
    impact,
    recommendation,
):
    findings.append(
        {
            "file_path": file_path,
            "line": line,
            "category": category,
            "severity": severity,
            "confidence": confidence,
            "title": title,
            "evidence": evidence,
            "impact": impact,
            "recommendation": recommendation,
        }
    )


def analyze_python_source(source_file, findings, warnings):
    path = source_file.path
    content = source_file.content

    try:
        tree = ast.parse(content, filename=path)
    except SyntaxError as error:
        if source_file.truncated:
            warnings.append(
                f"{path} could not be fully parsed because the submitted content was truncated."
            )
            return

        add_finding(
            findings,
            path,
            error.lineno,
            "correctness",
            "HIGH",
            "HIGH",
            "Python syntax error",
            error.msg,
            "The module cannot be imported or executed successfully.",
            "Correct the syntax error and rerun Stitch QA before deployment.",
        )
        return

    for node in ast.walk(tree):
        if isinstance(node, (ast.Assign, ast.AnnAssign)):
            value = node.value
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            names = []

            for target in targets:
                names.extend(assignment_target_names(target))

            if (
                isinstance(value, ast.Constant)
                and isinstance(value.value, str)
                and len(value.value.strip()) >= 6
                and any(SECRET_NAME_PATTERN.search(name) for name in names)
                and not is_placeholder_secret(value.value)
            ):
                add_finding(
                    findings,
                    path,
                    getattr(node, "lineno", None),
                    "security",
                    "HIGH",
                    "HIGH",
                    "Possible hardcoded credential",
                    "A credential-like variable is assigned a literal string value.",
                    "Hardcoded credentials can be exposed through source control, logs, or package distribution.",
                    "Move the value to a secret manager or environment variable and rotate any exposed credential.",
                )

        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            defaults = list(node.args.defaults) + [
                item for item in node.args.kw_defaults if item is not None
            ]

            if any(isinstance(default, (ast.List, ast.Dict, ast.Set)) for default in defaults):
                add_finding(
                    findings,
                    path,
                    getattr(node, "lineno", None),
                    "reliability",
                    "MEDIUM",
                    "HIGH",
                    "Mutable function default",
                    f"Function `{node.name}` uses a mutable default argument.",
                    "State can leak between calls and create difficult-to-reproduce defects.",
                    "Use None as the default and create the mutable object inside the function.",
                )

        if isinstance(node, ast.ExceptHandler):
            if node.type is None:
                add_finding(
                    findings,
                    path,
                    getattr(node, "lineno", None),
                    "reliability",
                    "MEDIUM",
                    "HIGH",
                    "Bare exception handler",
                    line_evidence(content, getattr(node, "lineno", None), "A bare except handler was detected."),
                    "SystemExit, KeyboardInterrupt, and unexpected defects can be swallowed.",
                    "Catch only the expected exception types and preserve actionable error context.",
                )

            if node.body and all(isinstance(item, ast.Pass) for item in node.body):
                add_finding(
                    findings,
                    path,
                    getattr(node, "lineno", None),
                    "error-handling",
                    "MEDIUM",
                    "HIGH",
                    "Exception silently ignored",
                    line_evidence(content, getattr(node, "lineno", None), "An exception handler contains only pass."),
                    "Failures can be hidden and leave the application in an unknown state.",
                    "Handle the exception explicitly or log and re-raise it with safe context.",
                )

        if not isinstance(node, ast.Call):
            continue

        function_name = dotted_name(node.func)
        line = getattr(node, "lineno", None)
        evidence = line_evidence(content, line, function_name)

        if function_name in {"eval", "exec", "builtins.eval", "builtins.exec"}:
            add_finding(
                findings,
                path,
                line,
                "security",
                "HIGH",
                "HIGH",
                "Dynamic code execution",
                evidence,
                "Untrusted input can lead to arbitrary code execution.",
                "Remove dynamic execution or replace it with a strict parser and an allowlisted operation set.",
            )

        if function_name == "os.system":
            add_finding(
                findings,
                path,
                line,
                "security",
                "HIGH",
                "HIGH",
                "Shell command execution through os.system",
                evidence,
                "User-controlled values can create operating-system command injection.",
                "Use subprocess with an argument list, shell disabled, validated inputs, and least privilege.",
            )

        if function_name.startswith("subprocess.") and is_true_literal(
            keyword_value(node, "shell")
        ):
            add_finding(
                findings,
                path,
                line,
                "security",
                "HIGH",
                "HIGH",
                "Subprocess executed with shell enabled",
                evidence,
                "Shell interpretation increases command-injection risk.",
                "Disable shell execution and pass validated command arguments as a list.",
            )

        if function_name in {"pickle.load", "pickle.loads"}:
            add_finding(
                findings,
                path,
                line,
                "security",
                "HIGH",
                "HIGH",
                "Unsafe pickle deserialization",
                evidence,
                "Loading attacker-controlled pickle data can execute arbitrary code.",
                "Use a non-executable serialization format and validate data before processing it.",
            )

        if function_name == "yaml.load":
            loader = keyword_value(node, "Loader")
            loader_name = dotted_name(loader) if loader is not None else ""

            if loader_name not in {"yaml.SafeLoader", "yaml.CSafeLoader", "SafeLoader", "CSafeLoader"}:
                add_finding(
                    findings,
                    path,
                    line,
                    "security",
                    "HIGH",
                    "HIGH",
                    "Unsafe YAML loading",
                    evidence,
                    "Unsafe YAML constructors can instantiate arbitrary Python objects.",
                    "Use yaml.safe_load or explicitly select SafeLoader.",
                )

        if function_name.startswith("requests.") and is_false_literal(
            keyword_value(node, "verify")
        ):
            add_finding(
                findings,
                path,
                line,
                "security",
                "HIGH",
                "HIGH",
                "TLS certificate verification disabled",
                evidence,
                "Network traffic can be intercepted by an attacker presenting an untrusted certificate.",
                "Enable certificate verification and configure a trusted CA bundle when required.",
            )

        if function_name in {"hashlib.md5", "hashlib.sha1"}:
            add_finding(
                findings,
                path,
                line,
                "security",
                "MEDIUM",
                "MEDIUM",
                "Weak cryptographic hash",
                evidence,
                "MD5 and SHA-1 are unsuitable for security-sensitive integrity or credential protection.",
                "Use a modern hash such as SHA-256, or a password-specific algorithm such as Argon2 or bcrypt.",
            )

        if function_name.endswith(".run") and is_true_literal(keyword_value(node, "debug")):
            add_finding(
                findings,
                path,
                line,
                "security",
                "MEDIUM",
                "MEDIUM",
                "Debug mode explicitly enabled",
                evidence,
                "Production debug mode can expose sensitive stack traces or interactive debugging features.",
                "Disable debug mode in deployment and control it through environment-specific configuration.",
            )

    if len(content.splitlines()) > 800:
        add_finding(
            findings,
            path,
            1,
            "maintainability",
            "LOW",
            "MEDIUM",
            "Large source file",
            f"The submitted file contains {len(content.splitlines())} lines.",
            "Very large modules are harder to review, test, and maintain safely.",
            "Split unrelated responsibilities into smaller cohesive modules while preserving behavior.",
        )


def analyze_java_source(source_file, findings):
    path = source_file.path
    content = source_file.content
    lines = content.splitlines()

    for index, raw_line in enumerate(lines, start=1):
        line = raw_line.strip()
        secret_match = re.search(
            r'(?i)\b(?:String\s+)?([A-Za-z0-9_]*(?:password|passwd|secret|token|apiKey|api_key|privateKey|accessKey)[A-Za-z0-9_]*)\s*=\s*"([^"]{6,})"',
            line,
        )

        if secret_match and not is_placeholder_secret(secret_match.group(2)):
            add_finding(
                findings,
                path,
                index,
                "security",
                "HIGH",
                "HIGH",
                "Possible hardcoded credential",
                "A credential-like Java variable is assigned a literal string value.",
                "The credential can be exposed through source control, build artifacts, or logs.",
                "Load the value from a protected secret store or environment variable and rotate exposed credentials.",
            )

        if "Runtime.getRuntime().exec" in line:
            add_finding(
                findings,
                path,
                index,
                "security",
                "HIGH",
                "HIGH",
                "Runtime command execution",
                line[:240],
                "Unvalidated command content can lead to operating-system command injection.",
                "Use a fixed command with validated arguments and avoid passing user-controlled shell content.",
            )

        if "new ProcessBuilder" in line:
            add_finding(
                findings,
                path,
                index,
                "security",
                "MEDIUM",
                "MEDIUM",
                "External process creation requires validation",
                line[:240],
                "Untrusted process arguments can create command execution or privilege risks.",
                "Use allowlisted commands, validated argument arrays, controlled working directories, and least privilege.",
            )

        if re.search(r"\bexecute(?:Query|Update)?\s*\([^)]*\+", line):
            add_finding(
                findings,
                path,
                index,
                "security",
                "HIGH",
                "MEDIUM",
                "Possible SQL query concatenation",
                line[:240],
                "Concatenated untrusted values can allow SQL injection.",
                "Use PreparedStatement parameters or an ORM parameter-binding API.",
            )

        if re.search(r'MessageDigest\.getInstance\(\s*"(?:MD5|SHA-1)"', line, re.IGNORECASE):
            add_finding(
                findings,
                path,
                index,
                "security",
                "MEDIUM",
                "HIGH",
                "Weak cryptographic hash",
                line[:240],
                "MD5 and SHA-1 are unsuitable for security-sensitive integrity or credential protection.",
                "Use SHA-256 or stronger, and use a password-specific algorithm for password storage.",
            )

        if ".printStackTrace()" in line:
            add_finding(
                findings,
                path,
                index,
                "error-handling",
                "LOW",
                "HIGH",
                "Stack trace written directly",
                line[:240],
                "Raw stack traces can expose implementation details and bypass structured logging.",
                "Use the project logger with controlled context and avoid exposing sensitive details to clients.",
            )

        if "System.out.print" in line or "System.err.print" in line:
            add_finding(
                findings,
                path,
                index,
                "maintainability",
                "LOW",
                "HIGH",
                "Direct console output in application code",
                line[:240],
                "Console output is difficult to classify, filter, and correlate in production.",
                "Use structured application logging with an appropriate log level.",
            )

        if re.search(r"@CrossOrigin\s*\([^)]*\*", line) or re.search(
            r"allowedOrigins?\s*\([^)]*\*", line, re.IGNORECASE
        ):
            add_finding(
                findings,
                path,
                index,
                "security",
                "MEDIUM",
                "HIGH",
                "Wildcard cross-origin access",
                line[:240],
                "Unrestricted origins can expose APIs to untrusted web applications.",
                "Allow only explicitly trusted origins and review credential-sharing settings.",
            )

        if re.search(r"HostnameVerifier.*->\s*true", line) or "ALLOW_ALL_HOSTNAME_VERIFIER" in line:
            add_finding(
                findings,
                path,
                index,
                "security",
                "CRITICAL",
                "HIGH",
                "TLS hostname verification bypass",
                line[:240],
                "An attacker can impersonate a remote service even when TLS is used.",
                "Remove the permissive verifier and use the platform default hostname and certificate validation.",
            )

    for match in re.finditer(r"catch\s*\([^)]*\)\s*\{\s*\}", content, re.DOTALL):
        line = content.count("\n", 0, match.start()) + 1
        add_finding(
            findings,
            path,
            line,
            "error-handling",
            "MEDIUM",
            "HIGH",
            "Empty Java catch block",
            "A catch block contains no handling logic.",
            "The application can hide failures and continue with invalid state.",
            "Handle the expected exception, preserve safe diagnostic context, or rethrow it appropriately.",
        )

    if len(lines) > 800:
        add_finding(
            findings,
            path,
            1,
            "maintainability",
            "LOW",
            "MEDIUM",
            "Large source file",
            f"The submitted file contains {len(lines)} lines.",
            "Very large classes are harder to review, test, and maintain safely.",
            "Separate unrelated responsibilities into smaller cohesive classes while preserving behavior.",
        )


def deduplicate_findings(findings):
    unique = {}

    for finding in findings:
        key = (
            finding.get("file_path"),
            finding.get("line"),
            finding.get("title"),
        )
        unique[key] = finding

    ordered = sorted(
        unique.values(),
        key=lambda item: (
            SEVERITY_ORDER.get(item.get("severity"), 99),
            str(item.get("file_path") or ""),
            item.get("line") or 0,
            item.get("title") or "",
        ),
    )

    for index, finding in enumerate(ordered, start=1):
        finding["id"] = f"SQ-SRC-{index:03d}"

    return ordered


def build_severity_summary(findings):
    summary = {
        "CRITICAL": 0,
        "HIGH": 0,
        "MEDIUM": 0,
        "LOW": 0,
        "INFO": 0,
    }

    for finding in findings:
        severity = finding.get("severity", "INFO")
        summary[severity] = summary.get(severity, 0) + 1

    return summary


def build_category_summary(findings):
    return dict(sorted(Counter(finding.get("category", "other") for finding in findings).items()))


def build_risk_level(severity_summary):
    for severity in ("CRITICAL", "HIGH", "MEDIUM", "LOW", "INFO"):
        if severity_summary.get(severity, 0):
            return severity

    return "LOW"


def build_release_recommendation(risk_level, partial):
    if risk_level in {"CRITICAL", "HIGH"}:
        return "BLOCK_RELEASE"

    if risk_level == "MEDIUM":
        return "REVIEW_REQUIRED"

    if partial:
        return "MANUAL_REVIEW_REQUIRED"

    return "READY_WITH_CAUTION"


def fallback_source_summary(request, findings, risk_level, release_recommendation):
    if not findings:
        return (
            f"Agent 3 reviewed {len(request.files)} application source files and did not identify "
            "a blocking issue with the implemented checks. This result does not replace manual, "
            "dependency, architecture, or runtime security review."
        )

    severity_summary = build_severity_summary(findings)
    return (
        f"Agent 3 reviewed {len(request.files)} application source files and reported "
        f"{len(findings)} findings. Highest risk is {risk_level}. "
        f"Critical: {severity_summary.get('CRITICAL', 0)}, High: {severity_summary.get('HIGH', 0)}, "
        f"Medium: {severity_summary.get('MEDIUM', 0)}, Low: {severity_summary.get('LOW', 0)}. "
        f"Release recommendation: {release_recommendation}."
    )


def build_source_summary_prompt(request, findings, risk_level, release_recommendation):
    finding_lines = []

    for finding in findings[:20]:
        location = finding.get("file_path") or "Project-level"
        if finding.get("line"):
            location = f"{location}:{finding.get('line')}"
        finding_lines.append(
            f"- [{finding.get('severity')}] {finding.get('title')} at {location}: "
            f"{finding.get('impact')}"
        )

    findings_text = "\n".join(finding_lines) or "- No findings from the implemented checks."

    return f"""
Create a concise professional pre-release source-code QA summary using only the supplied facts.

Project type: {request.project_type}
Reviewed files: {len(request.files)}
Has detected tests: {request.has_tests}
Highest risk: {risk_level}
Release recommendation: {release_recommendation}

Confirmed findings:
{findings_text}

State what was reviewed, the most important confirmed risks, and the required next action.
Do not invent findings, files, runtime results, or successful deployment claims.
Return one short paragraph only.
"""


def clean_source_summary(text):
    cleaned = remove_prompt_leak(text)

    if not cleaned:
        return None

    cleaned = re.sub(r"\n{2,}", " ", cleaned).strip()

    if len(cleaned) < 40:
        return None

    blocked_phrases = [
        "create a concise professional",
        "confirmed findings:",
        "do not invent findings",
        "return one short paragraph",
        "system you are",
        "user you are",
    ]

    if any(phrase in cleaned.lower() for phrase in blocked_phrases):
        return None

    return cleaned[:1600]


def review_source_request(request: SourceReviewRequest):
    findings = []
    warnings = []
    limitations = [
        "This review uses targeted static checks and an AI summary; it does not prove the absence of defects or vulnerabilities.",
        "Dependency vulnerabilities, infrastructure configuration, business-rule correctness, and runtime behavior require separate evidence.",
    ]

    for source_file in request.files:
        suffix = os.path.splitext(source_file.path.lower())[1]

        if suffix == ".py":
            analyze_python_source(source_file, findings, warnings)
        elif suffix == ".java":
            analyze_java_source(source_file, findings)
        else:
            warnings.append(f"Unsupported source extension skipped by Agent 3: {source_file.path}")

        if source_file.truncated:
            warnings.append(
                f"{source_file.path} was truncated before review; findings may not cover the entire file."
            )

    if not request.has_tests:
        add_finding(
            findings,
            None,
            None,
            "testing",
            "MEDIUM",
            "HIGH",
            "No automated tests detected",
            "The project scan did not detect a compatible automated test suite.",
            "Source review alone cannot verify runtime behavior, integrations, regressions, or business rules.",
            "Add focused automated tests for critical flows, validation, error paths, and security-sensitive behavior.",
        )

    findings = deduplicate_findings(findings)
    severity_summary = build_severity_summary(findings)
    category_summary = build_category_summary(findings)
    risk_level = build_risk_level(severity_summary)
    partial = any(
        (
            request.truncated_files_count,
            request.omitted_files_count,
            request.read_error_files_count,
        )
    )
    release_recommendation = build_release_recommendation(risk_level, partial)

    if request.omitted_files_count:
        limitations.append(
            f"{request.omitted_files_count} discovered source files were omitted by client-side review limits."
        )

    if request.read_error_files_count:
        limitations.append(
            f"{request.read_error_files_count} source files could not be read by the CLI."
        )

    if request.truncated_files_count:
        limitations.append(
            f"{request.truncated_files_count} source files were partially reviewed because of size limits."
        )

    status = "PARTIAL" if partial else "COMPLETED"
    mode = "rule-based"
    llm_error = None
    summary = fallback_source_summary(
        request,
        findings,
        risk_level,
        release_recommendation,
    )

    try:
        prompt = build_source_summary_prompt(
            request,
            findings,
            risk_level,
            release_recommendation,
        )
        llm_text = call_llm(
            prompt,
            system_prompt=(
                "You are Agent 3 of Stitch QA, a careful pre-release source-code QA reviewer. "
                "Summarize only confirmed supplied findings and never claim complete safety."
            ),
            max_input_tokens=1536,
            max_new_tokens=220,
        )
        cleaned_summary = clean_source_summary(llm_text)

        if cleaned_summary:
            summary = cleaned_summary
            mode = "hybrid"
    except Exception as error:
        llm_error = repr(error)

    return {
        "agent": "code-agent",
        "mode": mode,
        "status": status,
        "summary": summary,
        "risk_level": risk_level,
        "release_recommendation": release_recommendation,
        "reviewed_files_count": len(request.files),
        "findings_count": len(findings),
        "severity_summary": severity_summary,
        "category_summary": category_summary,
        "findings": findings,
        "warnings": list(dict.fromkeys(warnings)),
        "limitations": limitations,
        "verification": (
            "Manually validate confirmed findings, apply the smallest safe fixes, add or run tests, "
            "and rerun Stitch QA before deployment."
        ),
        "llm_error": llm_error,
    }


@app.post("/review-source", response_model=SourceReviewResponse)
def review_source(request: SourceReviewRequest):
    return review_source_request(request)


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
