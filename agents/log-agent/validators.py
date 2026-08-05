import json
import re

from pydantic import ValidationError

from schemas import ModelAnalysisPayload


FILE_LINE_PATTERN = re.compile(
    r"(?P<path>[A-Za-z0-9_./\\-]+\.[A-Za-z0-9]+):(?P<line>\d+)"
)

FAILURE_CONTRADICTIONS = {
    "all tests passed",
    "the test suite passed",
    "no tests failed",
    "no test failures",
    "safe to release",
    "ready for release",
    "release may proceed",
    "allow_release",
}

PASS_CONTRADICTIONS = {
    "all tests failed",
    "the test suite failed",
    "tests are failing",
    "block_release",
    "release must be blocked",
    "do not release",
}

INCONCLUSIVE_CONTRADICTIONS = {
    "all tests passed",
    "the test suite passed",
    "all tests failed",
    "the test suite failed",
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
                    allowed.add((normalized_path.lstrip("./"), int(line)))

    return allowed


def has_unsupported_reference(text, allowed_references):
    for match in FILE_LINE_PATTERN.finditer(text or ""):
        path = match.group("path").replace("\\", "/")
        line = int(match.group("line"))
        candidates = {
            (path, line),
            (path.lstrip("./"), line),
        }

        if not any(candidate in allowed_references for candidate in candidates):
            return True

    return False


def collect_payload_text(payload):
    items = [payload.overall_note]

    for insight in payload.group_insights:
        items.extend(
            [
                insight.root_cause,
                insight.runtime_impact,
                insight.required_action,
            ]
        )

    return " ".join(normalize_prose(item) for item in items).lower()


def contains_phrase(text, phrases):
    return any(phrase in text for phrase in phrases)


def validate_semantic_consistency(payload, base_analysis):
    combined_text = collect_payload_text(payload)
    test_result = str(base_analysis.get("test_result") or "").upper()
    release_gate = str(base_analysis.get("release_gate") or "").upper()

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
        {
            "safe to release",
            "ready for release",
            "release may proceed",
            "allow_release",
        },
    ):
        raise ValueError(
            "The model response contradicted the deterministic release gate."
        )

    if release_gate in {"ALLOW_RELEASE", "ALLOW_WITH_WARNINGS"} and contains_phrase(
        combined_text,
        {
            "block_release",
            "release must be blocked",
            "do not release",
        },
    ):
        raise ValueError(
            "The model response contradicted the deterministic release gate."
        )


def validate_model_output(text, base_analysis):
    raw_json = extract_json_object(text)

    try:
        payload = ModelAnalysisPayload.model_validate(json.loads(raw_json))
    except (json.JSONDecodeError, ValidationError) as error:
        raise ValueError(
            f"The model response failed schema validation: {error}"
        ) from error

    payload.overall_note = normalize_prose(payload.overall_note)

    if len(payload.overall_note) < 40:
        raise ValueError(
            "The model response did not provide a meaningful professional QA note."
        )

    allowed_group_ids = {
        group.get("group_id")
        for group in base_analysis.get("root_cause_groups", [])
        if group.get("group_id")
    }
    seen_group_ids = set()

    for insight in payload.group_insights:
        insight.root_cause = normalize_prose(insight.root_cause)
        insight.runtime_impact = normalize_prose(insight.runtime_impact)
        insight.required_action = normalize_prose(insight.required_action)

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

    allowed_references = collect_allowed_references(base_analysis)
    texts = [payload.overall_note]

    for insight in payload.group_insights:
        texts.extend(
            [
                insight.root_cause,
                insight.runtime_impact,
                insight.required_action,
            ]
        )

    if any(
        has_unsupported_reference(item, allowed_references)
        for item in texts
    ):
        raise ValueError(
            "The model response introduced an unsupported file or line reference."
        )

    validate_semantic_consistency(payload, base_analysis)
    return payload


def merge_model_output(base_analysis, payload):
    merged = dict(base_analysis)
    groups = [
        dict(group)
        for group in base_analysis.get("root_cause_groups", [])
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
        group["runtime_impact"] = insight.runtime_impact
        group["required_action"] = insight.required_action

    deterministic_summary = normalize_prose(
        base_analysis.get("summary")
    )
    model_note = normalize_prose(payload.overall_note)

    merged["root_cause_groups"] = groups
    merged["summary"] = (
        f"{deterministic_summary} Senior QA assessment: {model_note}"
        if deterministic_summary
        else model_note
    )

    required_actions = []

    for group in groups:
        action = normalize_prose(group.get("required_action"))

        if action and action not in required_actions:
            required_actions.append(action)

    merged["required_actions"] = (
        required_actions
        or base_analysis.get("required_actions", [])
    )

    if groups:
        merged["primary_root_cause"] = groups[0].get("root_cause")
        merged["root_cause"] = groups[0].get("root_cause")
        merged["runtime_impact"] = groups[0].get("runtime_impact")

    merged["recommendation"] = (
        merged["required_actions"][0]
        if merged.get("required_actions")
        else base_analysis.get("recommendation")
    )

    return merged