import json
import re
from difflib import SequenceMatcher

from pydantic import ValidationError

from schemas import ModelAnalysisPayload


FILE_LINE_PATTERN = re.compile(
    r"(?P<path>[A-Za-z0-9_./\\-]+\.[A-Za-z0-9]+):(?P<line>\d+)"
)

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
    "release may proceed",
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
    "code quality is",
    "architecture is",
    "architectural quality",
    "business logic is correct",
    "security posture",
    "security vulnerability",
    "user experience is",
}

AUTOMATIC_MODIFICATION_CLAIMS = {
    "automatically modify",
    "automatically fix",
    "auto-fix",
    "apply this patch",
    "generated patch",
}

FAILURE_CONTRADICTIONS = {
    "all tests passed",
    "the test suite passed",
    "no tests failed",
    "no test failures",
    "runtime validation passed",
    "allow_release",
}

PASS_CONTRADICTIONS = {
    "all tests failed",
    "the test suite failed",
    "tests are failing",
    "runtime validation failed",
    "block_release",
    "release must be blocked",
    "do not release",
}

INCONCLUSIVE_CONTRADICTIONS = {
    "all tests passed",
    "the test suite passed",
    "all tests failed",
    "the test suite failed",
    "runtime validation passed",
    "runtime validation failed",
}

BLOCK_RELEASE_CONTRADICTIONS = {
    "allow_release",
    "allow_with_warnings",
    "runtime gate allows release",
    "runtime gate permits release",
}

ALLOW_RELEASE_CONTRADICTIONS = {
    "block_release",
    "runtime gate blocks release",
    "release must be blocked",
}


def clean_model_output(text):
    cleaned = str(text or "").strip()
    cleaned = re.sub(
        r"<think>.*?</think>",
        "",
        cleaned,
        flags=re.IGNORECASE | re.DOTALL,
    ).strip()
    cleaned = re.sub(
        r"^```(?:json)?\s*",
        "",
        cleaned,
        flags=re.IGNORECASE,
    )
    cleaned = re.sub(r"\s*```$", "", cleaned)
    return cleaned.strip()


def normalize_prose(value):
    return " ".join(str(value or "").split()).strip()


def extract_json_object(text):
    cleaned = clean_model_output(text)
    start = cleaned.find("{")

    if start < 0:
        raise ValueError(
            "The model response did not contain a JSON object."
        )

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

    raise ValueError(
        "The model response contained an incomplete JSON object."
    )


def prepare_payload_data(raw_json, base_analysis):
    try:
        data = json.loads(raw_json)
    except json.JSONDecodeError as error:
        raise ValueError(
            f"The model response failed JSON parsing: {error}"
        ) from error

    if not isinstance(data, dict):
        raise ValueError(
            "The model response JSON root must be an object."
        )

    data.pop("release_advice", None)

    allowed_group_ids = {
        group.get("group_id")
        for group in base_analysis.get("root_cause_groups", [])
        if group.get("group_id")
    }
    test_result = str(
        base_analysis.get("test_result") or ""
    ).upper()

    if test_result == "PASS" or not allowed_group_ids:
        data["group_insights"] = []

    return data


def collect_allowed_references(base_analysis):
    allowed = set()

    for group in base_analysis.get("root_cause_groups", []):
        for item in group.get("evidence", []):
            for file_key, line_key in (
                ("application_file", "application_line"),
                ("test_file", "test_line"),
            ):
                file_path = item.get(file_key)
                line = item.get(line_key)

                if file_path and line:
                    normalized_path = str(file_path).replace("\\", "/")
                    allowed.add((normalized_path, int(line)))
                    allowed.add(
                        (
                            normalized_path.lstrip("./"),
                            int(line),
                        )
                    )

    return allowed


def has_unsupported_reference(text, allowed_references):
    for match in FILE_LINE_PATTERN.finditer(text or ""):
        path = match.group("path").replace("\\", "/")
        line = int(match.group("line"))
        candidates = {
            (path, line),
            (path.lstrip("./"), line),
        }

        if not any(
            candidate in allowed_references
            for candidate in candidates
        ):
            return True

    return False


def assessment_texts(payload):
    texts = [
        payload.outcome_interpretation,
        payload.scope_assurance,
        payload.residual_runtime_risk,
        payload.next_verification,
    ]

    for insight in payload.group_insights:
        texts.extend(
            [
                insight.root_cause,
                insight.runtime_impact,
                insight.required_action,
            ]
        )

    return texts


def collect_payload_text(payload):
    return " ".join(
        normalize_prose(item)
        for item in assessment_texts(payload)
    ).lower()


def contains_phrase(text, phrases):
    return any(phrase in text for phrase in phrases)


def normalize_payload(payload):
    payload.outcome_interpretation = normalize_prose(
        payload.outcome_interpretation
    )
    payload.scope_assurance = normalize_prose(
        payload.scope_assurance
    )
    payload.residual_runtime_risk = normalize_prose(
        payload.residual_runtime_risk
    )
    payload.next_verification = normalize_prose(
        payload.next_verification
    )

    for insight in payload.group_insights:
        insight.root_cause = normalize_prose(
            insight.root_cause
        )
        insight.runtime_impact = normalize_prose(
            insight.runtime_impact
        )
        insight.required_action = normalize_prose(
            insight.required_action
        )

    return payload


def validate_duty_boundary(payload):
    combined_text = collect_payload_text(payload)

    if contains_phrase(combined_text, GLOBAL_RELEASE_CLAIMS):
        raise ValueError(
            "The model response made an unsupported whole-application release claim."
        )

    if contains_phrase(combined_text, OUT_OF_SCOPE_CLAIMS):
        raise ValueError(
            "The model response exceeded the Runtime Quality Intelligence Analyst duty boundary."
        )

    if contains_phrase(
        combined_text,
        AUTOMATIC_MODIFICATION_CLAIMS,
    ):
        raise ValueError(
            "The model response proposed automatic source modification."
        )


def validate_semantic_consistency(payload, base_analysis):
    combined_text = collect_payload_text(payload)
    test_result = str(
        base_analysis.get("test_result") or ""
    ).upper()
    release_gate = str(
        base_analysis.get("release_gate") or ""
    ).upper()

    if test_result == "FAIL" and contains_phrase(
        combined_text,
        FAILURE_CONTRADICTIONS,
    ):
        raise ValueError(
            "The model response contradicted the validated failing test result."
        )

    if test_result == "PASS" and contains_phrase(
        combined_text,
        PASS_CONTRADICTIONS,
    ):
        raise ValueError(
            "The model response contradicted the validated passing test result."
        )

    if test_result in {"NOT_RUN", "INCONCLUSIVE"} and contains_phrase(
        combined_text,
        INCONCLUSIVE_CONTRADICTIONS,
    ):
        raise ValueError(
            "The model response invented a conclusive test outcome."
        )

    if release_gate == "BLOCK_RELEASE" and contains_phrase(
        combined_text,
        BLOCK_RELEASE_CONTRADICTIONS,
    ):
        raise ValueError(
            "The model response contradicted the deterministic BLOCK_RELEASE gate."
        )

    if release_gate in {
        "ALLOW_RELEASE",
        "ALLOW_WITH_WARNINGS",
    } and contains_phrase(
        combined_text,
        ALLOW_RELEASE_CONTRADICTIONS,
    ):
        raise ValueError(
            "The model response contradicted the deterministic runtime release gate."
        )


def validate_group_insights(payload, base_analysis):
    test_result = str(
        base_analysis.get("test_result") or ""
    ).upper()

    if test_result == "PASS" and payload.group_insights:
        raise ValueError(
            "The model response introduced root-cause insights for a passing test result."
        )

    allowed_group_ids = {
        group.get("group_id")
        for group in base_analysis.get("root_cause_groups", [])
        if group.get("group_id")
    }
    seen_group_ids = set()

    for insight in payload.group_insights:
        if insight.group_id not in allowed_group_ids:
            raise ValueError(
                "The model response referenced an unknown root-cause group."
            )

        if insight.group_id in seen_group_ids:
            raise ValueError(
                "The model response repeated a root-cause group."
            )

        seen_group_ids.add(insight.group_id)

    if not allowed_group_ids and payload.group_insights:
        raise ValueError(
            "The model response introduced root-cause groups without supporting evidence."
        )


def validate_references(payload, base_analysis):
    allowed_references = collect_allowed_references(
        base_analysis
    )

    if any(
        has_unsupported_reference(
            item,
            allowed_references,
        )
        for item in assessment_texts(payload)
    ):
        raise ValueError(
            "The model response introduced an unsupported file or line reference."
        )


def validate_summary_duplication(payload, base_analysis):
    deterministic_summary = normalize_prose(
        base_analysis.get("summary")
    ).lower()
    model_text = collect_payload_text(payload)

    if not deterministic_summary or not model_text:
        return

    similarity = SequenceMatcher(
        None,
        deterministic_summary,
        model_text,
    ).ratio()

    if similarity >= 0.88:
        raise ValueError(
            "The model response repeated the deterministic test summary instead of interpreting it."
        )


def validate_model_output(text, base_analysis):
    raw_json = extract_json_object(text)
    data = prepare_payload_data(
        raw_json,
        base_analysis,
    )

    try:
        payload = ModelAnalysisPayload.model_validate(data)
    except ValidationError as error:
        raise ValueError(
            f"The model response failed schema validation: {error}"
        ) from error

    payload = normalize_payload(payload)

    validate_group_insights(
        payload,
        base_analysis,
    )
    validate_references(
        payload,
        base_analysis,
    )
    validate_duty_boundary(payload)
    validate_semantic_consistency(
        payload,
        base_analysis,
    )
    validate_summary_duplication(
        payload,
        base_analysis,
    )

    return payload


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


def deterministic_release_advice(base_analysis):
    release_gate = str(
        base_analysis.get("release_gate") or "REVIEW_REQUIRED"
    ).upper()
    test_result = str(
        base_analysis.get("test_result") or "INCONCLUSIVE"
    ).upper()

    if release_gate == "ALLOW_RELEASE":
        return (
            "The runtime gate is ALLOW_RELEASE for this tested runtime scope only; "
            "final project-level release judgment must consider the remaining QA evidence."
        )

    if release_gate == "ALLOW_WITH_WARNINGS":
        return (
            "The runtime gate is ALLOW_WITH_WARNINGS for this tested runtime scope only; "
            "supplied runtime warnings must be reviewed with the remaining QA evidence."
        )

    if release_gate == "BLOCK_RELEASE":
        return (
            "The runtime gate is BLOCK_RELEASE because confirmed runtime failures require resolution "
            "and verification before release consideration."
        )

    if test_result == "NOT_RUN":
        return (
            "The runtime gate is REVIEW_REQUIRED because no executed runtime test result was established."
        )

    if test_result == "INCONCLUSIVE":
        return (
            "The runtime gate is REVIEW_REQUIRED because the runtime evidence is inconclusive."
        )

    return (
        "The runtime gate is REVIEW_REQUIRED until sufficient runtime evidence is available."
    )


def render_assessment(payload, base_analysis):
    return " ".join(
        unique_prose(
            [
                payload.outcome_interpretation,
                payload.scope_assurance,
                payload.residual_runtime_risk,
                deterministic_release_advice(base_analysis),
                payload.next_verification,
            ]
        )
    )


def merge_model_output(base_analysis, payload):
    merged = dict(base_analysis)
    groups = [
        dict(group)
        for group in base_analysis.get(
            "root_cause_groups",
            [],
        )
    ]
    insights = {
        item.group_id: item
        for item in payload.group_insights
    }

    for group in groups:
        insight = insights.get(group.get("group_id"))

        if insight is None:
            continue

        group["root_cause"] = insight.root_cause
        group["runtime_impact"] = (
            insight.runtime_impact
        )
        group["required_action"] = (
            insight.required_action
        )

    merged["root_cause_groups"] = groups
    merged["summary"] = render_assessment(
        payload,
        base_analysis,
    )

    required_actions = unique_prose(
        group.get("required_action")
        for group in groups
    )

    merged["required_actions"] = (
        required_actions
        or base_analysis.get(
            "required_actions",
            [],
        )
    )

    if groups:
        merged["primary_root_cause"] = groups[0].get(
            "root_cause"
        )
        merged["root_cause"] = groups[0].get(
            "root_cause"
        )
        merged["runtime_impact"] = groups[0].get(
            "runtime_impact"
        )

    verification_steps = unique_prose(
        [
            *base_analysis.get(
                "verification_steps",
                [],
            ),
            payload.next_verification,
        ]
    )
    merged["verification_steps"] = verification_steps

    merged["recommendation"] = (
        merged["required_actions"][0]
        if merged.get("required_actions")
        else base_analysis.get("recommendation")
    )

    return merged