import gc
import json
import os
import re
import threading
import time
from typing import Any, Literal

from fastapi import FastAPI
from pydantic import BaseModel, ConfigDict, Field, ValidationError


AGENT_ID = "defect-resolution-analyst"
DISPLAY_NAME = "Defect Resolution Intelligence Analyst"
AGENT_VERSION = "2.0"
MAX_AI_FINDINGS = 4
MAX_AI_CONTRACTS = 4

PRIORITY_ORDER = {
    "NONE": 0,
    "P3": 1,
    "P2": 2,
    "P1": 3,
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

MODEL_RESPONSE_SCHEMA = {
    "type": "object",
    "properties": {
        "p": {"type": "string", "enum": ["P1", "P2", "P3"]},
        "c": {"type": "string", "enum": ["HIGH", "MEDIUM", "LOW"]},
        "k": {"type": "boolean"},
        "kr": {"type": "string", "maxLength": 180},
        "x": {
            "type": "array",
            "minItems": 1,
            "maxItems": MAX_AI_CONTRACTS,
            "items": {
                "type": "object",
                "properties": {
                    "f": {
                        "type": "array",
                        "minItems": 1,
                        "maxItems": MAX_AI_FINDINGS,
                        "uniqueItems": True,
                        "items": {
                            "type": "string",
                            "minLength": 1,
                            "maxLength": 80,
                        },
                    },
                    "p": {"type": "string", "enum": ["P1", "P2", "P3"]},
                    "w": {"type": "string", "minLength": 8, "maxLength": 160},
                    "o": {"type": "string", "minLength": 8, "maxLength": 180},
                    "s": {"type": "string", "minLength": 8, "maxLength": 220},
                    "b": {"type": "string", "minLength": 6, "maxLength": 160},
                    "q": {"type": "string", "minLength": 6, "maxLength": 160},
                    "r": {"type": "string", "enum": ["L", "M", "H"]},
                    "v": {"type": "string", "minLength": 8, "maxLength": 220},
                },
                "required": ["f", "p", "w", "o", "s", "b", "q", "r", "v"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["p", "c", "k", "kr", "x"],
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
    return max(
        normalized,
        key=lambda value: RISK_ORDER.get(value, -1),
        default="UNKNOWN",
    )


def severity_priority(severity):
    severity = normalize_risk(severity)
    if severity in {"CRITICAL", "HIGH"}:
        return "P1"
    if severity == "MEDIUM":
        return "P2"
    return "P3"


class RepairRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")

    project_type: str = Field(min_length=1, max_length=200)
    command: str = Field(default="", max_length=2000)
    success: bool
    exit_code: int | None = None
    stdout: str = Field(default="", max_length=16000)
    stderr: str = Field(default="", max_length=16000)
    failure_type: str | None = Field(default=None, max_length=200)
    help_message: str | None = Field(default=None, max_length=4000)
    runtime_evidence: dict[str, Any] | None = None
    runtime_analysis: dict[str, Any] | None = None
    source_review: dict[str, Any] | None = None


class ModelRepairContract(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    finding_refs: list[str] = Field(alias="f", min_length=1, max_length=12)
    priority: Literal["P1", "P2", "P3"] = Field(alias="p")
    priority_reason: str = Field(alias="w", min_length=8, max_length=160)
    repair_objective: str = Field(alias="o", min_length=8, max_length=180)
    repair_strategy: str = Field(alias="s", min_length=8, max_length=220)
    change_boundary: str = Field(alias="b", min_length=6, max_length=160)
    protected_behavior: str = Field(alias="q", min_length=6, max_length=160)
    side_effect_risk_code: Literal["L", "M", "H"] = Field(alias="r")
    verification: str = Field(alias="v", min_length=8, max_length=220)

    @property
    def side_effect_risk(self):
        return {"L": "LOW", "M": "MEDIUM", "H": "HIGH"}[
            self.side_effect_risk_code
        ]


class ModelRepairPlan(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    overall_priority: Literal["P1", "P2", "P3"] = Field(alias="p")
    confidence: Literal["HIGH", "MEDIUM", "LOW"] = Field(alias="c")
    current_knowledge_required: bool = Field(alias="k")
    current_knowledge_reason: str = Field(alias="kr", default="", max_length=180)
    contracts: list[ModelRepairContract] = Field(
        alias="x",
        min_length=1,
        max_length=MAX_AI_CONTRACTS,
    )


class StitchRepairContract(BaseModel):
    model_config = ConfigDict(extra="ignore")

    contract_id: str
    finding_refs: list[str]
    title: str
    priority: Literal["P1", "P2", "P3"]
    priority_reason: str
    repair_objective: str
    repair_strategy: str
    change_boundary: str
    protected_behavior: str
    side_effect_risk: Literal["LOW", "MEDIUM", "HIGH"]
    verification: str
    done_condition: str
    status: Literal["PENDING_VERIFICATION"] = "PENDING_VERIFICATION"


class RepairResponse(BaseModel):
    model_config = ConfigDict(extra="ignore")

    agent_id: str
    display_name: str
    agent_version: str
    agent: str
    mode: str
    model: str | None = None
    status: str
    overall_priority: str
    confidence: str
    repair_risk_level: str
    auto_apply: bool = False
    summary: str
    stitch_repair_contracts: list[StitchRepairContract] = Field(default_factory=list)
    current_knowledge_required: bool = False
    current_knowledge_reason: str | None = None
    next_action: str | None = None
    suggestions: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)
    llm_metrics: dict[str, Any] | None = None
    llm_error: str | None = None


class ModelService:
    def __init__(self):
        self.model_repo = os.getenv(
            "HF_MODEL_REPO",
            "ibm-granite/granite-4.0-1b-GGUF",
        ).strip()
        self.model_file = os.getenv(
            "HF_MODEL_FILE",
            "granite-4.0-1b-Q4_K_M.gguf",
        ).strip()
        self.model_revision = os.getenv(
            "HF_MODEL_REVISION",
            "b27c2fe3f211b7f44e80fa620177aea371099aaa",
        ).strip()
        self.quantization = os.getenv(
            "MODEL_QUANTIZATION",
            "Q4_K_M",
        ).strip()
        self.primary_model = os.getenv(
            "HF_MODEL",
            f"{self.model_repo}:{self.quantization}",
        ).strip()
        self.cache_dir = os.getenv(
            "MODEL_CACHE_DIR",
            "/opt/huggingface/hub",
        ).strip()
        self.enabled = env_bool("LLM_ENABLED", True)
        self.local_files_only = env_bool("HF_LOCAL_FILES_ONLY", False)
        self.context_tokens = max(1024, int(os.getenv("MODEL_CONTEXT_TOKENS", "4096")))
        self.batch_tokens = max(
            64,
            min(
                self.context_tokens,
                int(os.getenv("MODEL_BATCH_TOKENS", "512")),
            ),
        )
        self.max_input_tokens = max(
            512,
            int(os.getenv("MODEL_MAX_INPUT_TOKENS", "2800")),
        )
        self.max_new_tokens = max(
            96,
            int(os.getenv("MODEL_MAX_NEW_TOKENS", "256")),
        )
        self.max_generation_seconds = max(
            15.0,
            float(os.getenv("MODEL_MAX_GENERATION_SECONDS", "90")),
        )
        self.threads = max(1, int(os.getenv("MODEL_THREADS", "2")))
        self.threads_batch = max(
            1,
            int(os.getenv("MODEL_THREADS_BATCH", str(self.threads))),
        )
        self.temperature = max(
            0.0,
            float(os.getenv("MODEL_TEMPERATURE", "0.1")),
        )
        self.top_p = min(
            1.0,
            max(0.01, float(os.getenv("MODEL_TOP_P", "0.9"))),
        )
        self.seed = int(os.getenv("MODEL_SEED", "17"))
        self.use_mmap = env_bool("MODEL_USE_MMAP", True)
        self.prompt_cache_mb = max(
            0,
            int(os.getenv("MODEL_PROMPT_CACHE_MB", "256")),
        )
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
            raise RuntimeError(
                "huggingface_hub is required for the configured Granite GGUF backend."
            ) from error

        return hf_hub_download(
            repo_id=self.model_repo,
            filename=self.model_file,
            revision=self.model_revision,
            cache_dir=self.cache_dir,
            local_files_only=self.local_files_only,
        )

    def _load_model(self):
        try:
            from llama_cpp import Llama, LlamaRAMCache
        except ImportError as error:
            raise RuntimeError(
                "llama-cpp-python is required for the configured Granite GGUF backend."
            ) from error

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

        if self.prompt_cache_mb > 0:
            model.set_cache(
                LlamaRAMCache(
                    capacity_bytes=self.prompt_cache_mb * 1024 * 1024
                )
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

    def _count_message_tokens(self, model, messages):
        serialized = json.dumps(
            messages,
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode("utf-8")

        try:
            tokens = model.tokenize(serialized, add_bos=False, special=True)
        except TypeError:
            tokens = model.tokenize(serialized, add_bos=False)

        return len(tokens)

    def _count_text_tokens(self, model, text):
        if not text:
            return 0
        value = str(text).encode("utf-8")
        try:
            tokens = model.tokenize(value, add_bos=False, special=True)
        except TypeError:
            tokens = model.tokenize(value, add_bos=False)
        return len(tokens)

    def _json_complete(self, text):
        candidate = str(text or "").strip()
        if not candidate.startswith("{") or not candidate.endswith("}"):
            return False
        try:
            json.loads(candidate)
            return True
        except json.JSONDecodeError:
            return False

    def generate(self, messages):
        self.last_generation = None
        model = self.load()

        with self.generation_lock:
            input_tokens = self._count_message_tokens(model, messages)
            if input_tokens > self.max_input_tokens:
                raise RuntimeError(
                    f"Model input contains approximately {input_tokens} tokens, exceeding the configured limit of {self.max_input_tokens}."
                )

            started = time.monotonic()
            parts = []
            finish_reason = None
            timed_out = False
            first_content_seconds = None
            stream = model.create_chat_completion(
                messages=messages,
                response_format={
                    "type": "json_object",
                    "schema": MODEL_RESPONSE_SCHEMA,
                },
                max_tokens=self.max_new_tokens,
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
                "max_new_tokens": self.max_new_tokens,
            }

            if timed_out:
                raise RuntimeError(
                    "The configured Granite model exceeded the generation time limit "
                    f"(generated_tokens={completion_tokens}, elapsed_seconds={elapsed:.3f}, tokens_per_second={tokens_per_second:.3f})."
                )

            if not text:
                raise RuntimeError("The configured Granite model returned an empty response.")

            try:
                json.loads(text)
            except json.JSONDecodeError as error:
                raise RuntimeError(
                    "The configured Granite JSON-constrained generation returned invalid JSON."
                ) from error

            if finish_reason == "length":
                raise RuntimeError(
                    "The configured Granite model reached the output token limit before completing the repair plan."
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
            "max_new_tokens": self.max_new_tokens,
            "max_generation_seconds": self.max_generation_seconds,
            "threads": self.threads,
            "prompt_cache_mb": self.prompt_cache_mb,
            "last_generation": self.last_generation,
        }


model_service = ModelService()

app = FastAPI(
    title="Stitch QA Defect Resolution Intelligence Analyst",
    version=AGENT_VERSION,
)


def runtime_findings(request):
    analysis = request.runtime_analysis or {}
    result = []

    for index, group in enumerate(
        normalize_list(analysis.get("root_cause_groups")),
        start=1,
    ):
        if not isinstance(group, dict):
            continue

        ref = clean_text(group.get("group_id"), 80) or f"RQI-{index:03d}"
        evidence = []
        locations = []

        for item in normalize_list(group.get("evidence"))[:8]:
            if not isinstance(item, dict):
                continue
            evidence.append(
                {
                    key: item.get(key)
                    for key in (
                        "failure_id",
                        "test_name",
                        "expected",
                        "actual",
                        "exception_type",
                        "exception_message",
                        "application_file",
                        "application_line",
                        "test_file",
                        "test_line",
                    )
                    if item.get(key) not in {None, ""}
                }
            )
            file_path = item.get("application_file") or item.get("test_file")
            line = item.get("application_line") or item.get("test_line")
            if file_path:
                locations.append(
                    f"{file_path}:{line}" if line else str(file_path)
                )

        result.append(
            {
                "ref": ref,
                "source": "runtime",
                "severity": normalize_risk(
                    analysis.get("runtime_risk_level") or "HIGH"
                ),
                "title": clean_text(group.get("title"), 180)
                or "Runtime failure group",
                "category": clean_text(group.get("category"), 120),
                "root_cause": clean_text(group.get("root_cause"), 700),
                "impact": clean_text(group.get("runtime_impact"), 500),
                "recommendation": clean_text(group.get("required_action"), 500),
                "locations": list(dict.fromkeys(locations))[:8],
                "evidence": evidence,
            }
        )

    if result:
        return result

    runtime_evidence = request.runtime_evidence or {}
    test_result = str(runtime_evidence.get("test_result") or "").upper()

    for index, failure in enumerate(
        normalize_list(runtime_evidence.get("failures")),
        start=1,
    ):
        if not isinstance(failure, dict):
            continue

        ref = clean_text(failure.get("id"), 80) or f"RTE-{index:03d}"
        application_file = failure.get("application_file")
        application_line = failure.get("application_line")
        test_file = failure.get("test_file")
        test_line = failure.get("test_line")
        locations = []

        if application_file:
            locations.append(
                f"{application_file}:{application_line}"
                if application_line
                else str(application_file)
            )
        if test_file:
            locations.append(
                f"{test_file}:{test_line}"
                if test_line
                else str(test_file)
            )

        expected = clean_text(failure.get("expected"), 180)
        actual = clean_text(
            failure.get("actual") or failure.get("exception_type"),
            180,
        )
        exception_message = clean_text(failure.get("exception_message"), 300)
        observed = exception_message or actual or "The tested path failed."
        contract_text = (
            f" Expected {expected}; observed {actual}."
            if expected and actual
            else ""
        )

        result.append(
            {
                "ref": ref,
                "source": "runtime",
                "severity": "HIGH" if test_result == "FAIL" else "MEDIUM",
                "title": clean_text(
                    failure.get("test_name") or failure.get("exception_type"),
                    180,
                ) or "Validated runtime failure",
                "category": "VALIDATED_RUNTIME_FAILURE",
                "root_cause": clean_text(
                    f"Observed failure evidence: {observed}.{contract_text}",
                    700,
                ),
                "impact": (
                    "A validated automated-test path did not complete with its expected behavior."
                ),
                "recommendation": (
                    "Resolve the evidence-backed behavior mismatch using the smallest safe change, then rerun the affected and regression tests."
                ),
                "locations": list(dict.fromkeys(locations)),
                "evidence": [
                    {
                        key: failure.get(key)
                        for key in (
                            "id",
                            "test_name",
                            "expected",
                            "actual",
                            "exception_type",
                            "exception_message",
                            "application_file",
                            "application_line",
                            "test_file",
                            "test_line",
                        )
                        if failure.get(key) not in {None, ""}
                    }
                ],
            }
        )

    return result


def runtime_warning_findings(request):
    analysis = request.runtime_analysis or {}
    runtime_evidence = request.runtime_evidence or {}
    warnings = []
    seen = set()

    for item in [
        *normalize_list(analysis.get("warnings")),
        *normalize_list(runtime_evidence.get("warnings")),
    ]:
        warning = clean_text(item, 500)
        key = warning.lower()
        if not warning or key in seen:
            continue
        seen.add(key)
        warnings.append(warning)

    release_gate = str(analysis.get("release_gate") or "").upper()
    severity = "MEDIUM" if release_gate == "ALLOW_WITH_WARNINGS" else "LOW"

    return [
        {
            "ref": f"RWI-{index:03d}",
            "source": "runtime",
            "severity": severity,
            "title": "Runtime warning requiring follow-up",
            "category": "RUNTIME_WARNING",
            "root_cause": warning,
            "impact": (
                "The validated run completed, but the warning may affect future compatibility, reliability, or execution behavior if its underlying condition changes."
            ),
            "recommendation": (
                "Review the warning-specific configuration or dependency behavior, verify current vendor guidance when needed, and rerun the relevant workflow after any targeted adjustment."
            ),
            "locations": [],
            "evidence": [],
        }
        for index, warning in enumerate(warnings, start=1)
    ]


def source_findings(request):
    source_review = request.source_review or {}
    result = []

    for index, finding in enumerate(
        normalize_list(source_review.get("findings")),
        start=1,
    ):
        if not isinstance(finding, dict):
            continue

        ref = clean_text(finding.get("id"), 80) or f"SRC-{index:03d}"
        file_path = finding.get("file_path")
        line = finding.get("line")
        location = None
        if file_path:
            location = f"{file_path}:{line}" if line else str(file_path)

        result.append(
            {
                "ref": ref,
                "source": "source",
                "severity": normalize_risk(finding.get("severity")),
                "title": clean_text(finding.get("title"), 180)
                or "Source-code finding",
                "category": clean_text(finding.get("category"), 120),
                "root_cause": clean_text(
                    finding.get("evidence") or finding.get("description"),
                    700,
                ),
                "impact": clean_text(finding.get("impact"), 500),
                "recommendation": clean_text(
                    finding.get("recommendation"),
                    500,
                ),
                "locations": [location] if location else [],
                "evidence": [],
            }
        )

    return result


def execution_finding(request):
    if request.success:
        return None

    analysis = request.runtime_analysis or {}
    if normalize_list(analysis.get("root_cause_groups")):
        return None

    runtime_evidence = request.runtime_evidence or {}
    if normalize_list(runtime_evidence.get("failures")):
        return None

    failure_type = clean_text(request.failure_type, 120)
    help_message = clean_text(request.help_message, 500)
    discovery_only_failures = {
        "PYTHON_TESTS_NOT_FOUND",
    }

    if failure_type.upper() in discovery_only_failures:
        return None

    if "no test files" in help_message.lower() or "no pytest-compatible test" in help_message.lower():
        return None

    if not failure_type and not help_message:
        return None

    return {
        "ref": "EXEC-001",
        "source": "execution",
        "severity": "MEDIUM",
        "title": (
            failure_type.replace("_", " ").title()
            if failure_type
            else "Execution blocker"
        ),
        "category": "EXECUTION_BLOCKER",
        "root_cause": help_message or "Execution did not produce a validated repairable runtime result.",
        "impact": "The intended QA workflow cannot establish complete runtime assurance until this blocker is resolved.",
        "recommendation": "Resolve the execution blocker and rerun Stitch QA before making application-code repair decisions.",
        "locations": [],
        "evidence": [],
    }


def collect_locked_findings(request):
    findings = []
    findings.extend(runtime_findings(request))
    findings.extend(runtime_warning_findings(request))
    findings.extend(source_findings(request))
    execution = execution_finding(request)
    if execution:
        findings.append(execution)

    seen = set()
    normalized = []
    for finding in findings:
        ref = finding["ref"]
        if ref in seen:
            continue
        seen.add(ref)
        normalized.append(finding)

    return normalized


def select_ai_findings(findings):
    source_order = {
        "execution": 0,
        "runtime": 1,
        "source": 2,
    }

    ordered = sorted(
        findings,
        key=lambda finding: (
            -RISK_ORDER.get(normalize_risk(finding.get("severity")), -1),
            source_order.get(str(finding.get("source") or ""), 3),
            str(finding.get("ref") or ""),
        ),
    )
    return ordered[:MAX_AI_FINDINGS], ordered[MAX_AI_FINDINGS:]


def overall_priority_floor(request, findings):
    analysis = request.runtime_analysis or {}
    release_gate = str(analysis.get("release_gate") or "").upper()

    if release_gate == "BLOCK_RELEASE":
        return "P1"

    runtime_evidence = request.runtime_evidence or {}
    if str(runtime_evidence.get("test_result") or "").upper() == "FAIL":
        return "P1"

    if any(
        finding.get("source") == "execution"
        for finding in findings
    ):
        return "P1"

    if any(
        normalize_risk(finding.get("severity")) == "CRITICAL"
        for finding in findings
    ):
        return "P1"

    return "P3"


def contract_priority_floor(request, contract, findings):
    refs = set(contract.finding_refs)
    selected = [finding for finding in findings if finding.get("ref") in refs]

    if any(finding.get("source") == "execution" for finding in selected):
        return "P1"

    runtime_evidence = request.runtime_evidence or {}
    if (
        str(runtime_evidence.get("test_result") or "").upper() == "FAIL"
        and any(finding.get("source") == "runtime" for finding in selected)
    ):
        return "P1"

    if any(
        finding.get("source") == "source"
        and normalize_risk(finding.get("severity")) == "CRITICAL"
        for finding in selected
    ):
        return "P1"

    return "P3"


def deterministic_confidence(request, findings):
    analysis = request.runtime_analysis or {}
    runtime_confidence = str(
        analysis.get("diagnosis_confidence") or ""
    ).upper()

    if runtime_confidence in {"HIGH", "MEDIUM", "LOW"}:
        return runtime_confidence

    source_review = request.source_review or {}
    source_confidences = {
        str(item.get("confidence") or "").upper()
        for item in normalize_list(source_review.get("findings"))
        if isinstance(item, dict)
    }

    if source_confidences == {"HIGH"}:
        return "HIGH"

    return "MEDIUM" if findings else "HIGH"


def fallback_contract(finding, index, request):
    priority = severity_priority(finding.get("severity"))

    if finding.get("source") == "execution":
        priority = "P1"

    objective = (
        finding.get("recommendation")
        or f"Resolve the confirmed condition represented by {finding['ref']}."
    )
    strategy = (
        finding.get("recommendation")
        or "Apply the smallest targeted change that resolves the confirmed condition without broad unrelated changes."
    )

    runtime_analysis = request.runtime_analysis or {}
    verification_steps = normalize_list(
        runtime_analysis.get("verification_steps")
    )
    verification = (
        " ".join(clean_text(item, 180) for item in verification_steps[:3])
        if verification_steps
        else "Confirm the affected behavior first, then run the relevant regression suite and verify no new failures."
    )

    return {
        "contract_id": f"STITCH-RC-{index:03d}",
        "finding_refs": [finding["ref"]],
        "title": clean_text(finding.get("title"), 140),
        "priority": priority,
        "priority_reason": (
            f"{finding['ref']} is prioritized from its validated impact and current QA blocking effect."
        ),
        "repair_objective": clean_text(objective, 260),
        "repair_strategy": clean_text(strategy, 320),
        "change_boundary": (
            "Limit the change to the component, input boundary, dependency, or configuration directly represented by this finding."
        ),
        "protected_behavior": (
            "Preserve behavior already shown to work outside the affected scope and avoid unrelated refactoring."
        ),
        "side_effect_risk": (
            "MEDIUM"
            if normalize_risk(finding.get("severity")) in {"CRITICAL", "HIGH", "MEDIUM"}
            else "LOW"
        ),
        "verification": clean_text(verification, 300),
        "done_condition": (
            f"{finding['ref']} is no longer reproducible and the relevant regression checks complete without new failures."
        ),
        "status": "PENDING_VERIFICATION",
    }


def finding_may_need_current_knowledge(finding):
    text = " ".join(
        clean_text(finding.get(key), 500).lower()
        for key in (
            "title",
            "category",
            "root_cause",
            "impact",
            "recommendation",
        )
    )
    indicators = (
        "dependency",
        "version",
        "deprecated",
        "deprecation",
        "compatibility",
        "plugin",
        "jdk",
        "cve",
        "security advisory",
        "vendor",
        "repository",
    )
    return any(indicator in text for indicator in indicators)


def build_fallback_plan(request, findings, mode="deterministic-fallback", llm_error=None):
    if not findings:
        return {
            "agent_id": AGENT_ID,
            "display_name": DISPLAY_NAME,
            "agent_version": AGENT_VERSION,
            "agent": "repair-agent",
            "mode": "evidence-validated",
            "model": None,
            "status": (
                "NO_REPAIR_REQUIRED"
                if request.success
                else "NO_CONFIRMED_REPAIR_TARGET"
            ),
            "overall_priority": "NONE",
            "confidence": "HIGH",
            "repair_risk_level": "NONE",
            "auto_apply": False,
            "summary": (
                "No confirmed repair target was supplied by runtime or source-review evidence."
                if request.success
                else "Execution did not succeed, but no evidence-grounded repair target was available; no source change should be guessed."
            ),
            "stitch_repair_contracts": [],
            "current_knowledge_required": False,
            "current_knowledge_reason": None,
            "next_action": (
                "Retain the available QA evidence and continue the normal release workflow."
                if request.success
                else "Obtain a confirmed runtime, execution, or source-review finding before planning a code repair."
            ),
            "suggestions": [],
            "warnings": [],
            "limitations": [
                "Agent 2 only plans repairs for findings supplied by validated Stitch QA evidence."
            ],
            "llm_metrics": model_service.last_generation,
            "llm_error": llm_error,
        }

    contracts = [
        fallback_contract(finding, index, request)
        for index, finding in enumerate(findings, start=1)
    ]
    contracts = sort_and_renumber_contracts(contracts)
    highest_priority = max(
        (contract["priority"] for contract in contracts),
        key=lambda item: PRIORITY_ORDER[item],
        default="P3",
    )
    floor = overall_priority_floor(request, findings)
    if PRIORITY_ORDER[highest_priority] < PRIORITY_ORDER[floor]:
        highest_priority = floor

    repair_risk = highest_risk(
        *(contract["side_effect_risk"] for contract in contracts)
    )

    warnings = []

    return {
        "agent_id": AGENT_ID,
        "display_name": DISPLAY_NAME,
        "agent_version": AGENT_VERSION,
        "agent": "repair-agent",
        "mode": mode,
        "model": model_service.model_name or model_service.primary_model,
        "status": "COMPLETED",
        "overall_priority": highest_priority,
        "confidence": deterministic_confidence(request, findings),
        "repair_risk_level": repair_risk,
        "auto_apply": False,
        "summary": (
            f"Prepared {len(contracts)} evidence-linked repair contract"
            f"{'s' if len(contracts) != 1 else ''} from {len(findings)} confirmed finding"
            f"{'s' if len(findings) != 1 else ''}."
        ),
        "stitch_repair_contracts": contracts,
        "current_knowledge_required": any(
            finding_may_need_current_knowledge(finding)
            for finding in findings
        ),
        "current_knowledge_reason": (
            "One or more repair targets depend on version, dependency, compatibility, vendor, deprecation, or security information that should be verified against current trusted documentation."
            if any(
                finding_may_need_current_knowledge(finding)
                for finding in findings
            )
            else None
        ),
        "next_action": (
            f"Start with {contracts[0]['contract_id']} and verify its done condition before broadening the repair scope."
        ),
        "suggestions": [
            contract["repair_strategy"]
            for contract in contracts
        ],
        "warnings": warnings,
        "limitations": [
            "This repair plan is grounded in supplied Stitch QA findings and does not automatically modify project code.",
            "Deterministic fallback prioritization is conservative and may be less context-sensitive than validated AI planning.",
        ],
        "llm_metrics": model_service.last_generation,
        "llm_error": llm_error,
    }


def compact_model_evidence(items):
    compacted = []
    for item in normalize_list(items)[:2]:
        if not isinstance(item, dict):
            continue
        compacted.append(
            {
                "id": clean_text(item.get("failure_id") or item.get("id"), 60),
                "test": clean_text(item.get("test_name"), 160),
                "expected": clean_text(item.get("expected"), 120),
                "actual": clean_text(item.get("actual"), 120),
                "exception": clean_text(item.get("exception_type"), 100),
                "message": clean_text(item.get("exception_message"), 220),
                "application": clean_text(item.get("application_file"), 200),
                "application_line": item.get("application_line"),
                "test_file": clean_text(item.get("test_file"), 200),
                "test_line": item.get("test_line"),
            }
        )
    return [
        {key: value for key, value in item.items() if value not in {None, ""}}
        for item in compacted
    ]


def model_input_findings(findings):
    payload = []

    for finding in findings[:MAX_AI_FINDINGS]:
        payload.append(
            {
                "ref": finding["ref"],
                "source": finding["source"],
                "severity": finding["severity"],
                "title": clean_text(finding.get("title"), 100),
                "category": clean_text(finding.get("category"), 70),
                "cause": clean_text(finding.get("root_cause"), 240),
                "impact": clean_text(finding.get("impact"), 180),
                "existing_action": clean_text(finding.get("recommendation"), 180),
                "locations": [
                    clean_text(location, 160)
                    for location in finding.get("locations", [])[:4]
                ],
                "evidence": compact_model_evidence(finding.get("evidence", [])),
            }
        )

    return payload


def build_messages(request, findings):
    analysis = request.runtime_analysis or {}
    source_review = request.source_review or {}

    system_prompt = (
        "You are Stitch QA's Defect Resolution Intelligence Analyst. "
        "Your job is to transform locked QA findings into the safest prioritized repair plan without editing code. "
        "The supplied finding references, severities, files, lines, test facts, release gate, and observed evidence are authoritative. "
        "Never invent findings, files, lines, test outcomes, dependency versions, vulnerabilities, or current external facts. "
        "Prioritize by impact, blocking effect, dependency order, repair scope, and regression risk; severity and repair priority are related but not identical. "
        "Group findings only when one repair objective genuinely resolves them together. "
        "For every repair contract define the smallest useful change boundary, behavior that must remain working, side-effect risk, confirmation verification, regression verification, and a measurable done condition. "
        "Repair strategy must describe the repair action and must never be only a file or line location. "
        "Change boundary must describe the permitted scope, not merely repeat locations. "
        "Protected behavior must name working behavior that should remain unchanged and must never be None, N/A, or an impact statement. "
        "Verification must include both targeted confirmation of the referenced finding and broader regression verification. "
        "Side-effect risk means risk introduced by implementing the repair, not the severity of the original defect; narrow local validation changes are normally LOW or MEDIUM unless the evidence shows broader coupling. "
        "Do not generate patches, code, commits, commands that modify the project, or automatic fixes. "
        "If a version, vendor behavior, dependency compatibility, deprecation, or security advisory needs up-to-date external documentation, set current_knowledge_required=true and explain why; do not invent the missing current fact. "
        "Return only JSON matching the required schema. "
        "Compact keys are fixed: p=overall priority, c=confidence, k=current-knowledge-needed, kr=current-knowledge reason, x=repair contracts; "
        "inside each contract f=finding refs, p=priority, w=priority reason, o=repair objective, s=repair strategy, b=change boundary, q=protected behavior, r=side-effect risk (L/M/H), v=verification. "
        "Keep every text value concise because the final professional report is formatted by Stitch QA."
    )

    payload = {
        "project": {
            "type": request.project_type,
            "command": request.command,
            "success": request.success,
            "exit_code": request.exit_code,
            "failure_type": request.failure_type,
        },
        "runtime_gate": {
            "test_result": analysis.get("test_result"),
            "release_gate": analysis.get("release_gate"),
            "runtime_risk": analysis.get("runtime_risk_level"),
            "confidence": analysis.get("diagnosis_confidence"),
            "evidence_quality": analysis.get("evidence_quality"),
        },
        "source_review": {
            "status": source_review.get("status"),
            "risk_level": source_review.get("risk_level"),
            "findings_count": len(
                normalize_list(source_review.get("findings"))
            ),
        },
        "locked_findings": model_input_findings(findings),
        "instructions": {
            "all_findings_must_be_covered": True,
            "contract_order_is_repair_order": True,
            "auto_apply": False,
        },
    }

    return [
        {
            "role": "system",
            "content": system_prompt,
        },
        {
            "role": "user",
            "content": json.dumps(
                payload,
                ensure_ascii=False,
                separators=(",", ":"),
            ),
        },
    ]


FILE_LINE_PATTERN = re.compile(
    r"(?P<path>[A-Za-z0-9_./\\-]+\.[A-Za-z0-9]+):(?P<line>\d+)"
)

AUTO_APPLY_PATTERNS = {
    "i modified",
    "i changed",
    "i updated",
    "automatically modified",
    "automatically fixed",
    "auto-fix applied",
    "committed the",
    "pushed the",
}


def parse_model_output(text):
    try:
        data = json.loads(str(text or "").strip())
    except json.JSONDecodeError as error:
        raise ValueError("The Granite response was not valid JSON.") from error

    try:
        return ModelRepairPlan.model_validate(data)
    except ValidationError as error:
        raise ValueError(
            f"The Granite response failed the repair-plan schema: {error}"
        ) from error


def allowed_references(findings):
    allowed = set()

    for finding in findings:
        for location in finding.get("locations", []):
            match = FILE_LINE_PATTERN.search(str(location))
            if not match:
                continue
            path = match.group("path").replace("\\", "/")
            line = int(match.group("line"))
            allowed.add((path, line))
            allowed.add((path.lstrip("./"), line))

    return allowed


def text_fields(plan):
    values = [plan.current_knowledge_reason]
    for contract in plan.contracts:
        values.extend(
            [
                contract.priority_reason,
                contract.repair_objective,
                contract.repair_strategy,
                contract.change_boundary,
                contract.protected_behavior,
                contract.verification,
            ]
        )
    return values


PLACEHOLDER_VALUES = {
    "none",
    "n/a",
    "na",
    "not applicable",
    "not available",
    "unknown",
    "null",
}

REPAIR_ACTION_TERMS = (
    "add ",
    "validate",
    "guard",
    "handle",
    "replace",
    "update",
    "configure",
    "remove",
    "restore",
    "return",
    "raise",
    "prevent",
    "resolve",
    "correct",
    "limit",
)

PROTECTION_TERMS = (
    "preserve",
    "keep",
    "maintain",
    "unchanged",
    "working",
    "valid",
    "passing",
)

REGRESSION_TERMS = (
    "regression",
    "full test",
    "complete test",
    "entire test",
    "no new failure",
    "all tests",
)

CONFIRMATION_TERMS = (
    "rerun",
    "re-run",
    "confirm",
    "verify",
    "expected",
    "affected test",
    "failing test",
)

BROAD_REPAIR_INDICATORS = (
    "dependency",
    "plugin",
    "configuration",
    "architecture",
    "migration",
    "security",
    "database",
    "schema",
    "api contract",
    "public api",
    "cross-service",
    "multiple modules",
)


def is_placeholder_text(value):
    normalized = clean_text(value, 400).lower().strip(" .:-")
    if not normalized:
        return True
    if normalized in PLACEHOLDER_VALUES:
        return True
    return any(
        normalized.startswith(f"{item}:")
        for item in PLACEHOLDER_VALUES
    )


def strip_file_line_references(value):
    text = FILE_LINE_PATTERN.sub(" ", clean_text(value, 600))
    text = re.sub(r"[\s,;:/|()\[\]{}-]+", " ", text)
    return text.strip()


def is_location_only_text(value):
    original = clean_text(value, 600)
    if not original:
        return True
    if not FILE_LINE_PATTERN.search(original):
        return False
    remainder = strip_file_line_references(original)
    return len(remainder.split()) <= 3


def selected_findings_for_contract(contract, findings):
    refs = set(contract.finding_refs)
    return [
        finding
        for finding in findings
        if finding.get("ref") in refs
    ]


def selected_locations(findings):
    locations = []
    for finding in findings:
        for location in finding.get("locations", []):
            value = clean_text(location, 180)
            if value and value not in locations:
                locations.append(value)
    return locations


def selected_test_evidence(findings):
    evidence = []
    seen = set()
    for finding in findings:
        for item in normalize_list(finding.get("evidence")):
            if not isinstance(item, dict):
                continue
            test_name = clean_text(item.get("test_name"), 180)
            expected = clean_text(item.get("expected"), 120)
            actual = clean_text(
                item.get("actual") or item.get("exception_type"),
                120,
            )
            key = (test_name, expected, actual)
            if key in seen:
                continue
            seen.add(key)
            evidence.append(
                {
                    "test_name": test_name,
                    "expected": expected,
                    "actual": actual,
                }
            )
    return evidence


def build_grounded_repair_objective(selected):
    evidence = selected_test_evidence(selected)
    expected_values = list(
        dict.fromkeys(
            item["expected"]
            for item in evidence
            if item.get("expected")
        )
    )

    if expected_values:
        return clean_text(
            f"Restore the expected {', '.join(expected_values[:3])} behavior for the referenced failing paths while preserving valid behavior outside them.",
            260,
        )

    recommendations = [
        clean_text(finding.get("recommendation"), 220)
        for finding in selected
        if clean_text(finding.get("recommendation"), 220)
    ]
    if recommendations:
        return clean_text(recommendations[0], 260)

    return (
        "Resolve the referenced evidence-backed condition without changing unrelated behavior."
    )


def build_grounded_repair_strategy(selected):
    evidence = selected_test_evidence(selected)
    locations = selected_locations(selected)
    expected_values = list(
        dict.fromkeys(
            item["expected"]
            for item in evidence
            if item.get("expected")
        )
    )
    actual_values = list(
        dict.fromkeys(
            item["actual"]
            for item in evidence
            if item.get("actual")
        )
    )

    if evidence and expected_values:
        expected_text = ", ".join(expected_values[:3])
        actual_text = ", ".join(actual_values[:3]) or "the observed failure"
        location_text = (
            f" at {', '.join(locations[:4])}"
            if locations
            else " in the affected runtime path"
        )
        return clean_text(
            f"Add targeted validation or controlled error handling{location_text} so the affected paths produce the expected {expected_text} behavior instead of {actual_text}; avoid unrelated implementation changes.",
            320,
        )

    recommendations = [
        clean_text(finding.get("recommendation"), 220)
        for finding in selected
        if clean_text(finding.get("recommendation"), 220)
    ]
    if recommendations:
        return clean_text(
            f"Apply the smallest targeted change needed to satisfy this evidence: {recommendations[0]}",
            320,
        )

    return (
        "Apply the smallest targeted change that resolves the referenced finding while avoiding unrelated refactoring or behavior changes."
    )


def build_grounded_change_boundary(selected):
    locations = selected_locations(selected)
    if locations:
        return clean_text(
            f"Limit changes to the behavior represented by {', '.join(locations[:4])}; do not broaden the repair into unrelated files or refactoring.",
            240,
        )
    return (
        "Limit changes to the component, configuration, or input boundary directly represented by the referenced finding; avoid unrelated changes."
    )


def build_grounded_protected_behavior(selected, request):
    runtime_evidence = request.runtime_evidence or {}
    test_summary = runtime_evidence.get("test_summary") or {}
    passed = int(test_summary.get("passed") or 0)

    if passed > 0:
        return clean_text(
            f"Preserve the {passed} currently passing tests and all valid-input behavior outside the referenced failure paths.",
            240,
        )

    if any(finding.get("source") == "runtime" for finding in selected):
        return (
            "Preserve currently successful runtime behavior outside the referenced failure paths and keep valid inputs unchanged."
        )

    return (
        "Preserve behavior outside the referenced source finding and avoid unrelated functional or structural changes."
    )


def build_grounded_verification(selected, request):
    evidence = selected_test_evidence(selected)
    test_names = list(
        dict.fromkeys(
            item["test_name"]
            for item in evidence
            if item.get("test_name")
        )
    )
    expected_values = list(
        dict.fromkeys(
            item["expected"]
            for item in evidence
            if item.get("expected")
        )
    )

    if test_names:
        targeted = ", ".join(test_names[:4])
        expected_text = (
            f" and confirm the expected {', '.join(expected_values[:3])} behavior"
            if expected_values
            else " and confirm the referenced failures no longer reproduce"
        )
        return clean_text(
            f"Rerun {targeted}{expected_text}; then run the complete test suite and confirm exit code 0 with no new failures.",
            300,
        )

    runtime_analysis = request.runtime_analysis or {}
    verification_steps = [
        clean_text(item, 160)
        for item in normalize_list(runtime_analysis.get("verification_steps"))
        if clean_text(item, 160)
    ]
    if verification_steps:
        base = " ".join(verification_steps[:3])
        if not any(term in base.lower() for term in REGRESSION_TERMS):
            base += " Then run the relevant regression suite and confirm no new failures."
        return clean_text(base, 300)

    return (
        "Confirm the referenced finding is resolved with a targeted check, then run all available regression tests or project checks and verify no new failure is introduced."
    )


def is_narrow_repair(selected, boundary):
    categories = " ".join(
        clean_text(finding.get("category"), 100).lower()
        for finding in selected
    )
    combined = f"{categories} {clean_text(boundary, 240).lower()}"
    if any(indicator in combined for indicator in BROAD_REPAIR_INDICATORS):
        return False

    files = set()
    for location in selected_locations(selected):
        match = FILE_LINE_PATTERN.search(location)
        if match:
            files.add(match.group("path").replace("\\", "/"))

    return len(files) <= 1


def normalize_contract_semantics(contract, request, findings):
    selected = selected_findings_for_contract(contract, findings)

    objective = clean_text(contract.repair_objective, 260)
    expected_values = [
        item["expected"]
        for item in selected_test_evidence(selected)
        if item.get("expected")
    ]
    if (
        is_placeholder_text(objective)
        or (
            expected_values
            and not any(
                expected.lower() in objective.lower()
                for expected in expected_values
            )
        )
    ):
        objective = build_grounded_repair_objective(selected)

    strategy = clean_text(contract.repair_strategy, 320)
    if (
        is_placeholder_text(strategy)
        or is_location_only_text(strategy)
        or not any(term in strategy.lower() for term in REPAIR_ACTION_TERMS)
    ):
        strategy = build_grounded_repair_strategy(selected)

    boundary = clean_text(contract.change_boundary, 240)
    if is_placeholder_text(boundary) or is_location_only_text(boundary):
        boundary = build_grounded_change_boundary(selected)

    protected = clean_text(contract.protected_behavior, 240)
    if (
        is_placeholder_text(protected)
        or not any(term in protected.lower() for term in PROTECTION_TERMS)
    ):
        protected = build_grounded_protected_behavior(selected, request)

    verification = clean_text(contract.verification, 300)
    lowered_verification = verification.lower()
    has_confirmation = any(
        term in lowered_verification
        for term in CONFIRMATION_TERMS
    )
    has_regression = any(
        term in lowered_verification
        for term in REGRESSION_TERMS
    )
    if (
        is_placeholder_text(verification)
        or not has_confirmation
        or not has_regression
    ):
        verification = build_grounded_verification(selected, request)

    repair_risk = contract.side_effect_risk
    if repair_risk == "HIGH" and is_narrow_repair(selected, boundary):
        repair_risk = "MEDIUM"

    return {
        "repair_objective": objective,
        "repair_strategy": strategy,
        "change_boundary": boundary,
        "protected_behavior": protected,
        "side_effect_risk": repair_risk,
        "verification": verification,
    }


def validate_plan(plan, request, findings):
    finding_refs = {finding["ref"] for finding in findings}
    used_refs = []
    combined_text = " ".join(text_fields(plan)).lower()

    for pattern in AUTO_APPLY_PATTERNS:
        if pattern in combined_text:
            raise ValueError(
                "The Granite repair plan claimed or proposed automatic project modification."
            )

    for contract in plan.contracts:
        for ref in contract.finding_refs:
            if ref not in finding_refs:
                raise ValueError(
                    f"The Granite repair plan referenced unknown finding {ref}."
                )
            used_refs.append(ref)

    missing_refs = finding_refs - set(used_refs)
    if missing_refs:
        raise ValueError(
            "The Granite repair plan omitted confirmed findings: "
            + ", ".join(sorted(missing_refs))
        )

    duplicates = {
        ref
        for ref in used_refs
        if used_refs.count(ref) > 1
    }
    if duplicates:
        raise ValueError(
            "The Granite repair plan assigned findings to multiple repair contracts: "
            + ", ".join(sorted(duplicates))
        )

    for contract in plan.contracts:
        floor = contract_priority_floor(request, contract, findings)
        if PRIORITY_ORDER[contract.priority] < PRIORITY_ORDER[floor]:
            contract.priority = floor

    allowed = allowed_references(findings)
    for value in text_fields(plan):
        for match in FILE_LINE_PATTERN.finditer(value or ""):
            path = match.group("path").replace("\\", "/")
            line = int(match.group("line"))
            if (path, line) not in allowed and (path.lstrip("./"), line) not in allowed:
                raise ValueError(
                    "The Granite repair plan introduced an unsupported file or line reference."
                )

    floor = overall_priority_floor(request, findings)
    if PRIORITY_ORDER[plan.overall_priority] < PRIORITY_ORDER[floor]:
        plan.overall_priority = floor

    highest_contract_priority = max(
        (contract.priority for contract in plan.contracts),
        key=lambda item: PRIORITY_ORDER[item],
    )
    if PRIORITY_ORDER[plan.overall_priority] < PRIORITY_ORDER[highest_contract_priority]:
        plan.overall_priority = highest_contract_priority

    grounded_current_knowledge = any(
        finding_may_need_current_knowledge(finding)
        for finding in findings
    )
    plan.current_knowledge_required = grounded_current_knowledge
    if not grounded_current_knowledge:
        plan.current_knowledge_reason = ""

    return plan


def sort_and_renumber_contracts(contracts):
    ordered = sorted(
        contracts,
        key=lambda contract: -PRIORITY_ORDER.get(contract.get("priority", "P3"), 1),
    )
    for index, contract in enumerate(ordered, start=1):
        contract["contract_id"] = f"STITCH-RC-{index:03d}"
    return ordered


def merge_model_plan(plan, request, findings, overflow_findings=None):
    overflow_findings = list(overflow_findings or [])
    contracts = []

    for index, item in enumerate(plan.contracts, start=1):
        semantic = normalize_contract_semantics(
            item,
            request,
            findings,
        )
        contracts.append(
            {
                "contract_id": f"STITCH-RC-{index:03d}",
                "finding_refs": item.finding_refs,
                "title": clean_text(
                    f"Repair contract for {', '.join(item.finding_refs)}",
                    140,
                ),
                "priority": item.priority,
                "priority_reason": clean_text(item.priority_reason, 220),
                "repair_objective": semantic["repair_objective"],
                "repair_strategy": semantic["repair_strategy"],
                "change_boundary": semantic["change_boundary"],
                "protected_behavior": semantic["protected_behavior"],
                "side_effect_risk": semantic["side_effect_risk"],
                "verification": semantic["verification"],
                "done_condition": (
                    "The referenced findings no longer reproduce, the targeted confirmation succeeds, and the stated regression verification introduces no new failure."
                ),
                "status": "PENDING_VERIFICATION",
            }
        )

    next_index = len(contracts) + 1
    for offset, finding in enumerate(overflow_findings):
        contract = fallback_contract(finding, next_index + offset, request)
        contracts.append(contract)

    contracts = sort_and_renumber_contracts(contracts)

    repair_risk = highest_risk(
        *(contract["side_effect_risk"] for contract in contracts)
    )

    overall_priority = plan.overall_priority
    if overflow_findings:
        overflow_priority = max(
            (severity_priority(item.get("severity")) for item in overflow_findings),
            key=lambda item: PRIORITY_ORDER[item],
            default="P3",
        )
        if PRIORITY_ORDER[overall_priority] < PRIORITY_ORDER[overflow_priority]:
            overall_priority = overflow_priority

    limitations = [
        "Agent 2 plans repairs from supplied Stitch QA evidence and does not automatically modify source code.",
        "Current external facts are not fetched inside this agent; cases marked current_knowledge_required need trusted documentation before implementation.",
    ]
    warnings = []

    if overflow_findings:
        warnings.append(
            f"{len(overflow_findings)} lower-priority finding(s) exceeded the AI reasoning window and were retained as conservative evidence-grounded repair contracts rather than being dropped."
        )
        limitations.append(
            "Overflow repair contracts use conservative deterministic planning because the AI reasoning window is intentionally bounded for CPU reliability."
        )

    summary_strategy = (
        clean_text(contracts[0]["repair_strategy"], 300).rstrip(" .")
        if contracts
        else "the highest-priority validated repair target"
    )

    return {
        "agent_id": AGENT_ID,
        "display_name": DISPLAY_NAME,
        "agent_version": AGENT_VERSION,
        "agent": "repair-agent",
        "mode": "ai-reasoned-validated",
        "model": model_service.model_name or model_service.primary_model,
        "status": "COMPLETED",
        "overall_priority": overall_priority,
        "confidence": plan.confidence,
        "repair_risk_level": repair_risk,
        "auto_apply": False,
        "summary": clean_text(
            f"Prepared {len(contracts)} prioritized evidence-linked repair contract"
            f"{'s' if len(contracts) != 1 else ''}; start with {summary_strategy}.",
            360,
        ),
        "stitch_repair_contracts": contracts,
        "current_knowledge_required": (
            plan.current_knowledge_required
            or any(
                finding_may_need_current_knowledge(finding)
                for finding in [*findings, *overflow_findings]
            )
        ),
        "current_knowledge_reason": (
            clean_text(plan.current_knowledge_reason, 240)
            if plan.current_knowledge_required and clean_text(plan.current_knowledge_reason, 240)
            else (
                "One or more repair targets depend on current version, dependency, compatibility, vendor, deprecation, or security documentation that must be verified before implementation."
                if any(
                    finding_may_need_current_knowledge(finding)
                    for finding in [*findings, *overflow_findings]
                )
                else None
            )
        ),
        "next_action": (
            f"Start with {contracts[0]['contract_id']}: {contracts[0]['repair_strategy']}"
            if contracts
            else None
        ),
        "suggestions": [
            contract["repair_strategy"]
            for contract in contracts
        ],
        "warnings": warnings,
        "limitations": limitations,
        "llm_metrics": model_service.last_generation,
        "llm_error": None,
    }

def should_use_llm(findings):
    return (
        model_service.enabled
        and bool(findings)
        and any(
            finding.get("source") in {"runtime", "source"}
            for finding in findings
        )
    )


@app.get("/")
def health_check():
    status = model_service.status()
    return {
        "service": "stitch-qa-repair-agent",
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
        "analysis_ready": True,
        "agent_id": AGENT_ID,
        "llm_enabled": status["enabled"],
        "llm_loaded": status["loaded"],
        "llm_state": status["state"],
        "configured_model": status["configured_model"],
        "active_model": status["active_model"],
        "deterministic_fallback": True,
    }


@app.post("/suggest", response_model=RepairResponse)
def suggest_repair(request: RepairRequest):
    findings = collect_locked_findings(request)

    if not findings:
        return RepairResponse.model_validate(
            build_fallback_plan(request, findings)
        )

    if not should_use_llm(findings):
        return RepairResponse.model_validate(
            build_fallback_plan(
                request,
                findings,
                mode="deterministic-validated",
            )
        )

    ai_findings, overflow_findings = select_ai_findings(findings)

    try:
        messages = build_messages(request, ai_findings)
        text = model_service.generate(messages)
        plan = parse_model_output(text)
        plan = validate_plan(plan, request, ai_findings)
        result = merge_model_plan(
            plan,
            request,
            ai_findings,
            overflow_findings,
        )
    except Exception as error:
        result = build_fallback_plan(
            request,
            findings,
            mode="deterministic-fallback",
            llm_error=repr(error),
        )

    return RepairResponse.model_validate(result)
