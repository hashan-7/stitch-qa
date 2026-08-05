from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


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
    root_cause: str = Field(min_length=1, max_length=3000)
    runtime_impact: str = Field(min_length=1, max_length=3000)
    required_action: str = Field(min_length=1, max_length=3000)
    affected_tests: list[str] = Field(default_factory=list, max_length=500)
    evidence: list[dict[str, Any]] = Field(default_factory=list, max_length=500)


class ModelGroupInsight(BaseModel):
    model_config = ConfigDict(extra="forbid")

    group_id: str = Field(min_length=1, max_length=80)
    root_cause: str = Field(min_length=1, max_length=2000)
    runtime_impact: str = Field(min_length=1, max_length=2000)
    required_action: str = Field(min_length=1, max_length=2000)


class ModelAnalysisPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    overall_note: str = Field(min_length=1, max_length=3000)
    group_insights: list[ModelGroupInsight] = Field(default_factory=list, max_length=100)


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
    diagnosis_confidence: str
    final_status: str
    summary: str
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
    llm_error: str | None = None
