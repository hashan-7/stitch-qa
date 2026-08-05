import json
import re

from pydantic import ValidationError

from schemas import ModelAnalysisPayload


FILE_LINE_PATTERN = re.compile(r"(?P<path>[A-Za-z0-9_./\\-]+\.[A-Za-z0-9]+):(?P<line>\d+)")


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
                    allowed.add((str(file_path).replace("\\", "/"), int(line)))
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


def validate_model_output(text, base_analysis):
    raw_json = extract_json_object(text)
    try:
        payload = ModelAnalysisPayload.model_validate(json.loads(raw_json))
    except (json.JSONDecodeError, ValidationError) as error:
        raise ValueError(f"The model response failed schema validation: {error}") from error

    allowed_group_ids = {
        group.get("group_id")
        for group in base_analysis.get("root_cause_groups", [])
        if group.get("group_id")
    }
    seen_group_ids = set()

    for insight in payload.group_insights:
        if insight.group_id not in allowed_group_ids:
            raise ValueError("The model response referenced an unknown root-cause group.")
        if insight.group_id in seen_group_ids:
            raise ValueError("The model response repeated a root-cause group.")
        seen_group_ids.add(insight.group_id)

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

    if any(has_unsupported_reference(item, allowed_references) for item in texts):
        raise ValueError("The model response introduced an unsupported file or line reference.")

    return payload


def merge_model_output(base_analysis, payload):
    merged = dict(base_analysis)
    groups = [dict(group) for group in base_analysis.get("root_cause_groups", [])]
    insights = {item.group_id: item for item in payload.group_insights}

    for group in groups:
        insight = insights.get(group.get("group_id"))
        if insight is None:
            continue
        group["root_cause"] = insight.root_cause
        group["runtime_impact"] = insight.runtime_impact
        group["required_action"] = insight.required_action

    merged["root_cause_groups"] = groups
    deterministic_summary = str(base_analysis.get("summary") or "").strip()
    model_note = payload.overall_note.strip()
    merged["summary"] = (
        f"{deterministic_summary} Analyst note: {model_note}"
        if deterministic_summary
        else model_note
    )
    merged["required_actions"] = [
        group.get("required_action")
        for group in groups
        if group.get("required_action")
    ] or base_analysis.get("required_actions", [])
    merged["primary_root_cause"] = (
        groups[0].get("root_cause") if groups else base_analysis.get("primary_root_cause")
    )
    merged["root_cause"] = merged.get("primary_root_cause")
    merged["recommendation"] = (
        merged["required_actions"][0]
        if merged.get("required_actions")
        else base_analysis.get("recommendation")
    )
    return merged
