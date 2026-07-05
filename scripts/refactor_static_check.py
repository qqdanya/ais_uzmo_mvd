#!/usr/bin/env python3
"""Lightweight refactor safety checks that do not require Django.

The script intentionally stays conservative: it catches the two regressions that
are easiest to introduce during mechanical refactors in this project:

* relative/imported names that no longer exist after moving functions between modules;
* unbalanced common Django template block tags after splitting large templates.
"""

from __future__ import annotations

import ast
import re
import sys
from dataclasses import dataclass
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
PYTHON_ROOTS = (PROJECT_ROOT / "apps", PROJECT_ROOT / "config")
TEMPLATE_ROOT = PROJECT_ROOT / "templates"

OPEN_CLOSE = {
    "if": "endif",
    "for": "endfor",
    "with": "endwith",
    "block": "endblock",
    "filter": "endfilter",
    "autoescape": "endautoescape",
    "spaceless": "endspaceless",
    "comment": "endcomment",
    "verbatim": "endverbatim",
}
CLOSERS = {value: key for key, value in OPEN_CLOSE.items()}
NEUTRAL_BLOCK_TAGS = {"elif", "else", "empty"}
TEMPLATE_TAG_RE = re.compile(r"{%\s*(.*?)\s*%}")


@dataclass(frozen=True)
class Issue:
    path: Path
    message: str

    def render(self) -> str:
        return f"{self.path.relative_to(PROJECT_ROOT)}: {self.message}"


def python_files() -> list[Path]:
    files: list[Path] = []
    for root in PYTHON_ROOTS:
        if root.exists():
            files.extend(path for path in root.rglob("*.py") if "__pycache__" not in path.parts)
    return sorted(files)


def module_name_for_path(path: Path) -> str:
    rel = path.relative_to(PROJECT_ROOT).with_suffix("")
    return ".".join(rel.parts)


def path_for_module(module: str) -> Path | None:
    candidate = PROJECT_ROOT.joinpath(*module.split(".")).with_suffix(".py")
    if candidate.exists():
        return candidate
    package_init = PROJECT_ROOT.joinpath(*module.split("."), "__init__.py")
    if package_init.exists():
        return package_init
    return None


def resolve_import_module(current_module: str, node: ast.ImportFrom) -> str | None:
    if node.level == 0:
        return node.module
    parts = current_module.split(".")
    # ast level=1 means from the current package, so remove the current module name only.
    package_parts = parts[: max(0, len(parts) - node.level)]
    if node.module:
        package_parts.extend(node.module.split("."))
    return ".".join(package_parts) if package_parts else None


def exported_names(path: Path, cache: dict[Path, set[str]]) -> set[str]:
    if path in cache:
        return cache[path]
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except SyntaxError:
        cache[path] = set()
        return cache[path]
    names: set[str] = set()
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            names.add(node.name)
        elif isinstance(node, (ast.Assign, ast.AnnAssign)):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            for target in targets:
                if isinstance(target, ast.Name):
                    names.add(target.id)
        elif isinstance(node, (ast.Import, ast.ImportFrom)):
            for alias in node.names:
                if alias.name == "*":
                    continue
                names.add(alias.asname or alias.name.split(".")[0])
    cache[path] = names
    return names


def check_imported_names() -> list[Issue]:
    issues: list[Issue] = []
    name_cache: dict[Path, set[str]] = {}
    for path in python_files():
        current_module = module_name_for_path(path)
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except SyntaxError as exc:
            issues.append(Issue(path, f"Python syntax error: {exc}"))
            continue
        for node in ast.walk(tree):
            if not isinstance(node, ast.ImportFrom) or any(alias.name == "*" for alias in node.names):
                continue
            module = resolve_import_module(current_module, node)
            if not module:
                continue
            module_path = path_for_module(module)
            # Only verify imports that point inside this repository.
            if not module_path or not str(module_path).startswith(str(PROJECT_ROOT)):
                continue
            available = exported_names(module_path, name_cache)
            for alias in node.names:
                if alias.name in available:
                    continue
                # ``from package import submodule`` is valid even when __init__.py does not re-export it.
                if path_for_module(f"{module}.{alias.name}"):
                    continue
                issues.append(Issue(path, f"missing import '{alias.name}' from {module}"))
    return issues


def check_template_blocks() -> list[Issue]:
    issues: list[Issue] = []
    if not TEMPLATE_ROOT.exists():
        return issues
    for path in sorted(TEMPLATE_ROOT.rglob("*.html")):
        stack: list[tuple[str, int]] = []
        for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
            for match in TEMPLATE_TAG_RE.finditer(line):
                tag = match.group(1).strip().split()[0] if match.group(1).strip() else ""
                tag = tag.split(".")[0]
                if tag in OPEN_CLOSE:
                    stack.append((tag, line_number))
                elif tag in CLOSERS:
                    if not stack:
                        issues.append(Issue(path, f"line {line_number}: unexpected '{tag}'"))
                        continue
                    opener, opener_line = stack.pop()
                    expected = OPEN_CLOSE[opener]
                    if tag != expected:
                        issues.append(Issue(path, f"line {line_number}: expected '{expected}' for '{opener}' from line {opener_line}, got '{tag}'"))
                elif tag in NEUTRAL_BLOCK_TAGS and not stack:
                    issues.append(Issue(path, f"line {line_number}: '{tag}' without open block"))
        for opener, opener_line in stack:
            issues.append(Issue(path, f"line {opener_line}: unclosed '{opener}', expected '{OPEN_CLOSE[opener]}'"))
    return issues


def main() -> int:
    issues = [*check_imported_names(), *check_template_blocks()]
    if issues:
        print("Refactor static check failed:", file=sys.stderr)
        for issue in issues:
            print(f"- {issue.render()}", file=sys.stderr)
        return 1
    print("Refactor static check passed: imports and template blocks look OK.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
