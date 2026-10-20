"""Documentation validation checker.

Verifies that:
1. Every count in documentation (a number followed by words like tests, tools, cases, steps, hours, days, seconds)
   exists in numbers.md or the generated files.
2. Every file path named in documentation exists on disk.

Exits with code 0 if all checks pass, code 1 otherwise.
"""

from pathlib import Path
import re
import sys

DOCS_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = DOCS_DIR.parent
WORKSPACE_ROOT = PROJECT_ROOT.parent
GENERATED_DIR = DOCS_DIR / "generated"

COUNT_PATTERN = re.compile(
    r"\b(\d+)\s*(tests?|tools?|cases?|steps?|hours?|days?|seconds?)\b",
    re.IGNORECASE,
)

# Common extensions that identify file paths
FILE_EXTENSIONS = (
    ".py",
    ".json",
    ".csv",
    ".md",
    ".jsonl",
    ".txt",
    ".ini",
    ".yaml",
    ".yml",
)


def load_generated_numbers() -> set[str]:
    """Extract all numbers appearing in docs/generated/*.md."""
    numbers = set()
    if not GENERATED_DIR.exists():
        return numbers

    for f in GENERATED_DIR.glob("*.md"):
        content = f.read_text(encoding="utf-8")
        # Extract individual digits/numbers
        found = re.findall(r"\b\d+\b", content)
        numbers.update(found)
    return numbers


def resolve_file_path(path_str: str) -> bool:
    """Check if path_str resolves to an existing file or directory."""
    cleaned = path_str.strip()
    if not cleaned:
        return True

    # Strip URI scheme if present
    if cleaned.startswith("file:///"):
        cleaned = cleaned[8:]
    elif cleaned.startswith("file://"):
        cleaned = cleaned[7:]

    # Remove URL anchor or line numbers
    if "#" in cleaned:
        cleaned = cleaned.split("#")[0]
    if "::" in cleaned:
        cleaned = cleaned.split("::")[0]

    # Convert Windows forward/back slashes
    raw_path = Path(cleaned)
    if raw_path.is_absolute() and raw_path.exists():
        return True

    # Check relative to PROJECT_ROOT (finance_agent/)
    if (PROJECT_ROOT / cleaned).exists():
        return True

    # Check relative to WORKSPACE_ROOT (repo root)
    if (WORKSPACE_ROOT / cleaned).exists():
        return True

    # Strip leading 'finance_agent/' if checking within PROJECT_ROOT
    if cleaned.startswith("finance_agent/"):
        rel_sub = cleaned[len("finance_agent/"):]
        if (PROJECT_ROOT / rel_sub).exists():
            return True

    return False


def extract_file_paths(text: str) -> list[tuple[str, int]]:
    """Extract referenced file paths from markdown text along with line numbers."""
    paths_found = []

    for line_no, line in enumerate(text.splitlines(), 1):
        # 1. Markdown link targets: [text](path)
        for target in re.findall(r"\[[^\]]+\]\(([^)]+)\)", line):
            target = target.strip()
            # Skip web URLs, anchors, mailto
            if target.startswith(("http://", "https://", "#", "mailto:")):
                continue
            if "[DEPLOYED_URL]" in target:
                continue
            paths_found.append((target, line_no))

        # 2. Backtick code spans: `path`
        for code in re.findall(r"`([^`\n]+)`", line):
            code = code.strip()
            # Ignore code spans that are not paths
            if code.startswith(("http://", "https://")):
                continue
            if "[DEPLOYED_URL]" in code:
                continue
            # If it contains directory separators or ends with a known file extension
            if "/" in code or "\\" in code or any(code.endswith(ext) for ext in FILE_EXTENSIONS):
                # Avoid command line invocations or python imports
                if code.startswith("pytest ") or code.startswith("python ") or code.startswith("git "):
                    continue
                if " " in code and not any(code.endswith(ext) for ext in FILE_EXTENSIONS):
                    continue
                # If it looks like a function call e.g. func(a/b)
                if "(" in code or ")" in code:
                    continue
                paths_found.append((code, line_no))

    return paths_found


def check_document(doc_path: Path, valid_numbers: set[str]) -> list[str]:
    """Validate counts and file paths in a single markdown document."""
    errors = []
    text = doc_path.read_text(encoding="utf-8")

    # 1. Check numeric counts
    for line_no, line in enumerate(text.splitlines(), 1):
        # Ignore comments or metadata tags
        if line.strip().startswith("<!--"):
            continue

        for match in COUNT_PATTERN.finditer(line):
            num_str = match.group(1)
            word = match.group(2)
            if num_str not in valid_numbers:
                errors.append(
                    f"{doc_path.name}:{line_no}: Count '{num_str} {word}' is not in numbers.md or generated files."
                )

    # 2. Check file paths
    paths = extract_file_paths(text)
    for p_str, line_no in paths:
        if not resolve_file_path(p_str):
            errors.append(
                f"{doc_path.name}:{line_no}: File path '{p_str}' does not exist on disk."
            )

    return errors


def main():
    valid_numbers = load_generated_numbers()
    if not valid_numbers:
        print("ERROR: No generated numbers found. Run build_facts.py first.", file=sys.stderr)
        sys.exit(1)

    # Identify documentation files to check (TECHNICAL.md, SECURITY.md, FEATURES.md, USER_GUIDE.md, DEMO_SCRIPT.md, README.md, etc.)
    docs_to_check = []
    core_docs = [
        DOCS_DIR / "TECHNICAL.md",
        DOCS_DIR / "SECURITY.md",
        DOCS_DIR / "FEATURES.md",
        DOCS_DIR / "USER_GUIDE.md",
        DOCS_DIR / "DEMO_SCRIPT.md",
        PROJECT_ROOT / "README.md",
    ]
    for c in core_docs:
        if c.exists() and c not in docs_to_check:
            docs_to_check.append(c)

    for md in DOCS_DIR.glob("*.md"):
        if md not in docs_to_check and md.is_file():
            docs_to_check.append(md)

    if not docs_to_check:
        print("No documents found to validate.")
        sys.exit(0)

    total_errors = []
    for doc in docs_to_check:
        display_path = doc.name if doc == PROJECT_ROOT / "README.md" else doc.relative_to(PROJECT_ROOT)
        print(f"Checking {display_path}...")
        doc_errors = check_document(doc, valid_numbers)
        if doc_errors:
            total_errors.extend(doc_errors)

    if total_errors:
        print(f"\nFAILURE: {len(total_errors)} issue(s) detected:", file=sys.stderr)
        for err in total_errors:
            print(f"  - {err}", file=sys.stderr)
        sys.exit(1)

    print(f"\nSUCCESS: All counts and file paths in {len(docs_to_check)} document(s) verified.")
    sys.exit(0)


if __name__ == "__main__":
    main()
