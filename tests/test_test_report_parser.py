from pathlib import Path

from stitch_cli.test_report_parser import parse_junit_reports


def test_parse_pytest_junit_failure(tmp_path):
    project_root = tmp_path / "project"
    project_root.mkdir()
    (project_root / "app.py").write_text(
        "def divide(a, b):\n    return a / b\n",
        encoding="utf-8",
    )
    (project_root / "test_app.py").write_text(
        "import pytest\nfrom app import divide\n\ndef test_divide_rejects_zero():\n    with pytest.raises(ValueError):\n        divide(10, 0)\n",
        encoding="utf-8",
    )
    report = tmp_path / "pytest-junit.xml"
    report.write_text(
        """<?xml version="1.0" encoding="utf-8"?>
<testsuites name="pytest tests">
  <testsuite name="pytest" errors="0" failures="1" skipped="0" tests="2" time="0.08">
    <testcase classname="test_app" name="test_divide_rejects_zero" time="0.01">
      <failure message="ZeroDivisionError: division by zero" type="ZeroDivisionError">test_app.py:6: in test_divide_rejects_zero
    divide(10, 0)
app.py:2: in divide
    return a / b
E   ZeroDivisionError: division by zero</failure>
    </testcase>
    <testcase classname="test_app" name="test_divide_valid" time="0.01" />
  </testsuite>
</testsuites>
""",
        encoding="utf-8",
    )

    evidence = parse_junit_reports(
        [report],
        project_root,
        "pytest",
        "python -m pytest",
        1,
        0.08,
    )

    assert evidence["test_result"] == "FAIL"
    assert evidence["test_summary"]["total"] == 2
    assert evidence["test_summary"]["passed"] == 1
    assert evidence["test_summary"]["failed"] == 1
    failure = evidence["failures"][0]
    assert failure["exception_type"] == "ZeroDivisionError"
    assert failure["expected"] == "ValueError"
    assert failure["actual"] == "ZeroDivisionError"
    assert failure["application_file"] == "app.py"
    assert failure["application_line"] == 2
    assert failure["test_file"] == "test_app.py"
    assert failure["test_line"] == 6


def test_parse_passing_junit_report(tmp_path):
    project_root = tmp_path / "project"
    project_root.mkdir()
    report = tmp_path / "pytest-junit.xml"
    report.write_text(
        """<?xml version="1.0" encoding="utf-8"?>
<testsuite name="pytest" errors="0" failures="0" skipped="1" tests="3" time="0.04">
  <testcase classname="test_app" name="test_one" time="0.01" />
  <testcase classname="test_app" name="test_two" time="0.01" />
  <testcase classname="test_app" name="test_three" time="0.01"><skipped /></testcase>
</testsuite>
""",
        encoding="utf-8",
    )

    evidence = parse_junit_reports(
        [report],
        project_root,
        "pytest",
        "python -m pytest",
        0,
        0.04,
    )

    assert evidence["test_result"] == "PASS"
    assert evidence["test_summary"] == {
        "total": 3,
        "passed": 2,
        "failed": 0,
        "skipped": 1,
        "errors": 0,
        "duration_seconds": 0.04,
    }
