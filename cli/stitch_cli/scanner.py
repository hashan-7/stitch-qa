from pathlib import Path
from collections import Counter
import platform

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

UNSUPPORTED_KNOWN_PROJECTS = {
    "Java Gradle Project": "Gradle support is planned for a future version.",
    "Node.js Project": "Node.js / npm support is planned for a future version.",
    "Angular Project": "Angular support is planned for a future version.",
    "Next.js Project": "Next.js support is planned for a future version.",
    "Nuxt.js Project": "Nuxt.js support is planned for a future version.",
    "Vite Project": "Vite support is planned for a future version.",
    "TypeScript Project": "TypeScript support is planned for a future version.",
    "PHP Composer Project": "PHP (Composer) support is planned for a future version.",
    "PHP Project": "PHP support is planned for a future version.",
    "Laravel Project": "Laravel support is planned for a future version.",
    "WordPress Project": "WordPress support is planned for a future version.",
    "Ruby Project": "Ruby support is planned for a future version.",
    "Go Project": "Go support is planned for a future version.",
    "Rust Project": "Rust support is planned for a future version.",
    "C# .NET Project": "C# / .NET support is planned for a future version.",
    "Swift Project": "Swift support is planned for a future version.",
    "Kotlin Project": "Kotlin support is planned for a future version.",
    "C Project": "C support is planned for a future version.",
    "C++ Project": "C++ support is planned for a future version.",
    "Flutter / Dart Project": "Flutter / Dart support is planned for a future version.",
    "Dart Project": "Dart support is planned for a future version.",
    "Shell Script Project": "Shell script support is planned for a future version.",
    "Bash Script Project": "Bash script support is planned for a future version.",
    "CMake Project": "CMake support is planned for a future version.",
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

    if (
        "pyproject.toml" in file_set
        or "requirements.txt" in file_set
        or "pytest.ini" in file_set
        or "setup.py" in file_set
        or "manage.py" in file_set
        or "app.py" in file_set
    ):
        return "Python Project"

    if "package.json" in file_set:
        if "angular.json" in file_set:
            return "Angular Project"
        if "next.config.js" in file_set or "next.config.ts" in file_set:
            return "Next.js Project"
        if "nuxt.config.js" in file_set or "nuxt.config.ts" in file_set:
            return "Nuxt.js Project"
        if "vite.config.js" in file_set or "vite.config.ts" in file_set:
            return "Vite Project"
        if "tsconfig.json" in file_set:
            return "TypeScript Project"
        if any(f.endswith(".ts") for f in files) or any(f.endswith(".tsx") for f in files):
            return "TypeScript Project"
        return "Node.js Project"

    if "tsconfig.json" in file_set:
        return "TypeScript Project"

    if any(f.endswith(".ts") for f in files) or any(f.endswith(".tsx") for f in files):
        return "TypeScript Project"

    if "composer.json" in file_set:
        return "PHP Composer Project"

    if "wp-config.php" in file_set:
        return "WordPress Project"

    if "artisan" in file_set:
        return "Laravel Project"

    if any(f.endswith(".php") for f in files):
        return "PHP Project"

    if "Gemfile" in file_set or "Rakefile" in file_set:
        return "Ruby Project"

    if any(f.endswith(".rb") for f in files):
        return "Ruby Project"

    if "go.mod" in file_set or "go.sum" in file_set:
        return "Go Project"

    if any(f.endswith(".go") for f in files):
        return "Go Project"

    if "Cargo.toml" in file_set or "Cargo.lock" in file_set:
        return "Rust Project"

    if any(f.endswith(".rs") for f in files):
        return "Rust Project"

    if any(f.endswith(".csproj") for f in files) or any(f.endswith(".sln") for f in files):
        return "C# .NET Project"

    if any(f.endswith(".cs") for f in files):
        return "C# .NET Project"

    if "Package.swift" in file_set:
        return "Swift Project"

    if any(f.endswith(".swift") for f in files):
        return "Swift Project"

    if any(f.endswith(".kt") for f in files) or any(f.endswith(".kts") for f in files):
        return "Kotlin Project"

    if "CMakeLists.txt" in file_set:
        return "CMake Project"

    if any(f.endswith(".cpp") for f in files) or any(f.endswith(".cxx") for f in files):
        return "C++ Project"

    if any(f.endswith(".c") for f in files):
        return "C Project"

    if "pubspec.yaml" in file_set:
        return "Flutter / Dart Project"

    if any(f.endswith(".dart") for f in files):
        return "Dart Project"

    if any(f.endswith(".sh") for f in files):
        return "Shell Script Project"

    if any(f.endswith(".bash") for f in files):
        return "Bash Script Project"

    return "Unknown Project"


def find_python_main_file(files):
    preferred_files = [
        "app.py",
        "main.py",
        "manage.py",
        "src/app.py",
        "src/main.py",
    ]

    file_set = set(file.replace("\\", "/") for file in files)

    for file in preferred_files:
        if file in file_set:
            return file

    for file in files:
        normalized_file = file.replace("\\", "/")
        if normalized_file.endswith(".py") and not normalized_file.startswith("tests/"):
            return file

    return None


def create_static_map(project_path, files, project_type):
    file_set = set(files)
    current_os = platform.system()

    static_map = {
        "build_file": None,
        "main_source_dir": None,
        "test_source_dir": None,
        "main_file": None,
        "suggested_command": None,
        "has_maven_wrapper": False,
        "wrapper_command": None,
        "wrapper_recommendation": None,
        "coming_soon_message": None,
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

        if current_os == "Windows":
            if "mvnw.cmd" in file_set:
                static_map["has_maven_wrapper"] = True
                static_map["wrapper_command"] = ".\\mvnw.cmd test"
                static_map["suggested_command"] = ".\\mvnw.cmd test"
            elif "mvnw" in file_set:
                static_map["has_maven_wrapper"] = True
                static_map["wrapper_command"] = "./mvnw test"
                static_map["suggested_command"] = "./mvnw test"
            else:
                static_map["suggested_command"] = "mvn test"
        else:
            if "mvnw" in file_set:
                static_map["has_maven_wrapper"] = True
                static_map["wrapper_command"] = "./mvnw test"
                static_map["suggested_command"] = "./mvnw test"
            elif "mvnw.cmd" in file_set:
                static_map["has_maven_wrapper"] = True
                static_map["wrapper_command"] = "./mvnw.cmd test"
                static_map["suggested_command"] = "./mvnw.cmd test"
            else:
                static_map["suggested_command"] = "mvn test"

        if not static_map.get("has_maven_wrapper"):
            static_map["wrapper_recommendation"] = (
                "This Maven project does not include Maven Wrapper files. "
                "For portable execution, add Maven Wrapper files such as mvnw, mvnw.cmd, "
                "and .mvn/wrapper so the project can run without requiring a global Maven installation."
            )

    elif project_type == "Python Project":
        if "pyproject.toml" in file_set:
            static_map["build_file"] = "pyproject.toml"
        elif "requirements.txt" in file_set:
            static_map["build_file"] = "requirements.txt"
        elif "setup.py" in file_set:
            static_map["build_file"] = "setup.py"
        elif "pytest.ini" in file_set:
            static_map["build_file"] = "pytest.ini"

        if any(file.startswith("src/") and file.endswith(".py") for file in normalized_files):
            static_map["main_source_dir"] = "src"
        elif any(file.endswith(".py") for file in normalized_files):
            static_map["main_source_dir"] = "."

        if any(file.startswith("tests/") and file.endswith(".py") for file in normalized_files):
            static_map["test_source_dir"] = "tests"
        elif any(Path(file).name.startswith("test_") and file.endswith(".py") for file in normalized_files):
            static_map["test_source_dir"] = "tests"

        static_map["main_file"] = find_python_main_file(files)
        static_map["suggested_command"] = "python -m pytest"

    else:
        static_map["suggested_command"] = None
        if project_type == "Unknown Project":
            static_map["coming_soon_message"] = "This project type could not be automatically recognized."
        else:
            static_map["coming_soon_message"] = UNSUPPORTED_KNOWN_PROJECTS.get(
                project_type,
                "Support for this project type is planned for a future release."
            )

    return static_map


def build_project_recommendations(project_type, static_map):
    recommendations = []

    if project_type == "Java Maven Project" and static_map.get("wrapper_recommendation"):
        recommendations.append(static_map["wrapper_recommendation"])

    if project_type == "Python Project" and not static_map.get("test_source_dir"):
        recommendations.append(
            "No Python test directory or test files were detected. "
            "Add pytest tests in a tests folder or files named test_*.py for better QA coverage."
        )

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