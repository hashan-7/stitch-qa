---
title: Stitch QA Defect Resolution Intelligence Analyst
emoji: 🛠️
colorFrom: purple
colorTo: blue
sdk: docker
app_port: 7860
---

# Stitch QA Defect Resolution Intelligence Analyst - Repair Agent

**Defect Resolution Intelligence Analyst** is Agent 2 in the Stitch QA workflow.  
It is also known by its original service name: **Repair Agent**.

Agent 2 converts confirmed Stitch QA findings into prioritized, evidence-linked repair contracts. It does not modify project source code. Its responsibility is to define what should be repaired, why it matters, what must stay protected, and how the repair should be verified.

---

## Role in Stitch QA

```text
Source findings + runtime findings
        ↓
Defect Resolution Intelligence Analyst - Repair Agent
        ↓
Prioritized Stitch Repair Contracts
```

Agent 2 receives validated evidence from source review and runtime analysis. It then creates repair contracts that are safe, bounded, and traceable back to the findings that justified them.

---

## Responsibilities

- Convert confirmed findings into repair contracts.
- Prioritize repairs using validated QA impact.
- Correlate related source and runtime findings when they describe the same affected behavior.
- Keep environment blockers separate from application defects.
- Define repair objectives, strategies, change boundaries, and protected behavior.
- Provide verification guidance and done conditions.
- Preserve `Auto Apply: False`.
- Avoid broad refactors or unsupported repair recommendations.

---

## Inputs

Agent 2 may receive:

- Source Quality Intelligence findings.
- Runtime Quality Intelligence root-cause groups.
- Test execution evidence.
- Failure origin and release gate.
- Project metadata.
- Evidence completeness information.

---

## Outputs

Agent 2 produces:

- Overall repair priority.
- Planning confidence.
- Repair side-effect risk.
- Stitch Repair Contracts.
- Next action.
- Verification guidance.
- Current knowledge requirement flag.
- Limitations.

---

## Repair Contract Structure

A Stitch Repair Contract typically includes:

- Contract ID.
- Linked finding references.
- Priority.
- Repair objective.
- Repair strategy.
- Change boundary.
- Protected behavior.
- Side-effect risk.
- Verification plan.
- Done condition.
- Contract status.

---

## Evidence-Linked Planning

Agent 2 must not create repair work from unsupported assumptions.

For example:

- If runtime evidence shows two failing tests caused by the same missing validation behavior, Agent 2 should group those findings into a focused repair contract.
- If Maven is unavailable, Agent 2 should recommend resolving the environment or build-tool problem, not editing application source code.
- If no tests exist in a Python source-only project, Agent 2 may recommend adding focused tests without changing production behavior solely to satisfy missing-test evidence.

---

## AI Usage

Agent 2 may use a local model reasoning layer to draft or refine repair contracts. However, every contract must remain grounded in supplied Stitch QA evidence and must pass validation.

If AI generation is unavailable, invalid, incomplete, or ungrounded, Agent 2 returns deterministic fallback repair planning.

---

## Safety Rules

- Do not automatically apply fixes.
- Do not generate unrelated refactors.
- Do not mix environment blockers with application defects.
- Do not recommend application source changes for toolchain availability problems.
- Do not invent current external facts.
- Do not expand repair scope beyond supplied evidence.
- Keep `auto_apply` false in all outputs.

---

## Typical Outcomes

| Scenario | Expected Agent 2 outcome |
| --- | --- |
| Confirmed application failures | One or more prioritized repair contracts |
| Correlated runtime and source findings | One focused contract where evidence supports correlation |
| Maven unavailable | Environment-only repair contract |
| All tests pass and no source findings exist | `NO_REPAIR_REQUIRED` |
| Unsupported project clean exit | Agent 2 is not run |

---

## Service Summary

| Field | Value |
| --- | --- |
| Agent number | Agent 2 |
| Special name | Defect Resolution Intelligence Analyst |
| Original service name | Repair Agent |
| Primary responsibility | Evidence-linked repair planning |
| Source-code modification | Not allowed |
| Main output | Stitch Repair Contracts |
| Auto Apply | Always false |
