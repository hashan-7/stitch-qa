from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


RuntimeRiskLevel = Literal[
    "LOW",
    "MEDIUM",
    "HIGH",
    "CRITICAL",
    "UNKNOWN",
]

FailureOrigin = Literal[
    "APPLICATION_DEFECT",
    "ENVIRONMENT",
    "TEST_DISCOVERY",
    "EXECUTION",
    "NOT_ESTABLISHED",
]

DiagnosisConfidence = Literal[
    "HIGH",
    "MEDIUM",
    "LOW",
]


class TestRunSummary(BaseModel):
    model_config = ConfigDict(extra="ignore")

    total: int = Field(default=0, ge=0)
    passed: int = Field(default=0, ge=0)
    failed: int = Field(default=0, ge=0)
    skipped: int = Field(default=0, ge=0)
    errors: int = Field(default=0, ge=0)
    duration_seconds: float | None = Field(default=None, ge=0)


class FailureEvidence(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: str = Field(min_length=1, max_length=80)
    status: Literal["FAILED", "ERROR"] = "FAILED"
    test_name: str | None = Field(default=None, max_length=500)
    test_file: str | None = Field(default=None, max_length=1000)
    test_line: int | None = Field(default=None, ge=1)
    classname: str | None = Field(default=None, max_length=500)
    duration_seconds: float | None = Field(default=None, ge=0)
    exception_type: str | None = Field(default=None, max_length=300)
    exception_message: str | None = Field(default=None, max_length=2000)
    expected: str | None = Field(default=None, max_length=1000)
    actual: str | None = Field(default=None, max_length=1000)
    application_file: str | None = Field(default=None, max_length=1000)
    application_line: int | None = Field(default=None, ge=1)
    traceback_excerpt: str | None = Field(default=None, max_length=5000)
    raw_failure: str | None = Field(default=None, max_length=8000)


class RuntimeEvidence(BaseModel):
    model_config = ConfigDict(extra="ignore")

    schema_version: str = Field(default="1.0", max_length=20)
    framework: str | None = Field(default=None, max_length=100)
    command: str | None = Field(default=None, max_length=2000)
    execution_status: str = Field(default="UNKNOWN", max_length=100)
    test_result: str = Field(default="INCONCLUSIVE", max_length=100)
    exit_code: int | None = None
    duration_seconds: float | None = Field(default=None, ge=0)
    test_summary: TestRunSummary = Field(default_factory=TestRunSummary)
    failures: list[FailureEvidence] = Field(default_factory=list, max_length=500)
    failure_records_total: int = Field(default=0, ge=0)
    failure_records_submitted: int = Field(default=0, ge=0)
    evidence_truncated: bool = False
    warnings: list[str] = Field(default_factory=list, max_length=200)
    report_files: list[str] = Field(default_factory=list, max_length=200)
    report_source: str = Field(default="NONE", max_length=100)
    evidence_quality: str = Field(default="NONE", max_length=100)
    collection_errors: list[str] = Field(default_factory=list, max_length=100)
    failure_type: str | None = Field(default=None, max_length=200)
    help_message: str | None = Field(default=None, max_length=4000)


class LogAnalysisRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")

    project_type: str = Field(min_length=1, max_length=200)
    command: str = Field(default="", max_length=2000)
    success: bool
    exit_code: int | None = None
    stdout: str = Field(default="", max_length=30000)
    stderr: str = Field(default="", max_length=30000)
    failure_type: str | None = Field(default=None, max_length=200)
    help_message: str | None = Field(default=None, max_length=4000)
    runtime_evidence: RuntimeEvidence | None = None


class RootCauseGroup(BaseModel):
    model_config = ConfigDict(extra="ignore")

    group_id: str = Field(min_length=1, max_length=80)
    title: str = Field(min_length=1, max_length=500)
    category: str = Field(min_length=1, max_length=200)
    failure_origin: FailureOrigin = "NOT_ESTABLISHED"
    root_cause: str = Field(min_length=1, max_length=3000)
    runtime_impact: str = Field(min_length=1, max_length=3000)
    required_action: str = Field(min_length=1, max_length=3000)
    affected_tests: list[str] = Field(default_factory=list, max_length=500)
    evidence: list[dict[str, Any]] = Field(default_factory=list, max_length=500)


class ModelReasoningGroup(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    failure_ids: list[str] = Field(alias="f", min_length=1, max_length=100)
    category: str = Field(alias="k", min_length=2, max_length=80)
    failure_origin: FailureOrigin = Field(alias="o")
    root_cause: str = Field(alias="c", min_length=8, max_length=600)
    runtime_impact: str = Field(alias="i", min_length=8, max_length=500)
    required_action: str = Field(alias="a", min_length=8, max_length=500)


class ModelAnalysisPayload(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    summary: str = Field(alias="s", min_length=12, max_length=500)
    failure_origin: FailureOrigin = Field(alias="o")
    runtime_risk_level: RuntimeRiskLevel = Field(alias="r")
    diagnosis_confidence: DiagnosisConfidence = Field(alias="c")
    next_verification: str = Field(alias="v", min_length=8, max_length=400)
    groups: list[ModelReasoningGroup] = Field(alias="x", default_factory=list, max_length=20)


class LogAnalysisResponse(BaseModel):
    model_config = ConfigDict(extra="ignore")

    agent_id: str
    display_name: str
    agent_version: str
    agent: str
    mode: str
    model: str | None = None
    execution_status: str
    test_result: str
    release_gate: str
    runtime_risk_level: RuntimeRiskLevel
    failure_origin: FailureOrigin
    diagnosis_confidence: str
    final_status: str
    summary: str
    outcome_interpretation: str | None = None
    scope_assurance: str | None = None
    residual_runtime_risk: str | None = None
    next_verification: str | None = None
    run_summary: dict[str, Any]
    root_cause_groups: list[RootCauseGroup]
    primary_root_cause: str | None = None
    root_cause: str | None = None
    runtime_impact: str
    required_actions: list[str]
    recommendation: str
    verification_steps: list[str]
    issues: list[str]
    warnings: list[str]
    limitations: list[str]
    evidence_quality: str
    llm_metrics: dict[str, Any] | None = None
    llm_error: str | None = None
