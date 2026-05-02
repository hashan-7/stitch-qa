# Stitch QA

Stitch QA is a CLI-first AI-assisted QA tool for Java Maven projects.

It scans a project, detects the build structure, runs the project test command, analyzes execution logs, suggests safe repair actions, and generates Markdown and JSON QA reports.

## Version

Current version: `v1.0.0-java-maven`

## Version 1 Scope

Stitch QA v1 focuses on Java Maven projects.

Supported in v1:

- Java Maven project detection
- Maven Wrapper detection
- Maven test execution
- Log analysis using AI agent
- Repair suggestion using AI agent
- Code-level guidance using AI agent
- Markdown report generation
- JSON report generation
- Single code snippet analysis through CLI

Planned for later versions:

- Version 2: UI dashboard
- Version 3: Node.js, Python, Gradle, React/Vite and other project types

## Architecture

Stitch QA v1 uses the following components:

CLI Scanner  
↓  
Command Executor  
↓  
Log Agent  
↓  
Repair Agent  
↓  
Code Agent  
↓  
Markdown / JSON Reports

## Agents

The project uses three Hugging Face Spaces agents:

Log Agent  
https://hashan-7-stitch-qa-log-agent.hf.space

Repair Agent  
https://hashan-7-stitch-qa-repair-agent.hf.space

Code Agent  
https://hashan-7-stitch-qa-code-agent.hf.space

## Requirements

Recommended environment:

- Python 3.10+
- Java 17+
- Maven or Maven Wrapper
- Git
- Internet connection for AI agent calls

For Maven projects, Stitch QA prefers Maven Wrapper when available:

- mvnw
- mvnw.cmd
- .mvn/wrapper

If Maven Wrapper is not available, Stitch QA uses:

```powershell
mvn test

```

## Installation

Clone the repository:

```powershell
git clone https://github.com/hashan-7/stitch-qa.git
cd stitch-qa
```

Create and activate the CLI virtual environment:

```powershell
cd cli
python -m venv venv
.\venv\Scripts\activate
pip install -e .
cd ..
```

Check the CLI:

```powershell
stitch --help
```

## Basic Usage

Scan a project only:

```powershell
stitch scan .
```

Run full QA flow:

```powershell
stitch scan . --run --analyze --repair --code-fix
```

Run against the included demo project:

```powershell
stitch scan demo --run --analyze --repair --code-fix
```

Run against any local Java Maven project:

```powershell
stitch scan "C:\path\to\your\maven-project" --run --analyze --repair --code-fix
```

Or go into the project root and run:

```powershell
stitch scan . --run --analyze --repair --code-fix
```

## Single Code Analysis

Stitch QA can also analyze a pasted code snippet:

```powershell
stitch analyze-code
```

The CLI will ask for:

- Project type
- File path
- Code snippet
- Error log
- Root cause
- Repair summary

This is useful when you want code-level guidance without scanning a full project.

## Reports

After a full scan, Stitch QA generates:

- STITCH_QA_REPORT.md
- STITCH_QA_REPORT.json

The reports include:

- Project summary
- Static mapping
- Maven Wrapper status
- Project recommendations
- Execution result
- Log Agent analysis
- Repair Agent suggestions
- Code Agent suggestions
- Evidence logs
- Final QA status

## Example Output

Successful Maven project:

```text
Final QA Status: PASS
Tests run: 1, Failures: 0, Errors: 0, Skipped: 0
No blocking runtime error detected.
```

Maven environment issue:

```text
Maven is not installed or not available in PATH.
Install Apache Maven and add it to PATH, or add Maven Wrapper files to this project.
```

Compile error example:

```text
cannot find symbol
symbol: class MissingApplication
```

Code Agent can suggest a targeted fix such as:

```text
Change SpringApplication.run(MissingApplication.class, args);
to SpringApplication.run(DemoApplication.class, args);
```

## Maven Wrapper Recommendation

If a Maven project does not include Maven Wrapper files, Stitch QA recommends adding them:

- mvnw
- mvnw.cmd
- .mvn/wrapper

This allows the project to run without requiring Maven to be globally installed on the user's machine.

## Safety

Stitch QA v1 does not automatically modify project source code.

The agents provide suggestions only:

```text
auto_apply: false
```

Users should manually review and apply suggested changes.

## Limitations

Stitch QA v1 is focused on Java Maven projects.

Current limitations:

- Full run support is mainly for Java Maven projects
- Other project types may be detected but are not fully supported yet
- UI dashboard is not included in v1
- Automatic code patching is not enabled
- AI output should be reviewed before applying changes

## Development Workflow

Run the demo project:

```powershell
stitch scan demo --run --analyze --repair --code-fix
```

Run a broken Maven project test:

```powershell
stitch scan demo-broken --run --analyze --repair --code-fix
```

Install the CLI again after code changes:

```powershell
cd cli
.\venv\Scripts\activate
pip install -e .
cd ..
```

## Version Roadmap

v1.0.0-java-maven  
CLI-first Java Maven QA assistant

v2.0.0-ui-dashboard  
Browser dashboard for viewing reports and agent outputs

v3.0.0-multi-language  
Node.js, Python, Gradle, React/Vite and other project support

## License

This project is currently prepared as a development and demonstration project.
##

<div align="center">

**Developed by 💜 h7**  

</div>
