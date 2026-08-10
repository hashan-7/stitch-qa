---
title: Stitch QA Runtime Quality Intelligence Analyst
emoji: 🤖
colorFrom: purple
colorTo: blue
sdk: docker
app_port: 7860
---

# Stitch QA Runtime Quality Intelligence Analyst

Agent 1 analyzes validated runtime and automated-test evidence for Stitch QA.

The service uses deterministic evidence analysis as the correctness layer and Qwen3-1.7B GGUF through llama.cpp as an optional interpretation layer for failing runtime evidence. Model output is constrained to the Agent 1 JSON contract and validated before it can refine the deterministic result.

The default Hugging Face deployment uses the official `Qwen/Qwen3-1.7B-GGUF` `Q5_K_M` checkpoint with a pinned repository revision. The model file is downloaded during the Docker build so runtime analysis does not depend on a first-request model download.

If model loading, generation, schema validation, or grounding validation fails, the service returns the deterministic evidence-backed analysis instead of replacing verified runtime facts.
