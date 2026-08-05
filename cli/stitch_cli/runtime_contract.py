AGENT_ID = "runtime-quality-analyst"
DISPLAY_NAME = "Runtime Quality Intelligence Analyst"
AGENT_VERSION = "2.0"
RUNTIME_EVIDENCE_SCHEMA_VERSION = "1.0"

EXECUTION_STATUSES = {
    "COMPLETED",
    "FAILED_TO_START",
    "TIMED_OUT",
    "SKIPPED",
    "UNKNOWN",
}

TEST_RESULTS = {
    "PASS",
    "FAIL",
    "NOT_RUN",
    "INCONCLUSIVE",
}

RELEASE_GATES = {
    "ALLOW_RELEASE",
    "ALLOW_WITH_WARNINGS",
    "REVIEW_REQUIRED",
    "BLOCK_RELEASE",
    "NOT_EVALUATED",
}

DIAGNOSIS_CONFIDENCE = {
    "LOW",
    "MEDIUM",
    "HIGH",
}


def normalize_choice(value, allowed, default):
    normalized = str(value or "").strip().upper()
    return normalized if normalized in allowed else default


def empty_test_summary(duration_seconds=None):
    return {
        "total": 0,
        "passed": 0,
        "failed": 0,
        "skipped": 0,
        "errors": 0,
        "duration_seconds": duration_seconds,
    }
