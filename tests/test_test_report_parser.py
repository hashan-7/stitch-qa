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
        "import pytest\n"
        "from app import divide\n"
        "\n"
        "def test_divide_rejects_zero():\n"
        "    with pytest.raises(ValueError):\n"
        "        divide(10, 0)\n",
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
    assert evidence["report_source"] == "JUNIT_XML"


def test_parse_maven_surefire_prefers_project_application_frame(
    tmp_path,
):
    project_root = tmp_path / "project"

    main_dir = (
        project_root
        / "src"
        / "main"
        / "java"
        / "com"
        / "stitchqa"
        / "fixture"
    )
    test_dir = (
        project_root
        / "src"
        / "test"
        / "java"
        / "com"
        / "stitchqa"
        / "fixture"
    )

    main_dir.mkdir(parents=True)
    test_dir.mkdir(parents=True)

    (main_dir / "Calculator.java").write_text(
        """package com.stitchqa.fixture;

public final class Calculator {
    public static int divide(int a, int b) {
        return a / b;
    }
}
""",
        encoding="utf-8",
    )

    (test_dir / "CalculatorTest.java").write_text(
        """package com.stitchqa.fixture;

import org.junit.jupiter.api.Test;
import static org.junit.jupiter.api.Assertions.assertThrows;

class CalculatorTest {
    @Test
    void divide_rejects_zero() {
        assertThrows(
            IllegalArgumentException.class,
            () -> Calculator.divide(10, 0)
        );
    }
}
""",
        encoding="utf-8",
    )

    report = (
        tmp_path
        / "TEST-com.stitchqa.fixture.CalculatorTest.xml"
    )

    report.write_text(
        """<?xml version="1.0" encoding="UTF-8"?>
<testsuite name="com.stitchqa.fixture.CalculatorTest" tests="2" failures="1" errors="0" skipped="0" time="0.1">
  <testcase name="divide_rejects_zero" classname="com.stitchqa.fixture.CalculatorTest" time="0.01">
    <failure
      message="Unexpected exception type thrown, expected: &lt;java.lang.IllegalArgumentException&gt; but was: &lt;java.lang.ArithmeticException&gt;"
      type="org.opentest4j.AssertionFailedError">org.opentest4j.AssertionFailedError: Unexpected exception type thrown, expected: &lt;java.lang.IllegalArgumentException&gt; but was: &lt;java.lang.ArithmeticException&gt;
    at org.junit.jupiter.api.Assertions.assertThrows(Assertions.java:3234)
    at com.stitchqa.fixture.CalculatorTest.divide_rejects_zero(CalculatorTest.java:27)
Caused by: java.lang.ArithmeticException: / by zero
    at com.stitchqa.fixture.Calculator.divide(Calculator.java:13)
    at com.stitchqa.fixture.CalculatorTest.lambda$divide_rejects_zero$0(CalculatorTest.java:29)
    at org.junit.jupiter.api.AssertThrows.assertThrows(AssertThrows.java:54)</failure>
  </testcase>
  <testcase name="divide_returns_quotient" classname="com.stitchqa.fixture.CalculatorTest" time="0.01" />
</testsuite>
""",
        encoding="utf-8",
    )

    evidence = parse_junit_reports(
        [report],
        project_root,
        "maven-surefire",
        "mvn test",
        1,
        0.1,
    )

    assert evidence["test_result"] == "FAIL"
    assert evidence["report_source"] == "SUREFIRE_XML"
    assert evidence["test_summary"]["total"] == 2
    assert evidence["test_summary"]["passed"] == 1
    assert evidence["test_summary"]["failed"] == 1

    failure = evidence["failures"][0]

    assert failure["exception_type"] == "AssertionFailedError"
    assert (
        failure["expected"]
        == "java.lang.IllegalArgumentException"
    )
    assert (
        failure["actual"]
        == "java.lang.ArithmeticException"
    )
    assert (
        failure["application_file"]
        == "src/main/java/com/stitchqa/fixture/Calculator.java"
    )
    assert failure["application_line"] == 13
    assert (
        failure["test_file"]
        == "src/test/java/com/stitchqa/fixture/CalculatorTest.java"
    )
    assert failure["test_line"] == 27


def test_parse_maven_surefire_does_not_treat_framework_frame_as_application_source(
    tmp_path,
):
    project_root = tmp_path / "project"

    test_dir = (
        project_root
        / "src"
        / "test"
        / "java"
        / "com"
        / "stitchqa"
        / "fixture"
    )
    test_dir.mkdir(parents=True)

    (test_dir / "CalculatorTest.java").write_text(
        "class CalculatorTest {}\n",
        encoding="utf-8",
    )

    report = (
        tmp_path
        / "TEST-com.stitchqa.fixture.CalculatorTest.xml"
    )

    report.write_text(
        """<?xml version="1.0" encoding="UTF-8"?>
<testsuite name="com.stitchqa.fixture.CalculatorTest" tests="1" failures="1" errors="0" skipped="0" time="0.1">
  <testcase name="divide_rejects_zero" classname="com.stitchqa.fixture.CalculatorTest" time="0.01">
    <failure message="Assertion failed" type="org.opentest4j.AssertionFailedError">org.opentest4j.AssertionFailedError: Assertion failed
    at org.junit.jupiter.api.Assertions.assertThrows(Assertions.java:3234)
    at com.stitchqa.fixture.CalculatorTest.divide_rejects_zero(CalculatorTest.java:27)
    at org.junit.jupiter.api.AssertThrows.assertThrows(AssertThrows.java:54)</failure>
  </testcase>
</testsuite>
""",
        encoding="utf-8",
    )

    evidence = parse_junit_reports(
        [report],
        project_root,
        "maven-surefire",
        "mvn test",
        1,
        0.1,
    )

    failure = evidence["failures"][0]

    assert failure["application_file"] is None
    assert failure["application_line"] is None
    assert (
        failure["test_file"]
        == "src/test/java/com/stitchqa/fixture/CalculatorTest.java"
    )
    assert failure["test_line"] == 27