from pathlib import Path
from collections import Counter

IGNORED_DIRS = {
    ".git",
    "node_modules",
    "venv",
    ".venv",
    "__pycache__",
    "target",
    "build",
    "dist",
    ".idea",
    ".vscode",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
    ".gradle",
}

IGNORED_SUFFIXES = {
    ".egg-info",
}

IGNORED_FILES = {
    "STITCH_QA_REPORT.md",
    "STITCH_QA_REPORT.json",
}


def should_ignore(relative_path):
    if relative_path.name in IGNORED_FILES:
        return True

    for part in relative_path.parts:
        if part in IGNORED_DIRS:
            return True

        for suffix in IGNORED_SUFFIXES:
            if part.endswith(suffix):
                return True

    return False


def detect_project_type(files):
    file_set = set(files)

    if "pom.xml" in file_set:
        return "Java Maven Project"

    if "build.gradle" in file_set or "build.gradle.kts" in file_set:
        return "Java Gradle Project"

    if "package.json" in file_set:
        return "Node.js Project"

    if "requirements.txt" in file_set or "pyproject.toml" in file_set:
        return "Python Project"

    return "Unknown Project"


def create_static_map(project_path, files, project_type):
    file_set = set(files)

    static_map = {
        "build_file": None,
        "main_source_dir": None,
        "test_source_dir": None,
        "main_file": None,
        "suggested_command": None,
        "has_maven_wrapper": False,
        "wrapper_command": None,
        "wrapper_recommendation": None,
    }

    normalized_files = [file.replace("\\", "/") for file in files]

    if project_type == "Java Maven Project":
        static_map["build_file"] = "pom.xml"

        if any(file.startswith("src/main/java/") for file in normalized_files):
            static_map["main_source_dir"] = "src/main/java"

        if any(file.startswith("src/test/java/") for file in normalized_files):
            static_map["test_source_dir"] = "src/test/java"

        for file in files:
            if file.endswith("Application.java"):
                static_map["main_file"] = file
                break

        static_map["suggested_command"] = "mvn test"

        if "mvnw.cmd" in file_set:
            static_map["has_maven_wrapper"] = True
            static_map["wrapper_command"] = ".\\mvnw.cmd test"
            static_map["suggested_command"] = ".\\mvnw.cmd test"

        elif "mvnw" in file_set:
            static_map["has_maven_wrapper"] = True
            static_map["wrapper_command"] = "./mvnw test"
            static_map["suggested_command"] = "./mvnw test"

        else:
            static_map["wrapper_recommendation"] = (
                "This Maven project does not include Maven Wrapper files. "
                "For portable execution, add Maven Wrapper files such as mvnw, mvnw.cmd, "
                "and .mvn/wrapper so the project can run without requiring a global Maven installation."
            )

    return static_map


def build_project_recommendations(project_type, static_map):
    recommendations = []

    if project_type == "Java Maven Project" and static_map.get("wrapper_recommendation"):
        recommendations.append(static_map["wrapper_recommendation"])

    return recommendations


def scan_project(path):
    project_path = Path(path).resolve()

    if not project_path.exists():
        raise FileNotFoundError(f"Project path does not exist: {project_path}")

    if not project_path.is_dir():
        raise NotADirectoryError(f"Project path is not a directory: {project_path}")

    files = []
    total_folders = 0
    ignored_items = 0

    for item in project_path.rglob("*"):
        relative_path = item.relative_to(project_path)

        if should_ignore(relative_path):
            ignored_items += 1
            continue

        if item.is_dir():
            total_folders += 1

        if item.is_file():
            files.append(str(relative_path))

    extension_counts = Counter(
        Path(file).suffix.lower() or "[no extension]"
        for file in files
    )

    project_type = detect_project_type(files)
    static_map = create_static_map(project_path, files, project_type)
    project_recommendations = build_project_recommendations(project_type, static_map)

    return {
        "project_path": str(project_path),
        "project_type": project_type,
        "total_files": len(files),
        "total_folders": total_folders,
        "ignored_items": ignored_items,
        "files": files,
        "extension_counts": dict(extension_counts),
        "static_map": static_map,
        "project_recommendations": project_recommendations,
    }