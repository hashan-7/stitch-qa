import json
import os
import re

from pydantic import ValidationError

from schemas import ModelAnalysisPayload


FILE_LINE_PATTERN = re.compile(r"(?P<path>[A-Za-z0-9_./\\-]+\.[A-Za-z0-9]+):(?P<line>\d+)")
EXCEPTION_TOKEN_PATTERN = re.compile(r"\b[A-Z][A-Za-z0-9_]*(?:Error|Exception|Failure)\b")
COUNT_PATTERNS = {
    "passed": re.compile(r"\b(\d+)\s+passed\b", re.IGNORECASE),
    "failed": re.compile(r"\b(\d+)\s+failed\b", re.IGNORECASE),
    "skipped": re.compile(r"\b(\d+)\s+skipped\b", re.IGNORECASE),
    "errors": re.compile(r"\b(\d+)\s+errors?\b", re.IGNORECASE),
}
EXIT_CODE_PATTERN = re.compile(r"\bexit\s+code\s*[:=]?\s*(-?\d+)\b", re.IGNORECASE)
WORD_PATTERN = re.compile(r"[A-Za-z][A-Za-z0-9_]{2,}")

GLOBAL_RELEASE_CLAIMS = {
    "application is ready for deployment",
    "application is ready for release",
    "application is deployment ready",
    "system is ready for deployment",
    "system is production ready",
    "software is production ready",
    "product is production ready",
    "safe to deploy",
    "safe for deployment",
    "fully validated",
    "completely validated",
    "no defects exist",
    "all requirements are satisfied",
    "all application behavior is correct",
}

OUT_OF_SCOPE_CLAIMS = {
    "source code review",
    "source review",
    "static analysis",
    "code smell",
    "architecture is",
    "architectural quality",
    "business logic is correct",
    "security posture",
    "security vulnerability",
    "user experience is",
    "the application failed",
    "application failed",
    "the system failed",
    "system failed",
    "the product failed",
    "product failed",
}

AUTOMATIC_MODIFICATION_CLAIMS = {
    "automatically modify",
    "automatically fix",
    "auto-fix",
    "apply this patch",
    "generated patch",
}



ORIGIN_CODES = {
    "A": "APPLICATION_DEFECT",
    "E": "ENVIRONMENT",
    "D": "TEST_DISCOVERY",
    "X": "EXECUTION",
    "N": "NOT_ESTABLISHED",
}

RISK_CODES = {
    "L": "LOW",
    "M": "MEDIUM",
    "H": "HIGH",
    "C": "CRITICAL",
    "U": "UNKNOWN",
}

CONFIDENCE_CODES = {
    "H": "HIGH",
    "M": "MEDIUM",
    "L": "LOW",
}

STOP_WORDS = {
    "the", "and", "for", "with", "from", "that", "this", "into", "when",
    "was", "were", "are", "has", "have", "had", "test", "tests", "failed",
    "failure", "runtime", "expected", "actual", "error", "exception",
}


def clean_model_output(text):
    cleaned = str(text or "").strip()
    cleaned = re.sub(r"<think>.*?</think>", "", cleaned, flags=re.IGNORECASE | re.DOTALL).strip()
    cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\s*```$", "", cleaned)
    return cleaned.strip()


def extract_json_object(text):
    cleaned = clean_model_output(text)
    start = cleaned.find("{")
    if start < 0:
        raise ValueError("The model response did not contain a JSON object.")

    depth = 0
    in_string = False
    escaped = False
    for index in range(start, len(cleaned)):
        character = cleaned[index]
        if in_string:
            if escaped:
                escaped = False
            elif character == "\\":
                escaped = True
            elif character == '"':
                in_string = False
            continue
        if character == '"':
            in_string = True
        elif character == "{":
            depth += 1
        elif character == "}":
            depth -= 1
            if depth == 0:
                return cleaned[start:index + 1]

    raise ValueError("The model response contained an incomplete JSON object.")


def normalize_prose(value):
    return " ".join(str(value or "").split()).strip()


def normalize_category(value):
    text = re.sub(r"[^A-Za-z0-9]+", "_", str(value or "").strip().upper()).strip("_")
    return text or "RUNTIME_FAILURE"


def unique_prose(items):
    result = []
    seen = set()
    for item in items:
        value = normalize_prose(item)
        key = value.lower()
        if not value or key in seen:
            continue
        seen.add(key)
        result.append(value)
    return result


def all_failure_items(base_analysis):
    items = {}
    for group in base_analysis.get("root_cause_groups", []):
        for item in group.get("evidence", []):
            failure_id = item.get("failure_id") or item.get("id")
            if failure_id and failure_id not in items:
                normalized = dict(item)
                normalized["failure_id"] = failure_id
                items[failure_id] = normalized
    return items


def submitted_failure_ids(base_analysis):
    configured = int(os.getenv("LLM_MAX_FAILURES", "8"))
    limit = min(max(configured, 1), 16)
    return list(all_failure_items(base_analysis).keys())[:limit]


def collect_payload_text(payload):
    texts = [
        payload.summary,
        payload.next_verification,
    ]
    for group in payload.groups:
        texts.extend([
            group.category,
            group.root_cause,
            group.runtime_impact,
            group.required_action,
        ])
    return " ".join(normalize_prose(value) for value in texts)


def validate_duty_boundary(payload):
    combined = collect_payload_text(payload).lower()
    if any(phrase in combined for phrase in GLOBAL_RELEASE_CLAIMS):
        raise ValueError("The model response made an unsupported whole-application release claim.")
    if any(phrase in combined for phrase in OUT_OF_SCOPE_CLAIMS):
        raise ValueError("The model response exceeded the Runtime Quality Intelligence Analyst duty boundary.")
    if any(phrase in combined for phrase in AUTOMATIC_MODIFICATION_CLAIMS):
        raise ValueError("The model response proposed automatic source modification.")


def validate_locked_numeric_facts(payload, base_analysis):
    run_summary = base_analysis.get("run_summary", {})
    combined = collect_payload_text(payload)
    for key, pattern in COUNT_PATTERNS.items():
        expected = run_summary.get(key)
        if expected is None:
            continue
        for match in pattern.finditer(combined):
            if int(match.group(1)) != int(expected):
                raise ValueError("The model response contradicted a parser-validated test count.")

    expected_exit_code = run_summary.get("exit_code")
    if expected_exit_code is not None:
        for match in EXIT_CODE_PATTERN.finditer(combined):
            if int(match.group(1)) != int(expected_exit_code):
                raise ValueError("The model response contradicted the parser-validated exit code.")


def collect_allowed_references(base_analysis):
    allowed = set()
    for item in all_failure_items(base_analysis).values():
        for file_key, line_key in (("application_file", "application_line"), ("test_file", "test_line")):
            path = item.get(file_key)
            line = item.get(line_key)
            if path and line:
                normalized = str(path).replace("\\", "/")
                allowed.add((normalized, int(line)))
                allowed.add((normalized.lstrip("./"), int(line)))
    return allowed


def validate_references(payload, base_analysis):
    allowed = collect_allowed_references(base_analysis)
    for match in FILE_LINE_PATTERN.finditer(collect_payload_text(payload)):
        path = match.group("path").replace("\\", "/")
        line = int(match.group("line"))
        if (path, line) not in allowed and (path.lstrip("./"), line) not in allowed:
            raise ValueError("The model response introduced an unsupported file or line reference.")


def collect_allowed_exception_types(base_analysis):
    allowed = set()
    for item in all_failure_items(base_analysis).values():
        for key in ("exception_type", "expected", "actual"):
            for match in EXCEPTION_TOKEN_PATTERN.finditer(str(item.get(key) or "")):
                allowed.add(match.group(0))
    return allowed


def validate_exception_types(payload, base_analysis):
    allowed = collect_allowed_exception_types(base_analysis)
    if not allowed:
        return
    for match in EXCEPTION_TOKEN_PATTERN.finditer(collect_payload_text(payload)):
        if match.group(0) not in allowed:
            raise ValueError("The model response introduced an unsupported exception type.")


def evidence_tokens(item):
    values = [
        item.get("test_name"),
        item.get("exception_type"),
        item.get("exception_message"),
        item.get("expected"),
        item.get("actual"),
        item.get("application_file"),
        item.get("test_file"),
    ]
    tokens = set()
    for value in values:
        for token in WORD_PATTERN.findall(str(value or "").lower().replace("_", " ")):
            if token not in STOP_WORDS and len(token) >= 4:
                tokens.add(token)
    return tokens


def validate_group_coverage_and_grounding(payload, base_analysis):
    failure_map = all_failure_items(base_analysis)
    submitted = submitted_failure_ids(base_analysis)
    expected = set(submitted)
    seen = set()

    if not expected:
        if payload.groups:
            raise ValueError("The model response created failure groups without submitted failure evidence.")
        return

    for group in payload.groups:
        group_ids = list(group.failure_ids)
        if not group_ids:
            raise ValueError("The model response created an empty failure group.")
        local_seen = set()
        anchors = set()
        for failure_id in group_ids:
            if failure_id not in expected:
                raise ValueError("The model response referenced an unknown or unsubmitted failure ID.")
            if failure_id in local_seen or failure_id in seen:
                raise ValueError("The model response assigned a failure ID more than once.")
            local_seen.add(failure_id)
            seen.add(failure_id)
            anchors.update(evidence_tokens(failure_map[failure_id]))

        reasoning_text = " ".join([
            group.category,
            group.root_cause,
            group.runtime_impact,
            group.required_action,
        ]).lower().replace("_", " ")
        reasoning_tokens = set(WORD_PATTERN.findall(reasoning_text)) - STOP_WORDS
        if anchors and not (anchors & reasoning_tokens):
            raise ValueError("The model group reasoning was not sufficiently grounded in its referenced failure evidence.")

    if seen != expected:
        raise ValueError("The model response did not cover every submitted failure ID exactly once.")


def validate_semantic_bounds(payload, base_analysis):
    test_result = str(base_analysis.get("test_result") or "INCONCLUSIVE").upper()
    evidence_quality = str(base_analysis.get("evidence_quality") or "NONE").upper()

    if test_result == "FAIL" and payload.runtime_risk_level not in {"HIGH", "CRITICAL"}:
        raise ValueError("A confirmed failing test result cannot be downgraded below HIGH runtime risk.")
    if test_result == "PASS" and payload.runtime_risk_level not in {"LOW", "MEDIUM"}:
        raise ValueError("A passing tested result cannot be promoted to unsupported high runtime risk.")
    if test_result in {"NOT_RUN", "INCONCLUSIVE"} and payload.runtime_risk_level == "LOW":
        raise ValueError("Missing or inconclusive runtime evidence cannot be classified as LOW risk.")
    if test_result == "FAIL" and payload.failure_origin == "TEST_DISCOVERY":
        raise ValueError("Executed failing tests cannot be classified as a test-discovery failure.")

    if evidence_quality in {"NONE", "LOG_ONLY"} and payload.diagnosis_confidence == "HIGH":
        raise ValueError("High diagnosis confidence requires stronger evidence than the supplied evidence quality.")
    if evidence_quality == "PARTIAL" and payload.diagnosis_confidence == "HIGH":
        raise ValueError("Partial structured evidence cannot support HIGH diagnosis confidence.")


def normalize_payload(payload):
    payload.summary = normalize_prose(payload.summary)
    payload.next_verification = normalize_prose(payload.next_verification)
    for group in payload.groups:
        group.category = normalize_category(group.category)
        group.root_cause = normalize_prose(group.root_cause)
        group.runtime_impact = normalize_prose(group.runtime_impact)
        group.required_action = normalize_prose(group.required_action)
    return payload


def expand_failure_reference(value, base_analysis):
    submitted = submitted_failure_ids(base_analysis)

    if isinstance(value, int):
        if value < 1 or value > len(submitted):
            raise ValueError("The model response referenced an unknown evidence number.")
        return submitted[value - 1]

    text = str(value or "").strip()
    if text.isdigit():
        number = int(text)
        if number < 1 or number > len(submitted):
            raise ValueError("The model response referenced an unknown evidence number.")
        return submitted[number - 1]

    if text in submitted:
        return text

    raise ValueError("The model response referenced an unknown or unsubmitted failure ID.")


def expand_code(value, mapping, label):
    text = str(value or "").strip().upper()
    if text in mapping:
        return mapping[text]
    if text in mapping.values():
        return text
    raise ValueError(f"The model response used an unsupported {label} code.")


def normalize_wire_payload(data, base_analysis):
    if not isinstance(data, dict):
        raise ValueError("The model response must be a JSON object.")

    if "x" in data:
        return data

    groups = data.get("g", [])
    if not isinstance(groups, list):
        raise ValueError("The model response groups field must be an array.")

    overall_origin = expand_code(data.get("o"), ORIGIN_CODES, "origin")
    expanded_groups = []
    for group in groups:
        if not isinstance(group, dict):
            raise ValueError("Each model reasoning group must be a JSON object.")
        refs = group.get("f")
        if not isinstance(refs, list) or not refs:
            raise ValueError("Each model reasoning group must reference evidence numbers.")
        expanded_groups.append(
            {
                "f": [expand_failure_reference(item, base_analysis) for item in refs],
                "k": group.get("k"),
                "o": overall_origin,
                "c": group.get("c"),
                "i": group.get("i"),
                "a": group.get("a"),
            }
        )

    if expanded_groups:
        first = expanded_groups[0]
        summary_parts = [
            str(value).strip().rstrip(".")
            for value in (first.get("c"), first.get("i"))
            if str(value or "").strip()
        ]
        summary = ". ".join(summary_parts) + ("." if summary_parts else "")
        verification = str(first.get("a") or "").strip()
    else:
        summary = "Runtime evidence requires QA review."
        verification = "Rerun the validated runtime workflow."

    return {
        "s": summary,
        "o": overall_origin,
        "r": expand_code(data.get("r"), RISK_CODES, "risk"),
        "c": expand_code(data.get("q"), CONFIDENCE_CODES, "confidence"),
        "v": verification,
        "x": expanded_groups,
    }


def validate_model_output(text, base_analysis):
    raw_json = extract_json_object(text)
    try:
        data = json.loads(raw_json)
    except json.JSONDecodeError as error:
        raise ValueError(f"The model response failed JSON parsing: {error}") from error

    try:
        data = normalize_wire_payload(data, base_analysis)
        payload = ModelAnalysisPayload.model_validate(data)
    except ValidationError as error:
        raise ValueError(f"The model response failed schema validation: {error}") from error

    payload = normalize_payload(payload)
    validate_group_coverage_and_grounding(payload, base_analysis)
    validate_references(payload, base_analysis)
    validate_exception_types(payload, base_analysis)
    validate_locked_numeric_facts(payload, base_analysis)
    validate_duty_boundary(payload)
    validate_semantic_bounds(payload, base_analysis)
    return payload


def deterministic_release_advice(base_analysis):
    release_gate = str(base_analysis.get("release_gate") or "REVIEW_REQUIRED").upper()
    if release_gate == "ALLOW_RELEASE":
        return "Gate: ALLOW_RELEASE for the tested runtime scope; combine this result with the remaining QA evidence."
    if release_gate == "ALLOW_WITH_WARNINGS":
        return "Gate: ALLOW_WITH_WARNINGS for the tested runtime scope; review runtime warnings with the remaining QA evidence."
    if release_gate == "BLOCK_RELEASE":
        return "Gate: BLOCK_RELEASE until the confirmed tested-path failures are fixed and verified."
    return "Gate: REVIEW_REQUIRED until sufficient runtime evidence is available."


def evidence_for_ids(base_analysis, failure_ids):
    mapping = all_failure_items(base_analysis)
    return [dict(mapping[failure_id]) for failure_id in failure_ids if failure_id in mapping]


def group_title(category, count):
    label = normalize_category(category).replace("_", " ").title()
    return f"{label} affecting {count} test{'s' if count != 1 else ''}"


def affected_tests(evidence):
    return unique_prose(item.get("test_name") or item.get("failure_id") for item in evidence)


def fallback_groups_for_unsubmitted(base_analysis, submitted_ids):
    remaining = []
    submitted = set(submitted_ids)
    for group in base_analysis.get("root_cause_groups", []):
        copied = dict(group)
        evidence = [
            dict(item)
            for item in group.get("evidence", [])
            if (item.get("failure_id") or item.get("id")) not in submitted
        ]
        if not evidence:
            continue
        copied["evidence"] = evidence
        copied["affected_tests"] = affected_tests(evidence)
        remaining.append(copied)
    return remaining


def merge_model_output(base_analysis, payload):
    merged = dict(base_analysis)
    submitted_ids = submitted_failure_ids(base_analysis)
    groups = []

    for index, insight in enumerate(payload.groups, start=1):
        evidence = evidence_for_ids(base_analysis, insight.failure_ids)
        groups.append({
            "group_id": f"RQI-{index:03d}",
            "title": group_title(insight.category, len(evidence)),
            "category": normalize_category(insight.category),
            "failure_origin": insight.failure_origin,
            "root_cause": insight.root_cause,
            "runtime_impact": insight.runtime_impact,
            "required_action": insight.required_action,
            "affected_tests": affected_tests(evidence),
            "evidence": evidence,
        })

    remainder = fallback_groups_for_unsubmitted(base_analysis, submitted_ids)
    for group in remainder:
        group = dict(group)
        group["group_id"] = f"RQI-{len(groups) + 1:03d}"
        groups.append(group)

    if not groups:
        groups = [dict(group) for group in base_analysis.get("root_cause_groups", [])]

    merged["root_cause_groups"] = groups
    merged["failure_origin"] = payload.failure_origin
    merged["runtime_risk_level"] = payload.runtime_risk_level
    merged["diagnosis_confidence"] = payload.diagnosis_confidence
    merged["outcome_interpretation"] = payload.summary
    merged["next_verification"] = payload.next_verification
    merged["summary"] = " ".join(unique_prose([payload.summary, deterministic_release_advice(base_analysis)]))

    impacts = unique_prose(group.get("runtime_impact") for group in groups)
    merged["residual_runtime_risk"] = impacts[0] if impacts else None

    if groups:
        merged["primary_root_cause"] = groups[0].get("root_cause")
        merged["root_cause"] = groups[0].get("root_cause")
        merged["runtime_impact"] = groups[0].get("runtime_impact")

    actions = unique_prose(group.get("required_action") for group in groups)
    merged["required_actions"] = actions or base_analysis.get("required_actions", [])
    merged["recommendation"] = merged["required_actions"][0] if merged["required_actions"] else base_analysis.get("recommendation")

    verification = [payload.next_verification]
    if str(base_analysis.get("test_result") or "").upper() == "FAIL":
        verification.append("Run the complete test suite after the targeted verification and confirm the validated command exits with code 0.")
    merged["verification_steps"] = unique_prose(verification)
    merged["issues"] = unique_prose(group.get("title") for group in groups)
    return merged
