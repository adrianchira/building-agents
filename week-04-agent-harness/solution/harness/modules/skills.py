"""Ready-made instructions for known jobs: a menu in the system prompt, the page loaded only when needed."""

from pathlib import Path

from pydantic import Field

from agent_core import tool
from life_tools import Args


def read_skill(path: Path) -> dict:
    """SKILL.md: a small header (name, description) between --- lines, then the instructions."""
    _, header, body = path.read_text(encoding="utf-8").split("---", 2)
    meta = dict(line.split(":", 1) for line in header.strip().splitlines())
    return {"name": meta["name"].strip(), "description": meta["description"].strip(), "body": body.strip()}


def skills_module(folder: str | Path) -> dict:
    skills = {s["name"]: s for s in map(read_skill, sorted(Path(folder).glob("*/SKILL.md")))}

    class LoadSkillIn(Args):
        name: str = Field(json_schema_extra={"enum": list(skills)})

    def load_skill(name: str) -> str:
        if name not in skills:
            raise ValueError(f"No skill '{name}'. Skills: {', '.join(skills)}")
        return skills[name]["body"]

    menu = "\n".join(f"- {s['name']}: {s['description']}" for s in skills.values())
    return {
        "system": "Skills: step-by-step instructions for jobs Alex asks for often. When a task matches one, "
                  "call load_skill with its name FIRST, then follow it.\n" + menu,
        "tools": {"load_skill": tool(load_skill, input_model=LoadSkillIn, description=
                                     "Load the full instructions of one skill from the menu in your instructions.")},
        "skills": skills,
    }
