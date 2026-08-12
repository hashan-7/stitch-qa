---
title: Stitch QA Runtime Quality Intelligence Analyst
emoji: 🤖
colorFrom: purple
colorTo: blue
sdk: docker
app_port: 7860
---

# Stitch QA Runtime Quality Intelligence Analyst - Log Agent

**Runtime Quality Intelligence Analyst** is Agent 1 in the Stitch QA workflow.  
It is also known by its original service name: **Log Agent**.

Agent 1 analyzes validated runtime and automated-test evidence produced by Stitch QA. Its role is to decide whether the tested execution path passed, failed because of an application defect, failed because of an environment blocker, or could not be evaluated from the available evidence.

This service is designed to protect verified runtime facts. AI interpretation may help summarize failing evidence, but deterministic evidence analysis remains the correctness layer.

---

## Role in Stitch QA

```text
Validated test execution
        ↓
Runtime Quality Intelligence Analyst - Log Agent
        ↓
Runtime risk, root cause groups, failure origin, release gate
```

Agent 1 receives structured runtime evidence, such as pytest or Maven Surefire results, and produces a release-focused runtime assessment.

---

## Responsibilities

- Analyze validated automated-test evidence.
- Distinguish application defects from environment or tooling blockers.
- Identify root-cause groups from runtime failures.
- Preserve structured evidence such as test counts, failure locations, exception types, and report sources.
- Produce a runtime release gate such as `ALLOW_RELEASE`, `REVIEW_REQUIRED`, or `BLOCK_RELEASE`.
- Avoid replacing verified runtime facts with unsupported model output.
- Fall back to deterministic evidence-backed analysis when AI output is unavailable or invalid.

---

## Inputs

Agent 1 may receive:

- Execution status.
- Test framework and command profile.
- Test summary.
- Structured failure records.
- JUnit XML evidence when available.
- Console output when structured evidence is incomplete.
- Environment and command-start failure details.

---

## Outputs

Agent 1 produces:

- Runtime execution status.
- Test result.
- Runtime risk level.
- Failure origin.
- Diagnosis confidence.
- Evidence quality.
- Root-cause groups.
- Required actions.
- Verification steps.
- Runtime release gate.

---

## Evidence-First Behavior

Agent 1 is intentionally conservative.

If a test command cannot start because Maven, pytest, or another required tool is unavailable, Agent 1 classifies the issue as an environment or execution blocker instead of inventing an application defect.

If tests pass, Agent 1 can return a release gate for the tested scope without requiring repair planning.

If tests fail, Agent 1 groups failures using validated runtime evidence and provides repair-focused runtime context for Agent 2.

---

## AI Usage

Agent 1 can use an optional local model interpretation layer for failing runtime evidence. Model output must match the Agent 1 JSON contract and pass validation before it can refine the deterministic result.

If model loading, generation, schema validation, or grounding validation fails, Agent 1 returns the deterministic evidence-backed analysis.

---

## Safety Rules

- Do not invent failed tests.
- Do not invent application defects when evidence shows an environment blocker.
- Do not ignore structured test evidence.
- Do not replace validated runtime facts with model speculation.
- Do not apply patches or modify project source code.
- Keep runtime analysis grounded in supplied Stitch QA evidence.

---

## Typical Outcomes

| Scenario | Expected Agent 1 outcome |
| --- | --- |
| All supported tests pass | Runtime risk `LOW`, release gate `ALLOW_RELEASE` |
| Pytest failures caused by application behavior | Failure origin `APPLICATION_DEFECT`, release gate `BLOCK_RELEASE` |
| Maven is not installed | Failure origin `ENVIRONMENT`, release gate `REVIEW_REQUIRED` |
| No compatible tests were executed | Runtime Quality Intelligence is not run |

---

## Service Summary

| Field | Value |
| --- | --- |
| Agent number | Agent 1 |
| Special name | Runtime Quality Intelligence Analyst |
| Original service name | Log Agent |
| Primary responsibility | Runtime and test-evidence analysis |
| Source-code modification | Not allowed |
| Correctness layer | Deterministic evidence analysis |
| AI role | Optional bounded interpretation layer |
