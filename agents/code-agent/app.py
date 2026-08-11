import ast
import gc
import json
import os
import re
import threading
import time
from collections import Counter
from typing import Any, Literal

from fastapi import FastAPI
from pydantic import BaseModel, ConfigDict, Field, ValidationError


AGENT_VERSION = "3.0"
SERVICE_NAME = "stitch-qa-code-agent"
SOURCE_AGENT_ID = "source-quality-analyst"
SOURCE_DISPLAY_NAME = "Source Quality Intelligence Analyst"
REPAIR_AGENT_ID = "repair-assurance-analyst"
REPAIR_DISPLAY_NAME = "Repair Assurance Intelligence Analyst"
LEGACY_AGENT_NAME = "code-agent"
MAX_AI_SOURCE_FINDINGS = 8
MAX_REPAIR_CONTRACTS = 8
MAX_SOURCE_CONTEXT_FILES = 8
MAX_SOURCE_CONTEXT_CHARS = 24000
MAX_SOURCE_AI_CONTEXT_CHARS = 18000
MAX_SOURCE_AI_FILES = 6

SEVERITY_ORDER = {
    "CRITICAL": 0,
    "HIGH": 1,
    "MEDIUM": 2,
    "LOW": 3,
    "INFO": 4,
}

RISK_ORDER = {
    "UNKNOWN": -1,
    "NONE": 0,
    "INFO": 1,
    "LOW": 2,
    "MEDIUM": 3,
    "HIGH": 4,
    "CRITICAL": 5,
}

SOURCE_AI_SCHEMA = {
    "type": "object",
    "properties": {
        "c": {"type": "string", "enum": ["HIGH", "MEDIUM", "LOW"]},
        "x": {
            "type": "array",
            "maxItems": MAX_AI_SOURCE_FINDINGS,
            "items": {
                "type": "object",
                "properties": {
                    "f": {"type": "string", "minLength": 1, "maxLength": 500},
                    "l": {"type": "integer", "minimum": 1},
                    "g": {"type": "string", "minLength": 2, "maxLength": 80},
                    "s": {"type": "string", "enum": ["HIGH", "MEDIUM", "LOW", "INFO"]},
                    "t": {"type": "string", "minLength": 6, "maxLength": 140},
                    "i": {"type": "string", "minLength": 8, "maxLength": 220},
                    "r": {"type": "string", "minLength": 8, "maxLength": 240},
                    "k": {"type": "boolean"},
                    "kr": {"type": "string", "maxLength": 160},
                },
                "required": ["f", "l", "g", "s", "t", "i", "r", "k", "kr"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["c", "x"],
    "additionalProperties": False,
}

REPAIR_AI_SCHEMA = {
    "type": "object",
    "properties": {
        "c": {"type": "string", "enum": ["HIGH", "MEDIUM", "LOW"]},
        "x": {
            "type": "array",
            "minItems": 1,
            "maxItems": MAX_REPAIR_CONTRACTS,
            "items": {
                "type": "object",
                "properties": {
                    "r": {"type": "string", "minLength": 1, "maxLength": 80},
                    "f": {
                        "type": "array",
                        "minItems": 1,
                        "maxItems": 16,
                        "uniqueItems": True,
                        "items": {"type": "string", "minLength": 1, "maxLength": 80},
                    },
                    "t": {
                        "type": "array",
                        "maxItems": MAX_SOURCE_CONTEXT_FILES,
                        "uniqueItems": True,
                        "items": {"type": "string", "minLength": 1, "maxLength": 500},
                    },
                    "y": {"type": "string", "minLength": 4, "maxLength": 180},
                    "i": {"type": "string", "minLength": 8, "maxLength": 220},
                    "a": {"type": "string", "minLength": 8, "maxLength": 420},
                    "e": {"type": "string", "minLength": 8, "maxLength": 220},
                    "v": {"type": "string", "minLength": 8, "maxLength": 240},
                    "g": {"type": "string", "minLength": 8, "maxLength": 240},
                    "p": {"type": "string", "maxLength": 900},
                    "k": {"type": "boolean"},
                    "kr": {"type": "string", "maxLength": 160},
                },
                "required": ["r", "f", "t", "y", "i", "a", "e", "v", "g", "p", "k", "kr"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["c", "x"],
    "additionalProperties": False,
}


def env_bool(name, default):
    value = os.getenv(name)
    if value is None:
        return bool(default)
    return value.strip().lower() in {"1", "true", "yes", "on"}


def clean_text(value, limit=800):
    text = " ".join(str(value or "").split()).strip()
    if len(text) <= limit:
        return text
    return text[: limit - 3].rstrip() + "..."


def normalize_list(value):
    if isinstance(value, list):
        return value
    if value is None:
        return []
    return [value]


def normalize_risk(value):
    risk = str(value or "UNKNOWN").upper()
    return risk if risk in RISK_ORDER else "UNKNOWN"


def highest_risk(*values):
    normalized = [normalize_risk(value) for value in values]
    return max(normalized, key=lambda value: RISK_ORDER.get(value, -1), default="UNKNOWN")


class SourceFileInput(BaseModel):
    model_config = ConfigDict(extra="ignore")

    path: str = Field(min_length=1, max_length=500)
    content: str = Field(default="", max_length=60000)
    truncated: bool = False
    original_chars: int = 0


class SourceReviewRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")

    project_type: str = Field(min_length=1, max_length=200)
    has_tests: bool = False
    files: list[SourceFileInput] = Field(default_factory=list, max_length=100)
    discovered_files_count: int = 0
    submitted_files_count: int = 0
    submitted_chars: int = 0
    truncated_files_count: int = 0
    omitted_files_count: int = 0
    read_error_files_count: int = 0


class SourceFinding(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: str
    file_path: str | None = None
    line: int | None = None
    category: str
    severity: Literal["CRITICAL", "HIGH", "MEDIUM", "LOW", "INFO"]
    confidence: Literal["HIGH", "MEDIUM", "LOW"]
    title: str
    evidence: str
    impact: str
    recommendation: str
    detector: str = "deterministic"
    current_knowledge_required: bool = False
    current_knowledge_reason: str | None = None


class SourceReviewResponse(BaseModel):
    model_config = ConfigDict(extra="ignore")

    agent_id: str
    display_name: str
    agent_version: str
    agent: str
    mode: str
    model: str | None = None
    status: str
    confidence: str
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
    current_knowledge_required: bool = False
    current_knowledge_reason: str | None = None
    llm_metrics: dict[str, Any] | None = None
    llm_error: str | None = None


class RepairContractInput(BaseModel):
    model_config = ConfigDict(extra="ignore")

    contract_id: str = Field(min_length=1, max_length=80)
    finding_refs: list[str] = Field(default_factory=list, max_length=16)
    title: str | None = Field(default=None, max_length=220)
    priority: str | None = Field(default=None, max_length=20)
    priority_reason: str | None = Field(default=None, max_length=500)
    repair_objective: str | None = Field(default=None, max_length=700)
    repair_strategy: str | None = Field(default=None, max_length=1000)
    change_boundary: str | None = Field(default=None, max_length=700)
    protected_behavior: str | None = Field(default=None, max_length=700)
    side_effect_risk: str | None = Field(default=None, max_length=40)
    verification: str | None = Field(default=None, max_length=700)
    done_condition: str | None = Field(default=None, max_length=700)
    status: str | None = Field(default=None, max_length=80)


class RepairAssuranceRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")

    project_type: str = Field(min_length=1, max_length=200)
    command: str = Field(default="", max_length=2000)
    success: bool | None = None
    exit_code: int | None = None
    failure_type: str | None = Field(default=None, max_length=200)
    help_message: str | None = Field(default=None, max_length=4000)
    runtime_analysis: dict[str, Any] | None = None
    source_review: dict[str, Any] | None = None
    repair_plan: dict[str, Any] | None = None
    source_files: list[SourceFileInput] = Field(default_factory=list, max_length=MAX_SOURCE_CONTEXT_FILES)
    file_path: str | None = Field(default=None, max_length=500)
    code_snippet: str | None = Field(default=None, max_length=16000)
    error_log: str | None = Field(default=None, max_length=16000)
    root_cause: str | None = Field(default=None, max_length=4000)
    repair_summary: str | None = Field(default=None, max_length=4000)


class RepairAssuranceItem(BaseModel):
    model_config = ConfigDict(extra="ignore")

    guidance_id: str
    repair_contract_ref: str
    finding_refs: list[str]
    target_files: list[str]
    target_symbols: list[str]
    implementation_intent: str
    code_level_approach: str
    change_boundary: str
    protected_behavior: str
    side_effect_considerations: str
    targeted_verification: str
    regression_verification: str
    suggested_patch: str | None = None
    patch_validation_status: str
    current_knowledge_required: bool = False
    current_knowledge_reason: str | None = None
    status: str = "PENDING_IMPLEMENTATION"


class RepairAssuranceResponse(BaseModel):
    model_config = ConfigDict(extra="ignore")

    agent_id: str
    display_name: str
    agent_version: str
    agent: str
    mode: str
    model: str | None = None
    status: str
    confidence: str
    risk_level: str
    auto_apply: bool = False
    summary: str
    guidance: list[RepairAssuranceItem] = Field(default_factory=list)
    suggested_patch: str | None = None
    verification: str
    current_knowledge_required: bool = False
    current_knowledge_reason: str | None = None
    evidence_lineage: list[dict[str, Any]] = Field(default_factory=list)
    shadow_validation_status: str = "NOT_RUN"
    warnings: list[str] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)
    llm_metrics: dict[str, Any] | None = None
    llm_error: str | None = None


class ModelSourceFinding(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    file_path: str = Field(alias="f", min_length=1, max_length=500)
    line: int = Field(alias="l", ge=1)
    category: str = Field(alias="g", min_length=2, max_length=80)
    severity: Literal["HIGH", "MEDIUM", "LOW", "INFO"] = Field(alias="s")
    title: str = Field(alias="t", min_length=6, max_length=140)
    impact: str = Field(alias="i", min_length=8, max_length=220)
    recommendation: str = Field(alias="r", min_length=8, max_length=240)
    current_knowledge_required: bool = Field(alias="k")
    current_knowledge_reason: str = Field(alias="kr", max_length=160)


class ModelSourcePlan(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    confidence: Literal["HIGH", "MEDIUM", "LOW"] = Field(alias="c")
    findings: list[ModelSourceFinding] = Field(alias="x", max_length=MAX_AI_SOURCE_FINDINGS)


class ModelRepairGuidance(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    contract_ref: str = Field(alias="r", min_length=1, max_length=80)
    finding_refs: list[str] = Field(alias="f", min_length=1, max_length=16)
    target_files: list[str] = Field(alias="t", max_length=MAX_SOURCE_CONTEXT_FILES)
    target_symbols_text: str = Field(alias="y", min_length=4, max_length=180)
    implementation_intent: str = Field(alias="i", min_length=8, max_length=220)
    code_level_approach: str = Field(alias="a", min_length=8, max_length=420)
    side_effect_considerations: str = Field(alias="e", min_length=8, max_length=220)
    targeted_verification: str = Field(alias="v", min_length=8, max_length=240)
    regression_verification: str = Field(alias="g", min_length=8, max_length=240)
    suggested_patch: str = Field(alias="p", max_length=900)
    current_knowledge_required: bool = Field(alias="k")
    current_knowledge_reason: str = Field(alias="kr", max_length=160)


class ModelRepairPlan(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    confidence: Literal["HIGH", "MEDIUM", "LOW"] = Field(alias="c")
    guidance: list[ModelRepairGuidance] = Field(alias="x", min_length=1, max_length=MAX_REPAIR_CONTRACTS)


class ModelService:
    def __init__(self):
        self.model_repo = os.getenv(
            "HF_MODEL_REPO",
            "ibm-granite/granite-4.1-3b-GGUF",
        ).strip()
        self.model_file = os.getenv(
            "HF_MODEL_FILE",
            "granite-4.1-3b-Q4_K_M.gguf",
        ).strip()
        self.model_revision = os.getenv(
            "HF_MODEL_REVISION",
            "b628c0ba2ad455695caee93e6a7ac8b3660ad229",
        ).strip()
        self.quantization = os.getenv("MODEL_QUANTIZATION", "Q4_K_M").strip()
        self.primary_model = os.getenv(
            "HF_MODEL",
            f"{self.model_repo}:{self.quantization}",
        ).strip()
        self.cache_dir = os.path.expanduser(
            os.getenv("MODEL_CACHE_DIR", "~/.cache/huggingface/hub").strip()
        )
        self.enabled = env_bool("LLM_ENABLED", True)
        self.local_files_only = env_bool("HF_LOCAL_FILES_ONLY", False)
        self.context_tokens = max(2048, int(os.getenv("MODEL_CONTEXT_TOKENS", "4096")))
        self.batch_tokens = max(64, min(self.context_tokens, int(os.getenv("MODEL_BATCH_TOKENS", "128"))))
        self.source_new_tokens = max(128, int(os.getenv("SOURCE_MODEL_MAX_NEW_TOKENS", "320")))
        self.repair_new_tokens = max(160, int(os.getenv("REPAIR_MODEL_MAX_NEW_TOKENS", "384")))
        self.max_input_tokens = max(1024, int(os.getenv("MODEL_MAX_INPUT_TOKENS", "3000")))
        response_budget = max(self.source_new_tokens, self.repair_new_tokens)
        context_safe_input = max(1024, self.context_tokens - response_budget - 128)
        self.max_input_tokens = min(self.max_input_tokens, context_safe_input)
        self.max_generation_seconds = max(20.0, float(os.getenv("MODEL_MAX_GENERATION_SECONDS", "120")))
        self.threads = max(1, int(os.getenv("MODEL_THREADS", "2")))
        self.threads_batch = max(1, int(os.getenv("MODEL_THREADS_BATCH", str(self.threads))))
        self.temperature = max(0.0, float(os.getenv("MODEL_TEMPERATURE", "0.1")))
        self.top_p = min(1.0, max(0.01, float(os.getenv("MODEL_TOP_P", "0.9"))))
        self.seed = int(os.getenv("MODEL_SEED", "17"))
        self.use_mmap = env_bool("MODEL_USE_MMAP", True)
        self.model = None
        self.model_path = None
        self.model_name = None
        self.load_error = None
        self.load_seconds = None
        self.last_generation = None
        self.load_lock = threading.Lock()
        self.generation_lock = threading.Lock()

    def _download_model(self):
        try:
            from huggingface_hub import hf_hub_download
        except ImportError as error:
            raise RuntimeError("huggingface_hub is required for the Agent 3 GGUF backend.") from error

        return hf_hub_download(
            repo_id=self.model_repo,
            filename=self.model_file,
            revision=self.model_revision,
            cache_dir=self.cache_dir,
            local_files_only=self.local_files_only,
        )

    def _load_model(self):
        try:
            from llama_cpp import Llama
        except ImportError as error:
            raise RuntimeError("llama-cpp-python is required for the Agent 3 GGUF backend.") from error

        model_path = self._download_model()
        model = Llama(
            model_path=model_path,
            n_ctx=self.context_tokens,
            n_batch=self.batch_tokens,
            n_threads=self.threads,
            n_threads_batch=self.threads_batch,
            n_gpu_layers=0,
            seed=self.seed,
            use_mmap=self.use_mmap,
            use_mlock=False,
            verbose=False,
        )
        return model_path, model

    def load(self):
        if not self.enabled:
            raise RuntimeError("LLM inference is disabled.")
        if self.model is not None:
            return self.model

        with self.load_lock:
            if self.model is not None:
                return self.model
            started = time.monotonic()
            try:
                model_path, model = self._load_model()
                self.model_path = model_path
                self.model = model
                self.model_name = self.primary_model
                self.load_error = None
                self.load_seconds = round(time.monotonic() - started, 3)
                return model
            except Exception as error:
                self.model = None
                self.model_path = None
                self.model_name = None
                self.load_error = repr(error)
                self.load_seconds = round(time.monotonic() - started, 3)
                gc.collect()
                raise RuntimeError(self.load_error) from error

    def _count_tokens(self, model, value):
        serialized = json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        try:
            return len(model.tokenize(serialized, add_bos=False, special=True))
        except TypeError:
            return len(model.tokenize(serialized, add_bos=False))

    def _count_text_tokens(self, model, text):
        if not text:
            return 0
        value = str(text).encode("utf-8")
        try:
            return len(model.tokenize(value, add_bos=False, special=True))
        except TypeError:
            return len(model.tokenize(value, add_bos=False))

    def _json_complete(self, text):
        candidate = str(text or "").strip()
        if not candidate.startswith("{") or not candidate.endswith("}"):
            return False
        try:
            json.loads(candidate)
            return True
        except json.JSONDecodeError:
            return False

    def generate_json(self, messages, schema, max_new_tokens, task):
        self.last_generation = None
        model = self.load()
        with self.generation_lock:
            input_tokens = self._count_tokens(model, messages)
            if input_tokens > self.max_input_tokens:
                raise RuntimeError(
                    f"Agent 3 model input contains approximately {input_tokens} tokens, exceeding the configured limit of {self.max_input_tokens}."
                )

            started = time.monotonic()
            parts = []
            finish_reason = None
            timed_out = False
            first_content_seconds = None
            stream = model.create_chat_completion(
                messages=messages,
                response_format={"type": "json_object", "schema": schema},
                max_tokens=max_new_tokens,
                temperature=self.temperature,
                top_p=self.top_p,
                seed=self.seed,
                stream=True,
            )

            try:
                for chunk in stream:
                    elapsed = time.monotonic() - started
                    choices = chunk.get("choices") or []
                    if choices:
                        choice = choices[0]
                        delta = choice.get("delta") or {}
                        content = delta.get("content")
                        if content:
                            if first_content_seconds is None:
                                first_content_seconds = elapsed
                            parts.append(str(content))
                            if self._json_complete("".join(parts)):
                                finish_reason = "json_complete"
                                break
                        if choice.get("finish_reason"):
                            finish_reason = str(choice.get("finish_reason"))
                    if elapsed >= self.max_generation_seconds and not finish_reason:
                        timed_out = True
                        break
            finally:
                close = getattr(stream, "close", None)
                if callable(close):
                    close()

            elapsed = time.monotonic() - started
            text = "".join(parts).strip()
            completion_tokens = self._count_text_tokens(model, text)
            tokens_per_second = (
                round(completion_tokens / elapsed, 3)
                if elapsed > 0 and completion_tokens
                else 0.0
            )
            self.last_generation = {
                "backend": "llama.cpp",
                "task": task,
                "quantization": self.quantization,
                "input_tokens_approx": input_tokens,
                "completion_tokens": completion_tokens,
                "elapsed_seconds": round(elapsed, 3),
                "first_content_seconds": (
                    round(first_content_seconds, 3)
                    if first_content_seconds is not None
                    else None
                ),
                "tokens_per_second": tokens_per_second,
                "finish_reason": finish_reason,
                "timed_out": timed_out,
                "max_generation_seconds": self.max_generation_seconds,
                "max_new_tokens": max_new_tokens,
            }

            if timed_out:
                raise RuntimeError(
                    "Agent 3 model exceeded the configured generation time limit "
                    f"(generated_tokens={completion_tokens}, elapsed_seconds={elapsed:.3f}, "
                    f"tokens_per_second={tokens_per_second:.3f})."
                )
            if not text:
                raise RuntimeError("Agent 3 model returned an empty response.")
            try:
                json.loads(text)
            except json.JSONDecodeError as error:
                raise RuntimeError("Agent 3 JSON-constrained generation returned invalid JSON.") from error
            if finish_reason == "length":
                raise RuntimeError(
                    "Agent 3 model reached the output token limit before completing the structured response."
                )
            return text

    def status(self):
        if not self.enabled:
            state = "disabled"
        elif self.model is not None:
            state = "loaded"
        elif self.load_error:
            state = "load_failed"
        else:
            state = "not_loaded"
        return {
            "enabled": self.enabled,
            "loaded": self.model is not None,
            "state": state,
            "backend": "llama.cpp",
            "configured_model": self.primary_model,
            "active_model": self.model_name,
            "model_repo": self.model_repo,
            "model_file": self.model_file,
            "model_revision": self.model_revision,
            "quantization": self.quantization,
            "load_error": self.load_error,
            "load_seconds": self.load_seconds,
            "context_tokens": self.context_tokens,
            "max_input_tokens": self.max_input_tokens,
            "source_max_new_tokens": self.source_new_tokens,
            "repair_max_new_tokens": self.repair_new_tokens,
            "threads": self.threads,
            "last_generation": self.last_generation,
        }


model_service = ModelService()

app = FastAPI(
    title="Stitch QA Code Quality Intelligence",
    version=AGENT_VERSION,
)


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

CURRENT_KNOWLEDGE_INDICATORS = (
    "version",
    "dependency",
    "deprecated",
    "deprecation",
    "compatibility",
    "cve",
    "security advisory",
    "vendor",
    "framework release",
    "jdk",
    "plugin",
)

ENVIRONMENT_INDICATORS = (
    "maven is not installed",
    "maven wrapper",
    "environment",
    "build-tool availability",
    "build tool availability",
    "path",
    "command timeout",
    "python is not installed",
    "pytest is not installed",
)

TESTING_ONLY_INDICATORS = (
    "no automated tests",
    "missing tests",
    "test files and test configuration",
    "add focused tests",
    "test suite",
)


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
    return any(marker in normalized for marker in ("${", "{{", "env.", "process.env", "os.getenv", "system.getenv"))


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
    detector="deterministic",
    current_knowledge_required=False,
    current_knowledge_reason=None,
):
    findings.append(
        {
            "file_path": file_path,
            "line": line,
            "category": clean_text(category, 80).lower(),
            "severity": severity,
            "confidence": confidence,
            "title": clean_text(title, 180),
            "evidence": clean_text(evidence, 300),
            "impact": clean_text(impact, 500),
            "recommendation": clean_text(recommendation, 600),
            "detector": detector,
            "current_knowledge_required": bool(current_knowledge_required),
            "current_knowledge_reason": clean_text(current_knowledge_reason, 240) or None,
        }
    )


def analyze_python_source(source_file, findings, warnings):
    path = source_file.path
    content = source_file.content
    try:
        tree = ast.parse(content, filename=path)
    except SyntaxError as error:
        if source_file.truncated:
            warnings.append(f"{path} could not be fully parsed because the submitted content was truncated.")
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
            defaults = list(node.args.defaults) + [item for item in node.args.kw_defaults if item is not None]
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
                    "Catch only expected exception types and preserve actionable error context.",
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

        if function_name.startswith("subprocess.") and is_true_literal(keyword_value(node, "shell")):
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

        if function_name.startswith("requests.") and is_false_literal(keyword_value(node, "verify")):
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

        if re.search(r"@CrossOrigin\s*\([^)]*\*", line) or re.search(r"allowedOrigins?\s*\([^)]*\*", line, re.IGNORECASE):
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


def finding_may_need_current_knowledge(finding):
    text = " ".join(
        clean_text(finding.get(key), 500).lower()
        for key in ("title", "category", "evidence", "impact", "recommendation")
    )
    return any(indicator in text for indicator in CURRENT_KNOWLEDGE_INDICATORS)


def build_source_line_index(request):
    index = {}
    for source_file in request.files:
        lines = source_file.content.splitlines()
        index[source_file.path] = lines
    return index


def model_source_payload(request, deterministic_findings):
    file_payload = []
    char_budget = MAX_SOURCE_AI_CONTEXT_CHARS
    used = 0
    for source_file in request.files[:MAX_SOURCE_AI_FILES]:
        remaining = char_budget - used
        if remaining <= 0:
            break
        content = source_file.content[:remaining]
        used += len(content)
        numbered = "\n".join(
            f"{index}: {line}"
            for index, line in enumerate(content.splitlines(), start=1)
        )
        file_payload.append(
            {
                "path": source_file.path,
                "truncated": source_file.truncated,
                "numbered_source": numbered,
            }
        )
    return {
        "project_type": request.project_type,
        "has_tests": request.has_tests,
        "files": file_payload,
        "deterministic_findings": [
            {
                "file": item.get("file_path"),
                "line": item.get("line"),
                "category": item.get("category"),
                "severity": item.get("severity"),
                "title": item.get("title"),
            }
            for item in deterministic_findings[:20]
        ],
    }


def build_source_messages(request, deterministic_findings):
    system = (
        "You are Stitch QA's Source Quality Intelligence Analyst. Review only the supplied Python or Java/Maven application source. "
        "Deterministic findings are locked facts. You may add contextual source findings only when the exact supplied file and line visibly support the issue. "
        "Never invent files, lines, runtime results, dependency versions, vulnerabilities, framework behavior, or business requirements. "
        "Do not repeat deterministic findings. Prefer correctness, reliability, validation, security, performance, maintainability, and testability risks that require contextual reasoning. "
        "AI-only findings must be conservative: use HIGH only for clearly dangerous source behavior visible at the cited line; otherwise use MEDIUM, LOW, or INFO. "
        "Set current knowledge true only when implementation decisions genuinely depend on current version, vendor, compatibility, deprecation, or security-advisory facts. "
        "Return only JSON matching the required schema."
    )
    return [
        {"role": "system", "content": system},
        {
            "role": "user",
            "content": json.dumps(model_source_payload(request, deterministic_findings), ensure_ascii=False, separators=(",", ":")),
        },
    ]


def parse_source_model_output(text):
    try:
        data = json.loads(str(text or "").strip())
    except json.JSONDecodeError as error:
        raise ValueError("The Source Quality model response was not valid JSON.") from error
    try:
        return ModelSourcePlan.model_validate(data)
    except ValidationError as error:
        raise ValueError(f"The Source Quality model response failed schema validation: {error}") from error


def validate_source_ai_findings(plan, request, deterministic_findings):
    line_index = build_source_line_index(request)
    deterministic_keys = {
        (
            str(item.get("file_path") or ""),
            int(item.get("line") or 0),
            str(item.get("title") or "").lower(),
        )
        for item in deterministic_findings
    }
    accepted = []
    for item in plan.findings:
        lines = line_index.get(item.file_path)
        if lines is None or item.line > len(lines):
            continue
        line_text = lines[item.line - 1].strip()
        if not line_text:
            continue
        title = clean_text(item.title, 180)
        key = (item.file_path, item.line, title.lower())
        if key in deterministic_keys:
            continue
        severity = item.severity
        if severity == "HIGH":
            high_signal = any(
                token in line_text.lower()
                for token in (
                    "eval(",
                    "exec(",
                    "os.system",
                    "shell=true",
                    "runtime.getruntime().exec",
                    "allow_all_hostname_verifier",
                    "hostnameverifier",
                    "verify=false",
                    "pickle.load",
                )
            )
            if not high_signal:
                severity = "MEDIUM"
        current_required = bool(item.current_knowledge_required) and any(
            indicator in " ".join(
                [item.category.lower(), title.lower(), item.impact.lower(), item.recommendation.lower()]
            )
            for indicator in CURRENT_KNOWLEDGE_INDICATORS
        )
        add_finding(
            accepted,
            item.file_path,
            item.line,
            clean_text(item.category, 80),
            severity,
            "MEDIUM",
            title,
            line_text[:240],
            item.impact,
            item.recommendation,
            detector="ai-contextual-validated",
            current_knowledge_required=current_required,
            current_knowledge_reason=(item.current_knowledge_reason if current_required else None),
        )
    return accepted


def deduplicate_findings(findings):
    unique = {}
    for finding in findings:
        key = (
            finding.get("file_path"),
            finding.get("line"),
            clean_text(finding.get("title"), 180).lower(),
        )
        existing = unique.get(key)
        if existing is None:
            unique[key] = finding
            continue
        if SEVERITY_ORDER.get(finding.get("severity"), 99) < SEVERITY_ORDER.get(existing.get("severity"), 99):
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
    summary = {"CRITICAL": 0, "HIGH": 0, "MEDIUM": 0, "LOW": 0, "INFO": 0}
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


def build_source_summary(request, findings, risk_level, release_recommendation):
    if not findings:
        return (
            f"Reviewed {len(request.files)} application source file(s) and found no blocking issue with the implemented deterministic and validated contextual checks. "
            "This does not prove the absence of defects, vulnerabilities, dependency risks, business-rule errors, or runtime failures."
        )
    severity_summary = build_severity_summary(findings)
    return (
        f"Reviewed {len(request.files)} application source file(s) and reported {len(findings)} evidence-grounded finding(s). "
        f"Highest source risk is {risk_level}. Critical: {severity_summary.get('CRITICAL', 0)}, High: {severity_summary.get('HIGH', 0)}, "
        f"Medium: {severity_summary.get('MEDIUM', 0)}, Low: {severity_summary.get('LOW', 0)}. Release recommendation: {release_recommendation}."
    )


def review_source_request(request):
    deterministic = []
    warnings = []
    limitations = [
        "Source Quality Intelligence combines targeted deterministic checks with bounded AI reasoning; it does not prove the absence of defects or vulnerabilities.",
        "AI contextual reasoning uses a bounded source window for CPU reliability; deterministic checks still evaluate every submitted supported source file.",
        "Dependency vulnerabilities, infrastructure configuration, business-rule correctness, and runtime behavior require separate evidence.",
    ]

    for source_file in request.files:
        suffix = os.path.splitext(source_file.path.lower())[1]
        if suffix == ".py":
            analyze_python_source(source_file, deterministic, warnings)
        elif suffix == ".java":
            analyze_java_source(source_file, deterministic)
        else:
            warnings.append(f"Unsupported source extension skipped by Source Quality Intelligence: {source_file.path}")
        if source_file.truncated:
            warnings.append(f"{source_file.path} was truncated before review; findings may not cover the entire file.")

    if not request.has_tests:
        add_finding(
            deterministic,
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

    ai_findings = []
    llm_error = None
    ai_confidence = None
    mode = "deterministic-validated"

    if model_service.enabled and request.files:
        try:
            messages = build_source_messages(request, deterministic)
            text = model_service.generate_json(
                messages,
                SOURCE_AI_SCHEMA,
                model_service.source_new_tokens,
                "source-quality",
            )
            plan = parse_source_model_output(text)
            ai_findings = validate_source_ai_findings(plan, request, deterministic)
            ai_confidence = plan.confidence
            mode = "hybrid-ai-validated" if ai_findings else "hybrid-ai-no-additional-findings"
        except Exception as error:
            llm_error = repr(error)
            mode = "deterministic-fallback"

    findings = deduplicate_findings([*deterministic, *ai_findings])
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
        limitations.append(f"{request.omitted_files_count} discovered source file(s) were omitted by client-side review limits.")
    if request.read_error_files_count:
        limitations.append(f"{request.read_error_files_count} source file(s) could not be read by the CLI.")
    if request.truncated_files_count:
        limitations.append(f"{request.truncated_files_count} source file(s) were partially reviewed because of size limits.")

    current_required = any(bool(item.get("current_knowledge_required")) for item in findings)
    current_reason = next(
        (item.get("current_knowledge_reason") for item in findings if item.get("current_knowledge_required") and item.get("current_knowledge_reason")),
        None,
    )

    confidence = "HIGH"
    if partial:
        confidence = "MEDIUM"
    elif ai_confidence in {"HIGH", "MEDIUM", "LOW"} and ai_findings:
        confidence = ai_confidence
    elif llm_error:
        confidence = "MEDIUM" if findings else "LOW"

    result = {
        "agent_id": SOURCE_AGENT_ID,
        "display_name": SOURCE_DISPLAY_NAME,
        "agent_version": AGENT_VERSION,
        "agent": LEGACY_AGENT_NAME,
        "mode": mode,
        "model": model_service.model_name or model_service.primary_model if model_service.enabled else None,
        "status": "PARTIAL" if partial else "COMPLETED",
        "confidence": confidence,
        "summary": build_source_summary(request, findings, risk_level, release_recommendation),
        "risk_level": risk_level,
        "release_recommendation": release_recommendation,
        "reviewed_files_count": len(request.files),
        "findings_count": len(findings),
        "severity_summary": severity_summary,
        "category_summary": category_summary,
        "findings": findings,
        "warnings": list(dict.fromkeys(warnings)),
        "limitations": limitations,
        "verification": "Validate each confirmed source finding, preserve unaffected behavior, run targeted checks where available, then rerun the complete supported QA workflow.",
        "current_knowledge_required": current_required,
        "current_knowledge_reason": current_reason,
        "llm_metrics": model_service.last_generation,
        "llm_error": llm_error,
    }
    return SourceReviewResponse.model_validate(result).model_dump()


def contract_text(contract):
    return " ".join(
        clean_text(value, 800).lower()
        for value in (
            contract.title,
            contract.priority_reason,
            contract.repair_objective,
            contract.repair_strategy,
            contract.change_boundary,
            contract.protected_behavior,
            contract.verification,
            contract.done_condition,
        )
    )


def contract_is_environment_only(contract):
    text = contract_text(contract)
    explicit_no_source = any(
        phrase in text
        for phrase in (
            "do not modify application source",
            "keep application source code outside this repair",
            "environment or build-tool availability",
            "environment needed to execute",
        )
    )
    environment_signal = any(indicator in text for indicator in ENVIRONMENT_INDICATORS)
    return explicit_no_source and environment_signal


def contract_is_testing_only(contract):
    text = contract_text(contract)
    test_signal = any(indicator in text for indicator in TESTING_ONLY_INDICATORS)
    source_exclusion = any(
        phrase in text
        for phrase in (
            "do not modify application behavior",
            "keep production code unchanged",
            "preserve existing application behavior",
        )
    )
    return test_signal and source_exclusion


def repair_contracts_from_request(request):
    source = request.repair_plan or {}
    contracts = []
    for item in normalize_list(source.get("stitch_repair_contracts"))[:MAX_REPAIR_CONTRACTS]:
        if not isinstance(item, dict):
            continue
        try:
            contracts.append(RepairContractInput.model_validate(item))
        except ValidationError:
            continue
    return contracts


def source_finding_map(request):
    source = request.source_review or {}
    result = {}
    for item in normalize_list(source.get("findings")):
        if isinstance(item, dict) and item.get("id"):
            result[str(item.get("id"))] = item
    return result


def runtime_group_map(request):
    analysis = request.runtime_analysis or {}
    result = {}
    for item in normalize_list(analysis.get("root_cause_groups")):
        if isinstance(item, dict) and item.get("group_id"):
            result[str(item.get("group_id"))] = item
    return result


def known_source_files(request):
    return {item.path: item for item in request.source_files}


def contract_linked_files(contract, request):
    available = known_source_files(request)
    source_map = source_finding_map(request)
    runtime_map = runtime_group_map(request)
    linked = []

    def add(path):
        value = clean_text(path, 500)
        if value in available and value not in linked:
            linked.append(value)

    for ref in contract.finding_refs:
        source_finding = source_map.get(ref)
        if source_finding:
            add(source_finding.get("file_path"))
        runtime_group = runtime_map.get(ref)
        if runtime_group:
            for evidence in normalize_list(runtime_group.get("evidence")):
                if isinstance(evidence, dict):
                    add(evidence.get("application_file"))
    return linked


def extract_symbols(source_file):
    if source_file is None:
        return []
    content = source_file.content
    path = source_file.path.lower()
    symbols = []
    if path.endswith(".py"):
        try:
            tree = ast.parse(content)
        except SyntaxError:
            return []
        for node in tree.body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                symbols.append(node.name)
    elif path.endswith(".java"):
        for match in re.finditer(
            r"\b(?:public|protected|private)?\s*(?:static\s+)?(?:final\s+)?(?:[A-Za-z_$][A-Za-z0-9_$<>\[\], ?.]*)\s+([A-Za-z_$][A-Za-z0-9_$]*)\s*\(",
            content,
        ):
            name = match.group(1)
            if name not in symbols:
                symbols.append(name)
        class_match = re.search(r"\bclass\s+([A-Za-z_$][A-Za-z0-9_$]*)", content)
        if class_match:
            symbols.insert(0, class_match.group(1))
    return symbols[:12]


def repair_payload(request, contracts):
    source_files = []
    used = 0
    for item in request.source_files[:MAX_SOURCE_CONTEXT_FILES]:
        remaining = MAX_SOURCE_CONTEXT_CHARS - used
        if remaining <= 0:
            break
        content = item.content[:remaining]
        used += len(content)
        source_files.append(
            {
                "path": item.path,
                "truncated": item.truncated or len(content) < len(item.content),
                "symbols": extract_symbols(item),
                "content": content,
            }
        )

    return {
        "project_type": request.project_type,
        "execution": {
            "command": request.command,
            "success": request.success,
            "exit_code": request.exit_code,
            "failure_type": request.failure_type,
            "help_message": clean_text(request.help_message, 500),
        },
        "runtime_analysis": request.runtime_analysis or {},
        "source_review": {
            "status": (request.source_review or {}).get("status"),
            "risk_level": (request.source_review or {}).get("risk_level"),
            "findings": normalize_list((request.source_review or {}).get("findings"))[:40],
        },
        "contracts": [contract.model_dump() for contract in contracts],
        "source_files": source_files,
    }


def build_repair_messages(request, contracts):
    system = (
        "You are Stitch QA's Repair Assurance Intelligence Analyst. Agent 2 repair contracts are authoritative and define WHAT may be repaired. "
        "Your job is to explain HOW to implement each contract safely in the supplied Python or Java/Maven code without editing the project. "
        "Never broaden a contract boundary, override protected behavior, invent files, lines, symbols, tests, dependency versions, vulnerabilities, or runtime results. "
        "Target files must be selected only from supplied source_files. When a contract is testing-only and no test file exists, target_files may be empty and the approach must describe the tests to add without modifying production behavior. "
        "Environment-only contracts require no application code guidance and will be handled deterministically outside the model. "
        "Suggested patch text is optional. If supplied, keep it small and local; Stitch QA will mark it unvalidated and will never auto-apply it. "
        "Targeted verification must confirm the referenced repair objective; regression verification must protect unaffected behavior. "
        "Set current knowledge true only for version/vendor/dependency compatibility/deprecation/security-advisory facts that genuinely require current trusted documentation. "
        "Return one guidance item for every submitted repair contract, exactly once, and return only JSON matching the required schema."
    )
    return [
        {"role": "system", "content": system},
        {
            "role": "user",
            "content": json.dumps(repair_payload(request, contracts), ensure_ascii=False, separators=(",", ":")),
        },
    ]


def parse_repair_model_output(text):
    try:
        data = json.loads(str(text or "").strip())
    except json.JSONDecodeError as error:
        raise ValueError("The Repair Assurance model response was not valid JSON.") from error
    try:
        return ModelRepairPlan.model_validate(data)
    except ValidationError as error:
        raise ValueError(f"The Repair Assurance model response failed schema validation: {error}") from error


def grounded_current_knowledge_for_contract(contract):
    text = contract_text(contract)
    return any(indicator in text for indicator in CURRENT_KNOWLEDGE_INDICATORS)


def deterministic_repair_item(contract, request, index, reason=None):
    linked_files = contract_linked_files(contract, request)
    source_files = known_source_files(request)
    symbols = []
    for path in linked_files:
        for symbol in extract_symbols(source_files.get(path)):
            if symbol not in symbols:
                symbols.append(symbol)

    testing_only = contract_is_testing_only(contract)
    current_required = grounded_current_knowledge_for_contract(contract)

    if testing_only:
        intent = clean_text(contract.repair_objective, 220) or "Add evidence-driven automated test coverage without changing production behavior."
        approach = (
            "Add focused automated tests using the detected project conventions. Cover the application behavior represented by the repair contract and evidence-backed edge or error paths. "
            "Keep production source unchanged unless a separate validated finding requires a source repair."
        )
        target_files = []
        target_symbols = symbols
    else:
        intent = clean_text(contract.repair_objective, 220) or "Implement the repair objective within the approved boundary."
        approach = clean_text(contract.repair_strategy, 420) or "Apply the smallest evidence-backed implementation change within the approved repair boundary."
        target_files = linked_files
        target_symbols = symbols

    verification = clean_text(contract.verification, 240) or "Confirm the referenced repair objective, then run the relevant regression suite."
    return {
        "guidance_id": f"RAI-{index:03d}",
        "repair_contract_ref": contract.contract_id,
        "finding_refs": list(dict.fromkeys(contract.finding_refs)),
        "target_files": target_files,
        "target_symbols": target_symbols,
        "implementation_intent": intent,
        "code_level_approach": approach,
        "change_boundary": clean_text(contract.change_boundary, 400) or "Do not broaden the repair beyond the referenced evidence.",
        "protected_behavior": clean_text(contract.protected_behavior, 400) or "Preserve unaffected behavior represented by the existing evidence.",
        "side_effect_considerations": (
            clean_text(reason, 220)
            if reason
            else f"Respect the Agent 2 side-effect risk classification ({clean_text(contract.side_effect_risk, 40) or 'UNKNOWN'}) and avoid unrelated refactoring."
        ),
        "targeted_verification": verification,
        "regression_verification": "After targeted confirmation, run the complete available test suite or project checks and confirm no new failure is introduced.",
        "suggested_patch": None,
        "patch_validation_status": "NOT_GENERATED",
        "current_knowledge_required": current_required,
        "current_knowledge_reason": (
            "This repair contract contains version, dependency, compatibility, deprecation, vendor, JDK, plugin, or security-advisory context that should be checked against current trusted documentation."
            if current_required
            else None
        ),
        "status": "PENDING_IMPLEMENTATION",
    }


def environment_repair_item(contract, index):
    return {
        "guidance_id": f"RAI-{index:03d}",
        "repair_contract_ref": contract.contract_id,
        "finding_refs": list(dict.fromkeys(contract.finding_refs)),
        "target_files": [],
        "target_symbols": [],
        "implementation_intent": clean_text(contract.repair_objective, 220) or "Restore the execution environment required for QA.",
        "code_level_approach": "No application source change is justified by this repair contract. Resolve only the environment, build-tool, or wrapper availability problem described by Agent 2.",
        "change_boundary": clean_text(contract.change_boundary, 400) or "Environment and build-tool setup only; application source remains outside this repair.",
        "protected_behavior": clean_text(contract.protected_behavior, 400) or "Preserve application source and test behavior while restoring the execution environment.",
        "side_effect_considerations": "Treat any later compile or test failure as a separate evidence-backed finding instead of mixing it into this environment repair.",
        "targeted_verification": clean_text(contract.verification, 240) or "Confirm the validated command can start and rerun Stitch QA.",
        "regression_verification": "After the environment blocker is removed, use the resulting complete build or test run as the runtime regression evidence.",
        "suggested_patch": None,
        "patch_validation_status": "NOT_APPLICABLE",
        "current_knowledge_required": grounded_current_knowledge_for_contract(contract),
        "current_knowledge_reason": None,
        "status": "NO_CODE_CHANGE_REQUIRED",
    }


def validate_repair_plan(plan, request, contracts):
    contract_map = {contract.contract_id: contract for contract in contracts}
    seen = []
    available_files = set(known_source_files(request))
    normalized = []

    for item in plan.guidance:
        contract = contract_map.get(item.contract_ref)
        if contract is None:
            raise ValueError(f"Repair Assurance referenced unknown contract {item.contract_ref}.")
        seen.append(item.contract_ref)
        allowed_refs = set(contract.finding_refs)
        if set(item.finding_refs) != allowed_refs:
            raise ValueError(f"Repair Assurance finding coverage does not match {item.contract_ref}.")
        linked_files = contract_linked_files(contract, request)
        target_files = [path for path in item.target_files if path in available_files]
        if linked_files:
            target_files = [path for path in target_files if path in set(linked_files)] or linked_files
        if contract_is_testing_only(contract):
            target_files = []

        source_files = known_source_files(request)
        target_symbols = []
        for path in target_files:
            for symbol in extract_symbols(source_files.get(path)):
                if symbol not in target_symbols:
                    target_symbols.append(symbol)

        current_required = grounded_current_knowledge_for_contract(contract)
        patch = clean_text(item.suggested_patch, 900)
        normalized.append(
            {
                "contract": contract,
                "target_files": target_files,
                "target_symbols": target_symbols,
                "implementation_intent": clean_text(item.implementation_intent, 260),
                "code_level_approach": clean_text(item.code_level_approach, 520),
                "side_effect_considerations": clean_text(item.side_effect_considerations, 280),
                "targeted_verification": clean_text(item.targeted_verification, 300),
                "regression_verification": clean_text(item.regression_verification, 300),
                "suggested_patch": patch or None,
                "current_knowledge_required": current_required,
                "current_knowledge_reason": (
                    clean_text(item.current_knowledge_reason, 220)
                    if current_required and clean_text(item.current_knowledge_reason, 220)
                    else (
                        "Current trusted documentation is required because the repair contract contains version, dependency, compatibility, deprecation, vendor, JDK, plugin, or security-advisory context."
                        if current_required
                        else None
                    )
                ),
            }
        )

    if set(seen) != set(contract_map) or len(seen) != len(set(seen)):
        raise ValueError("Repair Assurance did not cover every submitted repair contract exactly once.")
    return normalized


def build_evidence_lineage(contract):
    return {
        "repair_contract_ref": contract.contract_id,
        "finding_refs": list(dict.fromkeys(contract.finding_refs)),
        "guidance_status": "LINKED",
    }


def repair_assurance_request(request):
    contracts = repair_contracts_from_request(request)
    if not contracts:
        result = {
            "agent_id": REPAIR_AGENT_ID,
            "display_name": REPAIR_DISPLAY_NAME,
            "agent_version": AGENT_VERSION,
            "agent": LEGACY_AGENT_NAME,
            "mode": "evidence-validated",
            "model": None,
            "status": "NOT_REQUIRED",
            "confidence": "HIGH",
            "risk_level": "NONE",
            "auto_apply": False,
            "summary": "No Stitch Repair Contract was supplied, so no code-level repair assurance is required.",
            "guidance": [],
            "suggested_patch": None,
            "verification": "No repair implementation is pending from Agent 2.",
            "current_knowledge_required": False,
            "current_knowledge_reason": None,
            "evidence_lineage": [],
            "shadow_validation_status": "NOT_RUN",
            "warnings": [],
            "limitations": ["Repair Assurance only operates on supplied Stitch Repair Contracts."],
            "llm_metrics": model_service.last_generation,
            "llm_error": None,
        }
        return RepairAssuranceResponse.model_validate(result).model_dump()

    environment_contracts = [contract for contract in contracts if contract_is_environment_only(contract)]
    code_contracts = [contract for contract in contracts if contract not in environment_contracts]
    guidance = []
    llm_error = None
    confidence = "HIGH"
    mode = "deterministic-validated"

    for index, contract in enumerate(environment_contracts, start=1):
        guidance.append(environment_repair_item(contract, index))

    model_guidance = []
    if code_contracts and model_service.enabled:
        try:
            messages = build_repair_messages(request, code_contracts)
            text = model_service.generate_json(
                messages,
                REPAIR_AI_SCHEMA,
                model_service.repair_new_tokens,
                "repair-assurance",
            )
            plan = parse_repair_model_output(text)
            model_guidance = validate_repair_plan(plan, request, code_contracts)
            confidence = plan.confidence
            mode = "ai-reasoned-validated"
        except Exception as error:
            llm_error = repr(error)
            confidence = "MEDIUM"
            mode = "deterministic-fallback"

    start_index = len(guidance) + 1
    if model_guidance:
        for offset, item in enumerate(model_guidance):
            contract = item["contract"]
            guidance.append(
                {
                    "guidance_id": f"RAI-{start_index + offset:03d}",
                    "repair_contract_ref": contract.contract_id,
                    "finding_refs": list(dict.fromkeys(contract.finding_refs)),
                    "target_files": item["target_files"],
                    "target_symbols": item["target_symbols"],
                    "implementation_intent": item["implementation_intent"] or clean_text(contract.repair_objective, 260),
                    "code_level_approach": item["code_level_approach"] or clean_text(contract.repair_strategy, 520),
                    "change_boundary": clean_text(contract.change_boundary, 400) or "Do not broaden the repair beyond the Agent 2 contract.",
                    "protected_behavior": clean_text(contract.protected_behavior, 400) or "Preserve unaffected behavior represented by existing evidence.",
                    "side_effect_considerations": item["side_effect_considerations"],
                    "targeted_verification": item["targeted_verification"] or clean_text(contract.verification, 300),
                    "regression_verification": item["regression_verification"],
                    "suggested_patch": item["suggested_patch"],
                    "patch_validation_status": "NOT_VALIDATED" if item["suggested_patch"] else "NOT_GENERATED",
                    "current_knowledge_required": item["current_knowledge_required"],
                    "current_knowledge_reason": item["current_knowledge_reason"],
                    "status": "PENDING_IMPLEMENTATION",
                }
            )
    else:
        for offset, contract in enumerate(code_contracts):
            guidance.append(
                deterministic_repair_item(
                    contract,
                    request,
                    start_index + offset,
                    "AI reasoning was unavailable or rejected, so this guidance preserves the Agent 2 contract without expanding its scope.",
                )
            )

    order = {contract.contract_id: index for index, contract in enumerate(contracts)}
    guidance.sort(key=lambda item: order.get(item["repair_contract_ref"], 999))
    for index, item in enumerate(guidance, start=1):
        item["guidance_id"] = f"RAI-{index:03d}"

    current_required = any(item.get("current_knowledge_required") for item in guidance)
    current_reason = next(
        (item.get("current_knowledge_reason") for item in guidance if item.get("current_knowledge_required") and item.get("current_knowledge_reason")),
        None,
    )
    risk = highest_risk(
        *[clean_text(contract.side_effect_risk, 40) or "UNKNOWN" for contract in contracts]
    )
    patches = [item.get("suggested_patch") for item in guidance if item.get("suggested_patch")]
    code_change_count = sum(1 for item in guidance if item.get("status") != "NO_CODE_CHANGE_REQUIRED")
    if code_change_count:
        summary = (
            f"Prepared {len(guidance)} contract-bound repair assurance item(s) for {len(contracts)} Stitch Repair Contract(s). "
            "Implementation guidance is evidence-linked, preserves Agent 2 boundaries, and does not modify the project automatically."
        )
    else:
        summary = (
            f"Reviewed {len(contracts)} Stitch Repair Contract(s); all supplied contracts are environment-only, so no application source change is justified."
        )

    result = {
        "agent_id": REPAIR_AGENT_ID,
        "display_name": REPAIR_DISPLAY_NAME,
        "agent_version": AGENT_VERSION,
        "agent": LEGACY_AGENT_NAME,
        "mode": mode,
        "model": model_service.model_name or model_service.primary_model if model_service.enabled and code_contracts else None,
        "status": "COMPLETED",
        "confidence": confidence,
        "risk_level": risk,
        "auto_apply": False,
        "summary": summary,
        "guidance": guidance,
        "suggested_patch": patches[0] if len(patches) == 1 else None,
        "verification": "Complete targeted confirmation for each repair assurance item, then run the relevant full regression workflow before considering the repair verified.",
        "current_knowledge_required": current_required,
        "current_knowledge_reason": current_reason,
        "evidence_lineage": [build_evidence_lineage(contract) for contract in contracts],
        "shadow_validation_status": "NOT_RUN",
        "warnings": (["One or more model-generated patch suggestions are unvalidated and must not be applied automatically."] if patches else []),
        "limitations": [
            "Repair Assurance provides implementation guidance but never modifies the original project automatically.",
            "Shadow Repair Validation is not executed in this service response; any generated patch remains unvalidated until an isolated verification workflow proves it.",
            "Current external facts are not fetched inside this agent; cases marked current_knowledge_required need trusted documentation before implementation.",
        ],
        "llm_metrics": model_service.last_generation,
        "llm_error": llm_error,
    }
    return RepairAssuranceResponse.model_validate(result).model_dump()


def legacy_repair_assurance(request):
    if request.failure_type in {
        "MAVEN_NOT_AVAILABLE",
        "MAVEN_WRAPPER_NOT_AVAILABLE",
        "MAVEN_WRAPPER_NOT_EXECUTABLE",
        "PYTHON_NOT_AVAILABLE",
        "PYTEST_NOT_AVAILABLE",
        "COMMAND_TIMEOUT",
    }:
        summary = "The supplied evidence describes an execution-environment blocker rather than a confirmed application-source defect. No application source change is justified."
        status = "NO_CODE_CHANGE_REQUIRED"
        risk = "LOW"
    elif request.success is True or request.exit_code == 0:
        summary = "The supplied execution context does not establish a blocking application-source repair target. Preserve the passing state and do not apply an ungrounded source change."
        status = "NOT_REQUIRED"
        risk = "LOW"
    else:
        summary = "Legacy single-context guidance is available only as a compatibility path. Use Agent 2 Stitch Repair Contracts for professional Repair Assurance guidance."
        status = "LEGACY_CONTEXT_ONLY"
        risk = "MEDIUM"
    result = {
        "agent_id": REPAIR_AGENT_ID,
        "display_name": REPAIR_DISPLAY_NAME,
        "agent_version": AGENT_VERSION,
        "agent": LEGACY_AGENT_NAME,
        "mode": "legacy-compatibility",
        "model": None,
        "status": status,
        "confidence": "MEDIUM",
        "risk_level": risk,
        "auto_apply": False,
        "summary": summary,
        "guidance": [],
        "suggested_patch": None,
        "verification": "Run the supported Stitch QA workflow with Agent 2 repair planning before applying any code change.",
        "current_knowledge_required": False,
        "current_knowledge_reason": None,
        "evidence_lineage": [],
        "shadow_validation_status": "NOT_RUN",
        "warnings": [],
        "limitations": ["This compatibility path does not replace contract-bound Repair Assurance."],
        "llm_metrics": None,
        "llm_error": None,
    }
    return RepairAssuranceResponse.model_validate(result).model_dump()


@app.get("/")
def health_check():
    status = model_service.status()
    return {
        "service": SERVICE_NAME,
        "status": "running",
        "agent_version": AGENT_VERSION,
        "model": status,
        "capabilities": [
            {
                "agent_id": SOURCE_AGENT_ID,
                "display_name": SOURCE_DISPLAY_NAME,
                "endpoint": "/review-source",
            },
            {
                "agent_id": REPAIR_AGENT_ID,
                "display_name": REPAIR_DISPLAY_NAME,
                "endpoint": "/assure-repair",
            },
        ],
        "compatibility_endpoints": ["/suggest-code-fix"],
        "supported_project_types": ["Python Project", "Java Maven Project"],
    }


@app.get("/ready")
def readiness_check():
    status = model_service.status()
    return {
        "ready": True,
        "source_quality_ready": True,
        "repair_assurance_ready": True,
        "llm_enabled": status["enabled"],
        "llm_loaded": status["loaded"],
        "llm_state": status["state"],
        "configured_model": status["configured_model"],
        "active_model": status["active_model"],
        "deterministic_fallback": True,
    }


@app.post("/review-source", response_model=SourceReviewResponse)
def review_source(request: SourceReviewRequest):
    return SourceReviewResponse.model_validate(review_source_request(request))


@app.post("/assure-repair", response_model=RepairAssuranceResponse)
def assure_repair(request: RepairAssuranceRequest):
    if request.repair_plan:
        return RepairAssuranceResponse.model_validate(repair_assurance_request(request))
    return RepairAssuranceResponse.model_validate(legacy_repair_assurance(request))


@app.post("/suggest-code-fix", response_model=RepairAssuranceResponse)
def suggest_code_fix(request: RepairAssuranceRequest):
    if request.repair_plan:
        return RepairAssuranceResponse.model_validate(repair_assurance_request(request))
    return RepairAssuranceResponse.model_validate(legacy_repair_assurance(request))
