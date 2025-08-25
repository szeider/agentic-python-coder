"""Simple markdown-based project system."""

import re
from pathlib import Path
from typing import List, Tuple
import importlib.util


def parse_project_file(file_path: str) -> Tuple[List[str], str]:
    """Parse a project markdown file.

    Extracts the packages block and returns the rest as content.

    Args:
        file_path: Path to the markdown file

    Returns:
        Tuple of (packages_list, markdown_content)
    """
    path = Path(file_path)
    if not path.exists():
        raise FileNotFoundError(f"Project file not found: {file_path}")

    content = path.read_text()

    # Look for ```packages block at the start
    packages_pattern = r"^```packages\s*\n(.*?)\n```\s*\n"
    match = re.match(packages_pattern, content, re.MULTILINE | re.DOTALL)

    packages = []
    remaining_content = content

    if match:
        # Extract package names
        packages_text = match.group(1)
        packages = [pkg.strip() for pkg in packages_text.split("\n") if pkg.strip()]

        # Remove the packages block from content
        remaining_content = content[match.end() :]

    return packages, remaining_content


def check_packages_available(packages: List[str]) -> List[str]:
    """Check which packages are available in the environment.

    Args:
        packages: List of package names to check

    Returns:
        List of unavailable packages
    """
    unavailable = []

    for package in packages:
        # Try to find the package
        spec = importlib.util.find_spec(package)
        if spec is None:
            unavailable.append(package)

    return unavailable


def create_project_prompt(
    packages: List[str], content: str, unavailable: List[str] = None
) -> str:
    """Create the project prompt from markdown content.

    Args:
        packages: List of available packages
        content: Markdown content
        unavailable: List of unavailable packages

    Returns:
        Formatted project prompt
    """
    prompt_parts = []

    # Add header
    prompt_parts.append("\n## Project Configuration Active\n")

    # Add available packages if any
    if packages:
        prompt_parts.append("### Package Status")

        # Show available packages
        available = [
            pkg for pkg in packages if not unavailable or pkg not in unavailable
        ]
        if available:
            prompt_parts.append("\n**✅ Available for import:**")
            for pkg in available:
                prompt_parts.append(f"- `{pkg}`")

        # Show unavailable packages
        if unavailable:
            prompt_parts.append("\n**❌ NOT available (will cause ImportError):**")
            for pkg in unavailable:
                prompt_parts.append(f"- `{pkg}`")
            prompt_parts.append(
                "\n⚠️ You must work around these missing packages using only standard library or the available packages listed above."
            )

        prompt_parts.append("")

    # Add the project content
    prompt_parts.append(content)

    return "\n".join(prompt_parts)
