"""SKILL.md discovery and loading from common agent directories."""

import logging
import re
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

import yaml

logger = logging.getLogger(__name__)

_SKILL_PATTERNS = [
    ".agents/skills/*/SKILL.md",
    ".github/skills/*/SKILL.md",
    ".claude/skills/*/SKILL.md",
    ".cursor/skills/*/SKILL.md",
    ".codex/skills/*/SKILL.md",
    ".cognition/skills/*/SKILL.md",
    ".windsurf/skills/*/SKILL.md",
]

_FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n", re.DOTALL)
_BACKTICK_CMD_RE = re.compile(r"`!([^`]+)`")
_PLACEHOLDER_RE = re.compile(r"\$(?:ARGUMENTS|\d+)")


@dataclass
class Skill:
    """Represents a loaded SKILL.md entry.

    Attributes:
        name: Skill identifier.
        description: Human-readable description.
        triggers: Keywords that activate this skill.
        allowed_tools: Tool names the skill may use.
        argument_hint: Hint for the ``$ARGUMENTS`` placeholder.
        content: Full skill content (after frontmatter removal).
        path: Filesystem path where the skill was found.
    """

    name: str
    description: str = ""
    triggers: list[str] = field(default_factory=list)
    allowed_tools: list[str] = field(default_factory=list)
    argument_hint: str = ""
    content: str = ""
    path: str = ""


class SkillLoader:
    """Discover and load SKILL.md files from common agent directories."""

    def __init__(self) -> None:
        """Initialise the loader."""
        self._skills: list[Skill] = []

    def load_skills(self, repo_path: str) -> list[Skill]:
        """Scan the repository for SKILL.md files and load them.

        Args:
            repo_path: Root path of the repository to scan.

        Returns:
            List of loaded Skill instances.
        """
        root = Path(repo_path)
        self._skills = []

        for pattern in _SKILL_PATTERNS:
            for path in root.glob(pattern):
                try:
                    skill = self._load_skill_file(path)
                    self._skills.append(skill)
                    logger.debug("Loaded skill: %s from %s", skill.name, path)
                except Exception as exc:
                    logger.warning("Failed to load skill at %s: %s", path, exc)

        logger.info("Loaded %d skills from %s", len(self._skills), repo_path)
        return self._skills

    def get_skill(self, name: str) -> Skill | None:
        """Retrieve a skill by name.

        Args:
            name: Skill name to look up.

        Returns:
            The matching Skill, or None if not found.
        """
        for skill in self._skills:
            if skill.name == name:
                return skill
        return None

    def render_skill(self, skill: Skill, arguments: str = "", args: list[str] | None = None) -> str:
        """Render a skill's content with placeholder substitution.

        Args:
            skill: The skill to render.
            arguments: Value for the ``$ARGUMENTS`` placeholder.
            args: Positional arguments for ``$0``, ``$1``, … placeholders.

        Returns:
            Rendered content string.
        """
        content = skill.content
        args = args or []

        # Replace $ARGUMENTS
        content = content.replace("$ARGUMENTS", arguments)

        # Replace positional $0, $1, ...
        for i, val in enumerate(args):
            content = content.replace(f"${i}", val)

        # Execute `!command` backtick blocks
        def run_cmd(match: re.Match[str]) -> str:
            cmd = match.group(1).strip()
            try:
                result = subprocess.run(
                    cmd, shell=True, capture_output=True, text=True, timeout=10
                )
                return result.stdout.strip()
            except Exception as exc:
                return f"(command failed: {exc})"

        content = _BACKTICK_CMD_RE.sub(run_cmd, content)
        return content

    def _load_skill_file(self, path: Path) -> Skill:
        """Parse a single SKILL.md file.

        Args:
            path: Path to the SKILL.md file.

        Returns:
            A populated Skill instance.
        """
        raw = path.read_text(encoding="utf-8")
        frontmatter: dict[str, object] = {}
        content = raw

        match = _FRONTMATTER_RE.match(raw)
        if match:
            try:
                frontmatter = yaml.safe_load(match.group(1)) or {}
            except yaml.YAMLError as exc:
                logger.warning("YAML parse error in %s: %s", path, exc)
            content = raw[match.end():]

        name = str(frontmatter.get("name", path.parent.name))
        description = str(frontmatter.get("description", ""))
        triggers_raw = frontmatter.get("triggers", [])
        triggers = list(triggers_raw) if isinstance(triggers_raw, list) else [str(triggers_raw)]
        tools_raw = frontmatter.get("allowed-tools", [])
        allowed_tools = list(tools_raw) if isinstance(tools_raw, list) else [str(tools_raw)]
        argument_hint = str(frontmatter.get("argument-hint", ""))

        return Skill(
            name=name,
            description=description,
            triggers=triggers,
            allowed_tools=allowed_tools,
            argument_hint=argument_hint,
            content=content.strip(),
            path=str(path),
        )
