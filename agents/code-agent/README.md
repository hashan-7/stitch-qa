---
title: Stitch QA Source Quality and Repair Assurance Intelligence Analyst
emoji: 🧠
colorFrom: purple
colorTo: blue
sdk: docker
app_port: 7860
license: mit
---

# Stitch QA Source Quality and Repair Assurance Intelligence Analyst - Code Agent

**Source Quality Intelligence Analyst** and **Repair Assurance Intelligence Analyst** are the two Agent 3 responsibilities in the Stitch QA workflow.  
Both are served under the original service name: **Code Agent**.

Agent 3 is intentionally split into two logical parts while keeping the same service identity. Part 1 reviews supported application source files for evidence-backed risks. Part 2 turns approved repair contracts into code-level implementation guidance without generating or applying unvalidated patches.

---

## Role in Stitch QA

```text
Part 1:
Project source files
        ↓
Source Quality Intelligence Analyst - Code Agent
        ↓
Source findings and source risk

Part 2:
Stitch Repair Contracts
        ↓
Repair Assurance Intelligence Analyst - Code Agent
        ↓
Target files, target symbols, change boundaries, verification guidance
```

Agent 3 supports both source-level review and repair-assurance guidance, but it does not automatically modify user projects.

---

## Agent 3 Part 1: Source Quality Intelligence Analyst

The **Source Quality Intelligence Analyst** reviews supported application source files for deterministic and bounded AI-assisted source-quality signals.

### Responsibilities

- Discover supported application source files.
- Exclude test files from application-source review.
- Detect evidence-backed source risks.
- Report findings with file paths, lines, severity, evidence, impact, and recommendations.
- Preserve current knowledge flags.
- Communicate limitations clearly when source review cannot prove full correctness.

### Typical findings

- Missing automated tests in source-only Python projects.
- Potential unguarded divisor behavior.
- Potential empty-collection divisor behavior.
- Other evidence-backed source-quality risks supported by deterministic checks and validated reasoning.

---

## Agent 3 Part 2: Repair Assurance Intelligence Analyst

The **Repair Assurance Intelligence Analyst** receives Stitch Repair Contracts from Agent 2 and converts them into bounded code-level guidance.

### Responsibilities

- Link guidance back to repair contracts.
- Identify target files and target symbols.
- Preserve Agent 2 change boundaries.
- Explain implementation intent.
- Provide targeted and regression verification guidance.
- Avoid producing unvalidated patches.
- Return `NOT_REQUIRED` when no repair contract exists.
- Return `NO_CODE_CHANGE_REQUIRED` when contracts are environment-only.

---

## Inputs

Agent 3 may receive:

- Application source files.
- Source discovery metadata.
- Stitch Repair Contracts.
- Runtime evidence summaries.
- Source review findings.
- Project profile information.

---

## Outputs

Agent 3 may produce:

- Source findings.
- Source risk level.
- Source release recommendation.
- Repair assurance guidance.
- Target files.
- Target symbols.
- Change boundaries.
- Verification plans.
- Patch validation status.
- Current knowledge requirement flag.

---

## AI Usage

Agent 3 uses deterministic validation as a safety layer and bounded local model reasoning as an optional support layer.

If model output is invalid, incomplete, ungrounded, or not contract-safe, Agent 3 falls back to deterministic validated behavior. This protects the workflow from unsafe or overbroad code recommendations.

---

## Safety Rules

- Do not automatically modify project source code.
- Do not emit an unvalidated patch as a trusted repair.
- Do not broaden Agent 2 repair boundaries.
- Do not invent unsupported source findings.
- Do not recommend code changes for environment-only contracts.
- Do not claim complete correctness from source review alone.
- Keep `auto_apply` false in repair-assurance outputs.

---

## Typical Outcomes

| Scenario | Expected Agent 3 outcome |
| --- | --- |
| Supported source files with findings | Source findings with evidence and recommendations |
| Supported source files without findings | Low source risk with limitations |
| Runtime and source findings correlated by Agent 2 | Targeted repair assurance guidance |
| Environment-only repair contract | `NO_CODE_CHANGE_REQUIRED` |
| No repair contract exists | `NOT_REQUIRED` |
| Unsupported project clean exit | Agent 3 analysis is not run |

---

## Service Summary

| Field | Value |
| --- | --- |
| Agent number | Agent 3 |
| Special names | Source Quality Intelligence Analyst; Repair Assurance Intelligence Analyst |
| Original service name | Code Agent |
| Primary responsibility | Source review and repair-assurance guidance |
| Source-code modification | Not allowed |
| Patch behavior | No unvalidated patch application |
| Auto Apply | Always false |
