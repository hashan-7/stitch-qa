from pathlib import Path, PurePosixPath
from collections import Counter
from configparser import ConfigParser, Error as ConfigParserError
from fnmatch import fnmatch
import platform
import posixpath
import shlex

try:
    import tomllib
except ModuleNotFoundError:
    tomllib = None

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

DEFAULT_PYTEST_FILE_PATTERNS = (
    "test_*.py",
    "*_test.py",
)

DEFAULT_MAVEN_TEST_FILE_PATTERNS = (
    "Test*.java",
    "*Test.java",
    "*Tests.java",
    "*TestCase.java",
)

PYTEST_CONFIG_FILES = (
    "pytest.toml",
    ".pytest.toml",
    "pytest.ini",
    ".pytest.ini",
    "pyproject.toml",
    "tox.ini",
    "setup.cfg",
)


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


def normalize_path(value):
    normalized = str(value).replace("\\", "/").strip()

    while normalized.startswith("./"):
        normalized = normalized[2:]

    return normalized.rstrip("/") or "."


def normalize_config_values(value):
    if value is None:
        return []

    if isinstance(value, (list, tuple, set)):
        items = []
        for item in value:
            items.extend(normalize_config_values(item))
        return items

    text = str(value).strip()
    if not text:
        return []

    try:
        values = shlex.split(text.replace("\n", " "))
    except ValueError:
        values = text.replace("\n", " ").split()

    return [item.strip() for item in values if item.strip()]


def read_toml_pytest_section(config_path):
    if tomllib is None:
        raise RuntimeError("TOML parsing requires Python 3.11 or the tomli package.")

    with config_path.open("rb") as config_file:
        data = tomllib.load(config_file)

    if config_path.name in {"pytest.toml", ".pytest.toml"}:
        section = data.get("pytest")
        return dict(section) if isinstance(section, dict) else None

    pytest_section = data.get("tool", {}).get("pytest")
    if not isinstance(pytest_section, dict):
        return None

    ini_options = pytest_section.get("ini_options")
    if isinstance(ini_options, dict):
        return dict(ini_options)

    return dict(pytest_section)


def read_ini_pytest_section(config_path):
    parser = ConfigParser(interpolation=None, strict=False)
    parser.read(config_path, encoding="utf-8")
    section_name = "tool:pytest" if config_path.name == "setup.cfg" else "pytest"

    if not parser.has_section(section_name):
        return None

    return {key: value for key, value in parser.items(section_name)}


def load_pytest_config(project_path):
    for config_name in PYTEST_CONFIG_FILES:
        config_path = project_path / config_name
        if not config_path.is_file():
            continue

        try:
            if config_path.suffix == ".toml":
                section = read_toml_pytest_section(config_path)
            else:
                section = read_ini_pytest_section(config_path)
        except (OSError, ValueError, ConfigParserError, RuntimeError) as error:
            return {}, config_name, f"Unable to parse {config_name}: {error}"

        if section is not None:
            return section, config_name, None

    return {}, None, None


def path_matches_test_path(file_path, test_path):
    normalized_file = normalize_path(file_path)
    normalized_test_path = normalize_path(test_path)

    if normalized_test_path == ".":
        return True

    if any(character in normalized_test_path for character in "*?["):
        return fnmatch(normalized_file, normalized_test_path) or fnmatch(
            normalized_file,
            f"{normalized_test_path}/**",
        )

    return normalized_file == normalized_test_path or normalized_file.startswith(
        f"{normalized_test_path}/"
    )


def common_parent(paths):
    if not paths:
        return None

    parents = [str(PurePosixPath(path).parent) for path in paths]
    shared_parent = posixpath.commonpath(parents)
    return shared_parent or "."


def discover_source_roots(files, source_marker):
    roots = set()
    marker = source_marker.strip("/")
    marker_with_separator = f"{marker}/"

    for file in files:
        normalized_file = normalize_path(file)
        if normalized_file.startswith(marker_with_separator):
            roots.add(marker)
            continue

        nested_marker = f"/{marker_with_separator}"
        if nested_marker in normalized_file:
            prefix = normalized_file.split(nested_marker, 1)[0]
            roots.add(f"{prefix}/{marker}")

    return sorted(roots, key=str.lower)


def detect_python_tests(project_path, files):
    config, config_file, config_warning = load_pytest_config(project_path)
    configured_patterns = normalize_config_values(config.get("python_files"))
    configured_test_paths = [
        normalize_path(value)
        for value in normalize_config_values(config.get("testpaths"))
    ]
    test_file_patterns = configured_patterns or list(DEFAULT_PYTEST_FILE_PATTERNS)
    normalized_files = sorted(
        (normalize_path(file) for file in files),
        key=str.lower,
    )

    test_files = []
    for file in normalized_files:
        if not file.endswith(".py"):
            continue

        if configured_test_paths and not any(
            path_matches_test_path(file, test_path)
            for test_path in configured_test_paths
        ):
            continue

        file_name = PurePosixPath(file).name
        if any(fnmatch(file_name, pattern) for pattern in test_file_patterns):
            test_files.append(file)

    test_source_dirs = []
    for test_path in configured_test_paths:
        if not any(character in test_path for character in "*?["):
            candidate_path = project_path / test_path
            if candidate_path.is_dir():
                test_source_dirs.append(test_path)

    for test_file in test_files:
        parent = str(PurePosixPath(test_file).parent) or "."
        if parent not in test_source_dirs:
            test_source_dirs.append(parent)

    default_test_dir = project_path / "tests"
    if default_test_dir.is_dir() and "tests" not in test_source_dirs:
        test_source_dirs.insert(0, "tests")

    if configured_test_paths:
        test_source_dir = configured_test_paths[0]
    else:
        test_source_dir = common_parent(test_files)
        if test_source_dir is None and default_test_dir.is_dir():
            test_source_dir = "tests"

    return {
        "has_tests": bool(test_files),
        "test_source_dir": test_source_dir,
        "test_source_dirs": test_source_dirs,
        "test_files": test_files,
        "test_files_count": len(test_files),
        "test_framework": "pytest",
        "test_detection_source": config_file or "pytest defaults",
        "test_file_patterns": test_file_patterns,
        "configured_test_paths": configured_test_paths,
        "test_detection_warning": config_warning,
    }


def detect_maven_tests(project_path, files):
    normalized_files = sorted(
        (normalize_path(file) for file in files),
        key=str.lower,
    )
    test_source_dirs = discover_source_roots(normalized_files, "src/test/java")

    if (project_path / "src/test/java").is_dir() and "src/test/java" not in test_source_dirs:
        test_source_dirs.insert(0, "src/test/java")

    test_files = []
    for file in normalized_files:
        if not file.endswith(".java"):
            continue

        if not any(
            file.startswith(f"{source_dir}/")
            for source_dir in test_source_dirs
        ):
            continue

        file_name = PurePosixPath(file).name
        if any(fnmatch(file_name, pattern) for pattern in DEFAULT_MAVEN_TEST_FILE_PATTERNS):
            test_files.append(file)

    return {
        "has_tests": bool(test_files),
        "test_source_dir": test_source_dirs[0] if test_source_dirs else None,
        "test_source_dirs": test_source_dirs,
        "test_files": test_files,
        "test_files_count": len(test_files),
        "test_framework": "Maven Surefire",
        "test_detection_source": "Maven standard layout and Surefire defaults",
        "test_file_patterns": list(DEFAULT_MAVEN_TEST_FILE_PATTERNS),
        "configured_test_paths": [],
        "test_detection_warning": None,
    }


def detect_project_type(files):
    normalized_files = [normalize_path(file) for file in files]
    file_set = set(normalized_files)

    if "pom.xml" in file_set:
        return "Java Maven Project"

    if "build.gradle" in file_set or "build.gradle.kts" in file_set:
        return "Java Gradle Project"

    if (
        "pyproject.toml" in file_set
        or "requirements.txt" in file_set
        or "pytest.ini" in file_set
        or ".pytest.ini" in file_set
        or "pytest.toml" in file_set
        or ".pytest.toml" in file_set
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
        if any(file.endswith(".ts") for file in normalized_files) or any(
            file.endswith(".tsx") for file in normalized_files
        ):
            return "TypeScript Project"
        return "Node.js Project"

    if "tsconfig.json" in file_set:
        return "TypeScript Project"

    if any(file.endswith(".ts") for file in normalized_files) or any(
        file.endswith(".tsx") for file in normalized_files
    ):
        return "TypeScript Project"

    if "composer.json" in file_set:
        return "PHP Composer Project"

    if "wp-config.php" in file_set:
        return "WordPress Project"

    if "artisan" in file_set:
        return "Laravel Project"

    if any(file.endswith(".php") for file in normalized_files):
        return "PHP Project"

    if "Gemfile" in file_set or "Rakefile" in file_set:
        return "Ruby Project"

    if any(file.endswith(".rb") for file in normalized_files):
        return "Ruby Project"

    if "go.mod" in file_set or "go.sum" in file_set:
        return "Go Project"

    if any(file.endswith(".go") for file in normalized_files):
        return "Go Project"

    if "Cargo.toml" in file_set or "Cargo.lock" in file_set:
        return "Rust Project"

    if any(file.endswith(".rs") for file in normalized_files):
        return "Rust Project"

    if any(file.endswith(".csproj") for file in normalized_files) or any(
        file.endswith(".sln") for file in normalized_files
    ):
        return "C# .NET Project"

    if any(file.endswith(".cs") for file in normalized_files):
        return "C# .NET Project"

    if "Package.swift" in file_set:
        return "Swift Project"

    if any(file.endswith(".swift") for file in normalized_files):
        return "Swift Project"

    if any(file.endswith(".kt") for file in normalized_files) or any(
        file.endswith(".kts") for file in normalized_files
    ):
        return "Kotlin Project"

    if "CMakeLists.txt" in file_set:
        return "CMake Project"

    if any(file.endswith(".cpp") for file in normalized_files) or any(
        file.endswith(".cxx") for file in normalized_files
    ):
        return "C++ Project"

    if any(file.endswith(".c") for file in normalized_files):
        return "C Project"

    if "pubspec.yaml" in file_set:
        return "Flutter / Dart Project"

    if any(file.endswith(".dart") for file in normalized_files):
        return "Dart Project"

    if any(file.endswith(".sh") for file in normalized_files):
        return "Shell Script Project"

    if any(file.endswith(".bash") for file in normalized_files):
        return "Bash Script Project"

    return "Unknown Project"


def find_python_main_file(files, test_files=None):
    preferred_files = [
        "app.py",
        "main.py",
        "manage.py",
        "src/app.py",
        "src/main.py",
    ]
    normalized_files = [normalize_path(file) for file in files]
    file_set = set(normalized_files)
    test_file_set = set(test_files or [])

    for file in preferred_files:
        if file in file_set and file not in test_file_set:
            return file

    for preferred_name in ("main.py", "app.py", "manage.py", "cli.py"):
        for file in normalized_files:
            if (
                PurePosixPath(file).name == preferred_name
                and file not in test_file_set
            ):
                return file

    excluded_names = {"__init__.py", "conftest.py", "setup.py"}
    for file in normalized_files:
        if (
            file.endswith(".py")
            and file not in test_file_set
            and PurePosixPath(file).name not in excluded_names
        ):
            return file

    return None


def create_static_map(project_path, files, project_type):
    normalized_files = [normalize_path(file) for file in files]
    file_set = set(normalized_files)
    current_os = platform.system()

    static_map = {
        "build_file": None,
        "main_source_dir": None,
        "test_source_dir": None,
        "test_source_dirs": [],
        "main_file": None,
        "suggested_command": None,
        "has_tests": False,
        "test_files_count": 0,
        "test_files": [],
        "test_framework": None,
        "test_detection_source": None,
        "test_file_patterns": [],
        "configured_test_paths": [],
        "test_detection_warning": None,
        "has_maven_wrapper": False,
        "wrapper_command": None,
        "wrapper_recommendation": None,
        "coming_soon_message": None,
    }

    if project_type == "Java Maven Project":
        static_map["build_file"] = "pom.xml"
        main_source_dirs = discover_source_roots(normalized_files, "src/main/java")
        if (project_path / "src/main/java").is_dir() and "src/main/java" not in main_source_dirs:
            main_source_dirs.insert(0, "src/main/java")
        static_map["main_source_dir"] = main_source_dirs[0] if main_source_dirs else None
        static_map.update(detect_maven_tests(project_path, normalized_files))

        for file in normalized_files:
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

        if not static_map["has_maven_wrapper"]:
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
        elif "pytest.toml" in file_set:
            static_map["build_file"] = "pytest.toml"
        elif ".pytest.toml" in file_set:
            static_map["build_file"] = ".pytest.toml"
        elif "pytest.ini" in file_set:
            static_map["build_file"] = "pytest.ini"
        elif ".pytest.ini" in file_set:
            static_map["build_file"] = ".pytest.ini"

        if any(file.startswith("src/") and file.endswith(".py") for file in normalized_files):
            static_map["main_source_dir"] = "src"
        elif any(file.endswith(".py") for file in normalized_files):
            static_map["main_source_dir"] = "."

        python_test_data = detect_python_tests(project_path, normalized_files)
        static_map.update(python_test_data)
        static_map["main_file"] = find_python_main_file(
            normalized_files,
            static_map["test_files"],
        )
        static_map["suggested_command"] = "python -m pytest"

    else:
        if project_type == "Unknown Project":
            static_map["coming_soon_message"] = "This project type could not be automatically recognized."
        else:
            static_map["coming_soon_message"] = UNSUPPORTED_KNOWN_PROJECTS.get(
                project_type,
                "Support for this project type is planned for a future release.",
            )

    return static_map


def build_project_recommendations(project_type, static_map):
    recommendations = []

    if project_type == "Java Maven Project":
        if static_map.get("wrapper_recommendation"):
            recommendations.append(static_map["wrapper_recommendation"])

        if not static_map.get("has_tests"):
            recommendations.append(
                "No Maven Surefire test classes were detected using the standard src/test/java layout "
                "and default class-name patterns. Add tests such as *Test.java or configure custom "
                "Surefire includes when the project uses a different convention."
            )

    if project_type == "Python Project" and not static_map.get("has_tests"):
        recommendations.append(
            "No pytest-compatible test files were detected using the active discovery configuration. "
            "Add tests matching the configured patterns or the default test_*.py and *_test.py patterns."
        )

    if static_map.get("test_detection_warning"):
        recommendations.append(static_map["test_detection_warning"])

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
            files.append(normalize_path(relative_path))

    files.sort(key=str.lower)

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
        "extension_counts": dict(sorted(extension_counts.items())),
        "static_map": static_map,
        "project_recommendations": project_recommendations,
    }
