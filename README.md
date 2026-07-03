# Stitch QA

[![GitHub release](https://img.shields.io/github/v/release/hashan-7/stitch-qa)](https://github.com/hashan-7/stitch-qa/releases)
[![GitHub Actions](https://github.com/hashan-7/stitch-qa/actions/workflows/stitch-qa.yml/badge.svg)](https://github.com/hashan-7/stitch-qa/actions)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

AI-powered QA assistant for Java Maven and Python projects.

Stitch QA scans your project, detects the build structure, runs tests, analyzes execution logs, and provides AI-powered repair suggestions and code-level guidance through a simple CLI.

## Features

| Feature | V1 | V2 |
| --- | --- | --- |
| Java Maven detection and execution | Supported | Supported |
| Maven Wrapper detection | Supported | Supported |
| Python detection and pytest execution | Not supported | Supported |
| AI log analysis | Supported | Supported |
| AI repair suggestions | Supported | Supported |
| AI code guidance | Supported | Supported |
| Unsupported language handling | Not supported | Supported |
| OS-aware Maven Wrapper | Not supported | Supported |
| Docker support | Not supported | Supported |
| GitHub Actions integration | Not supported | Supported |
| Markdown report | Supported | Supported |
| JSON report | Supported | Supported |
| Single code snippet analysis | Supported | Supported |

## Installation

### Local CLI

```bash
pip install git+https://github.com/hashan-7/stitch-qa.git
```

Or clone and install locally:

```bash
git clone https://github.com/hashan-7/stitch-qa.git
cd stitch-qa/cli
python -m venv venv
source venv/bin/activate  # Windows: .\venv\Scripts\activate
pip install -e .
cd ..
```

### Docker

```bash
docker run --rm -v ${PWD}:/project hashan-7/stitch-qa:v2 scan /project --run --analyze --repair --code-fix
```

## Quick Start

### Scan a Java Maven project

```bash
stitch scan demo --run --analyze --repair --code-fix
```

### Scan a Python project

```bash
stitch scan demo-python --run --analyze --repair --code-fix
```

### Scan only

```bash
stitch scan .
```

### Analyze a code snippet

```bash
stitch analyze-code
```

## What Stitch QA Does

```text
Project Folder
     ↓
Scanner (language detection)
     ↓
Executor (OS-aware test runner)
     ↓
Log Agent (analyzes logs and finds root cause)
     ↓
Repair Agent (suggests safe repair actions)
     ↓
Code Agent (provides code-level guidance)
     ↓
Report (Markdown + JSON)
```

## Supported Languages

| Language | Build Tool | Status |
| --- | --- | --- |
| Java Maven | Maven | Supported |
| Python | pytest | Supported |
| Java Gradle | Gradle | Planned |
| Node.js | npm | Planned |
| PHP | Composer | Planned |
| TypeScript | tsc | Planned |
| Go | go.mod | Planned |
| Rust | Cargo | Planned |
| C# .NET | .NET | Planned |

## Coming Soon Handling

When Stitch QA detects a language that is not yet supported, it will skip execution cleanly and generate a report that explains the reason.

Example:

```text
Project Type: PHP Project
Skipping execution. This project type is not yet supported in this version.
PHP support is planned for a future version.
Supported: Java Maven (pom.xml), Python (requirements.txt / pyproject.toml)
Exiting cleanly with exit code 0.
```

## Reports

After a full scan, Stitch QA generates:

- `STITCH_QA_REPORT.md`
- `STITCH_QA_REPORT.json`

Reports include:

- Project summary
- Static mapping
- Execution result
- Log Agent analysis
- Repair Agent suggestions
- Code Agent guidance
- Evidence logs
- Final QA status

## AI Agents

| Agent | Purpose |
| --- | --- |
| Log Agent | Log analysis, summarization, root cause identification |
| Repair Agent | Repair suggestions, risk assessment, next actions |
| Code Agent | Code-level guidance, targeted fixes, verification steps |

## Agent URLs

- Log Agent: https://hashan-77-stitch-qa-log-agent.hf.space
- Repair Agent: https://hashan-77-stitch-qa-repair-agent.hf.space
- Code Agent: https://hashan-77-stitch-qa-code-agent.hf.space

## Docker Usage

```bash
docker build -t stitch-qa:local .
docker run --rm -v ${PWD}/demo:/project stitch-qa:local scan /project --run --analyze --repair --code-fix
```

## GitHub Actions Integration

Add `.github/workflows/stitch-qa.yml`:

```yaml
name: Stitch QA Scan
on:
  push:
    branches: [dev, main]
  pull_request:
    branches: [dev, main]
  workflow_dispatch:

jobs:
  qa-scan:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - name: Run Stitch QA
        uses: ./
        with:
          project-path: "."
      - name: Upload Reports
        uses: actions/upload-artifact@v4
        with:
          name: stitch-qa-reports
          path: STITCH_QA_REPORT.*
```

## Basic Commands

| Command | Description |
| --- | --- |
| `stitch scan .` | Scan project only |
| `stitch scan . --run` | Scan and run tests |
| `stitch scan . --run --analyze` | Scan, run, and analyze logs |
| `stitch scan . --run --analyze --repair` | Scan, run, analyze, and suggest repairs |
| `stitch scan . --run --analyze --repair --code-fix` | Full QA flow |
| `stitch analyze-code` | Analyze a code snippet manually |

## Requirements

| Requirement | Version |
| --- | --- |
| Python | 3.10+ |
| Java | 17+ |
| Maven | 3.6+ or Maven Wrapper |
| Docker | Optional |
| Git | Required for installation |

## Safety

Stitch QA does not automatically modify your source code. All AI suggestions are provided for manual review only.

## Development Workflow

```bash
stitch scan demo --run --analyze --repair --code-fix
stitch scan demo-python --run --analyze --repair --code-fix
mkdir demo-php && echo "<?php echo 'Hello'; ?>" > demo-php/index.php
stitch scan demo-php --run --analyze --repair --code-fix
```

## Version Roadmap

| Version | Focus | Status |
| --- | --- | --- |
| v1.0.0 | Java Maven CLI-first QA assistant | Released |
| v1.0.1 | Updated HF agent URLs | Released |
| v2.0.0 | Language UX + Docker + GitHub Actions + model upgrades | Released |
| v2.1.0 | Gradle support | Planned |
| v3.0.0 | Node.js, PHP, TypeScript, Go, Rust, C# | Planned |

## License

MIT License. See `LICENSE` for details.

## Acknowledgments

- FastAPI
- Hugging Face Transformers
- Click
- Rich

<div align="center">Developed with 💜 by H7</a></div>