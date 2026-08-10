import re
import xml.etree.ElementTree as ET
from pathlib import Path

from stitch_cli.runtime_contract import RUNTIME_EVIDENCE_SCHEMA_VERSION, empty_test_summary


PYTHON_LOCATION_PATTERN = re.compile(
    r"(?P<path>(?:[A-Za-z]:)?[^\s:\n]+\.py):(?P<line>\d+)(?::|\b)"
)
JAVA_LOCATION_PATTERN = re.compile(
    r"\((?P<file>[A-Za-z0-9_$.-]+\.java):(?P<line>\d+)\)"
)
EXCEPTION_PATTERN = re.compile(
    r"(?m)^(?:E\s+)?(?P<type>[A-Za-z_][A-Za-z0-9_.]*(?:Error|Exception|Failure)):\s*(?P<message>.+)$"
)
EXPECTED_ACTUAL_PATTERNS = [
    re.compile(
        r"expected:\s*<?(?P<expected>.*?)>?(?:\s+but was:|\s+actual:)\s*<?(?P<actual>.*?)>?$",
        re.IGNORECASE | re.MULTILINE,
    ),
    re.compile(
        r"expected\s*[=:]\s*(?P<expected>.+?)\s+(?:but\s+was|actual)\s*[=:]\s*(?P<actual>.+)",
        re.IGNORECASE,
    ),
]


def safe_relative_path(path_value, project_root):
    if not path_value:
        return None

    project_root = Path(project_root).resolve()
    raw_path = Path(str(path_value))
    candidates = []

    if raw_path.is_absolute():
        candidates.append(raw_path.resolve())
    else:
        candidates.append((project_root / raw_path).resolve())

    for candidate in candidates:
        try:
            return candidate.relative_to(project_root).as_posix()
        except ValueError:
            continue

    normalized = str(path_value).replace("\\", "/")
    if normalized.startswith("./"):
        normalized = normalized[2:]
    return normalized


def is_test_path(path_value):
    normalized = str(path_value or "").replace("\\", "/").lower()
    name = Path(normalized).name
    return (
        "/test/" in f"/{normalized}/"
        or "/tests/" in f"/{normalized}/"
        or name.startswith("test_")
        or name.endswith("_test.py")
        or name.endswith("test.java")
        or name.endswith("tests.java")
    )


def resolve_project_file(project_root, path_value):
    if not path_value:
        return None

    project_root = Path(project_root).resolve()
    candidate = Path(str(path_value))

    if candidate.is_absolute():
        resolved = candidate.resolve()
    else:
        resolved = (project_root / candidate).resolve()

    try:
        resolved.relative_to(project_root)
    except ValueError:
        return None

    return resolved if resolved.is_file() else None


def is_project_application_path(path_value, project_root):
    return (
        not is_test_path(path_value)
        and resolve_project_file(project_root, path_value) is not None
    )


def find_java_file(project_root, file_name):
    matches = list(Path(project_root).rglob(file_name))
    if not matches:
        return file_name

    test_named = file_name.lower().endswith(("test.java", "tests.java"))
    preferred = sorted(
        matches,
        key=lambda item: (
            0
            if (test_named and "src/test" in item.as_posix())
            or (not test_named and "src/main" in item.as_posix())
            else 1,
            len(item.parts),
        ),
    )[0]

    return safe_relative_path(preferred, project_root)


def extract_locations(text, project_root):
    locations = []
    seen = set()

    for match in PYTHON_LOCATION_PATTERN.finditer(text or ""):
        path = safe_relative_path(match.group("path"), project_root)
        line = int(match.group("line"))
        key = (path, line)

        if key not in seen:
            seen.add(key)
            locations.append(key)

    for match in JAVA_LOCATION_PATTERN.finditer(text or ""):
        path = find_java_file(project_root, match.group("file"))
        line = int(match.group("line"))
        key = (path, line)

        if key not in seen:
            seen.add(key)
            locations.append(key)

    return locations


def read_expected_contract(project_root, test_file, test_line):
    if not test_file:
        return None

    project_root = Path(project_root).resolve()
    file_path = (project_root / test_file).resolve()

    try:
        file_path.relative_to(project_root)
    except ValueError:
        return None

    if not file_path.is_file():
        return None

    try:
        lines = file_path.read_text(
            encoding="utf-8",
            errors="ignore",
        ).splitlines()
    except OSError:
        return None

    if not lines:
        return None

    if test_line:
        start = max(test_line - 5, 0)
        end = min(test_line + 5, len(lines))
    else:
        start = 0
        end = min(80, len(lines))

    snippet = "\n".join(lines[start:end])
    patterns = [
        re.compile(r"pytest\.raises\(\s*([A-Za-z_][A-Za-z0-9_.]*)"),
        re.compile(r"assertThrows\(\s*([A-Za-z_][A-Za-z0-9_.]*)\.class"),
        re.compile(r"with\s+self\.assertRaises\(\s*([A-Za-z_][A-Za-z0-9_.]*)"),
    ]

    for pattern in patterns:
        match = pattern.search(snippet)
        if match:
            return match.group(1).rsplit(".", 1)[-1]

    return None


def extract_expected_actual(text):
    for pattern in EXPECTED_ACTUAL_PATTERNS:
        match = pattern.search(text or "")
        if match:
            return (
                match.group("expected").strip(),
                match.group("actual").strip(),
            )

    did_not_raise = re.search(
        r"DID NOT RAISE\s+<class ['\"](?P<expected>[^'\"]+)['\"]>",
        text or "",
        re.IGNORECASE,
    )

    if did_not_raise:
        return (
            did_not_raise.group("expected").rsplit(".", 1)[-1],
            "No exception",
        )

    return None, None


def extract_exception(failure_element, text):
    exception_type = failure_element.get("type")
    message = failure_element.get("message")
    match = EXCEPTION_PATTERN.search(text or "")

    if match:
        exception_type = exception_type or match.group("type")
        message = message or match.group("message")

    if exception_type:
        exception_type = exception_type.rsplit(".", 1)[-1]

    return exception_type, message


def build_test_name(testcase):
    classname = testcase.get("classname")
    name = testcase.get("name")

    if classname and name:
        return f"{classname}::{name}"

    return name or classname or "unknown_test"


def testcase_duration(testcase):
    try:
        return (
            float(testcase.get("time"))
            if testcase.get("time") is not None
            else None
        )
    except ValueError:
        return None


def parse_failure(
    testcase,
    failure_element,
    status,
    project_root,
    failure_id,
):
    raw_text = "\n".join(
        item
        for item in (
            failure_element.get("message"),
            failure_element.text,
        )
        if item
    ).strip()

    locations = extract_locations(
        raw_text,
        project_root,
    )
    testcase_file = safe_relative_path(
        testcase.get("file"),
        project_root,
    )
    testcase_line = None

    if testcase.get("line"):
        try:
            testcase_line = int(testcase.get("line")) + 1
        except ValueError:
            testcase_line = None

    test_file = testcase_file
    test_line = testcase_line
    application_file = None
    application_line = None

    for path, line in locations:
        if is_test_path(path) and test_file is None:
            test_file = path
            test_line = line
        elif (
            application_file is None
            and is_project_application_path(
                path,
                project_root,
            )
        ):
            application_file = path
            application_line = line

    if test_file is None:
        for path, line in locations:
            if is_test_path(path):
                test_file = path
                test_line = line
                break

    exception_type, exception_message = extract_exception(
        failure_element,
        raw_text,
    )
    expected, actual = extract_expected_actual(
        raw_text
    )

    if expected is None:
        expected = read_expected_contract(
            project_root,
            test_file,
            test_line,
        )

    if actual is None and exception_type:
        actual = exception_type

    traceback_excerpt = (
        raw_text[-4000:]
        if raw_text
        else None
    )

    return {
        "id": failure_id,
        "status": status,
        "test_name": build_test_name(testcase),
        "test_file": test_file,
        "test_line": test_line,
        "classname": testcase.get("classname"),
        "duration_seconds": testcase_duration(testcase),
        "exception_type": exception_type,
        "exception_message": exception_message,
        "expected": expected,
        "actual": actual,
        "application_file": application_file,
        "application_line": application_line,
        "traceback_excerpt": traceback_excerpt,
        "raw_failure": (
            raw_text[-8000:]
            if raw_text
            else None
        ),
    }


def iter_testcases(root):
    if root.tag.endswith("testcase"):
        yield root

    for element in root.iter():
        if element is root:
            continue

        if element.tag.endswith("testcase"):
            yield element


def root_totals(root):
    values = {}

    for key in (
        "tests",
        "failures",
        "errors",
        "skipped",
    ):
        try:
            values[key] = int(
                root.get(key, 0)
            )
        except ValueError:
            values[key] = 0

    try:
        values["time"] = (
            float(root.get("time"))
            if root.get("time") is not None
            else None
        )
    except ValueError:
        values["time"] = None

    return values


def parse_junit_reports(
    report_files,
    project_root,
    framework,
    command,
    exit_code,
    duration_seconds,
    failure_type=None,
    help_message=None,
):
    summary = empty_test_summary(
        duration_seconds
    )
    failures = []
    report_names = []
    collection_errors = []
    parsed_files = 0

    for report_file in report_files:
        report_path = Path(report_file)
        report_names.append(
            report_path.name
        )

        try:
            root = ET.parse(
                report_path
            ).getroot()
        except (
            ET.ParseError,
            OSError,
        ) as error:
            collection_errors.append(
                f"{report_path.name}: {error}"
            )
            continue

        parsed_files += 1
        testcases = list(
            iter_testcases(root)
        )

        if not testcases:
            totals = root_totals(root)
            summary["total"] += totals["tests"]
            summary["failed"] += totals["failures"]
            summary["errors"] += totals["errors"]
            summary["skipped"] += totals["skipped"]
            summary["passed"] += max(
                totals["tests"]
                - totals["failures"]
                - totals["errors"]
                - totals["skipped"],
                0,
            )

            if totals["time"] is not None:
                current_duration = (
                    summary.get("duration_seconds")
                    or 0
                )
                summary["duration_seconds"] = max(
                    current_duration,
                    totals["time"],
                )

            continue

        for testcase in testcases:
            summary["total"] += 1

            failure_element = next(
                (
                    child
                    for child in testcase
                    if child.tag.endswith("failure")
                ),
                None,
            )
            error_element = next(
                (
                    child
                    for child in testcase
                    if child.tag.endswith("error")
                ),
                None,
            )
            skipped_element = next(
                (
                    child
                    for child in testcase
                    if child.tag.endswith("skipped")
                ),
                None,
            )

            if failure_element is not None:
                summary["failed"] += 1
                failures.append(
                    parse_failure(
                        testcase,
                        failure_element,
                        "FAILED",
                        project_root,
                        f"FAIL-{len(failures) + 1:04d}",
                    )
                )
            elif error_element is not None:
                summary["errors"] += 1
                failures.append(
                    parse_failure(
                        testcase,
                        error_element,
                        "ERROR",
                        project_root,
                        f"ERROR-{len(failures) + 1:04d}",
                    )
                )
            elif skipped_element is not None:
                summary["skipped"] += 1
            else:
                summary["passed"] += 1

    if summary["failed"] or summary["errors"]:
        test_result = "FAIL"
    elif (
        summary["total"] > 0
        and exit_code == 0
    ):
        test_result = "PASS"
    elif failure_type == "PYTHON_TESTS_NOT_FOUND":
        test_result = "NOT_RUN"
    elif parsed_files:
        test_result = "INCONCLUSIVE"
    else:
        test_result = "INCONCLUSIVE"

    if parsed_files:
        report_source = (
            "SUREFIRE_XML"
            if str(framework or "").strip().lower()
            == "maven-surefire"
            else "JUNIT_XML"
        )
    else:
        report_source = "NONE"

    return {
        "schema_version": RUNTIME_EVIDENCE_SCHEMA_VERSION,
        "framework": framework,
        "command": command,
        "execution_status": "COMPLETED",
        "test_result": test_result,
        "exit_code": exit_code,
        "duration_seconds": duration_seconds,
        "test_summary": summary,
        "failures": failures,
        "failure_records_total": len(failures),
        "failure_records_submitted": len(failures),
        "evidence_truncated": False,
        "warnings": [],
        "report_files": report_names,
        "report_source": report_source,
        "evidence_quality": (
            "STRUCTURED"
            if parsed_files
            and not collection_errors
            else "PARTIAL"
        ),
        "collection_errors": collection_errors,
        "failure_type": failure_type,
        "help_message": help_message,
    }


def discover_maven_report_files(
    project_root,
    started_at_epoch,
):
    project_root = Path(
        project_root
    ).resolve()

    patterns = (
        "**/target/surefire-reports/TEST-*.xml",
        "**/target/failsafe-reports/TEST-*.xml",
    )
    files = []
    threshold = max(
        0,
        started_at_epoch - 2,
    )

    for pattern in patterns:
        for path in project_root.glob(
            pattern
        ):
            try:
                if (
                    path.is_file()
                    and path.stat().st_mtime
                    >= threshold
                ):
                    files.append(path)
            except OSError:
                continue

    return sorted(
        set(files)
    )