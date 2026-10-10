"""Tools = a JSON schema the model reads + a Python function we run.

The model never runs anything. It only *asks* for a tool by name with arguments;
`execute_tool` is where our code decides what actually happens.
"""

import ast
import operator
from pathlib import Path
from typing import Any, Callable

from .config import DATA_DIR
from .providers import ToolResult

MAX_FILE_CHARS = 20_000


# ---------- implementations ----------

def _safe_path(path: str) -> Path:
    """Resolve `path` inside DATA_DIR and refuse anything that escapes it."""
    target = (DATA_DIR / path).resolve()
    if not target.is_relative_to(DATA_DIR):
        raise PermissionError(f"'{path}' is outside the data folder")
    return target


def list_dir(path: str = ".") -> str:
    target = _safe_path(path)
    if not target.is_dir():
        raise FileNotFoundError(f"No such directory: '{path}'")
    entries = sorted(target.iterdir())
    if not entries:
        return "(empty directory)"
    return "\n".join(f"{p.name}/" if p.is_dir() else p.name for p in entries)


def read_file(path: str) -> str:
    target = _safe_path(path)
    if not target.is_file():
        raise FileNotFoundError(f"No such file: '{path}'. Use list_dir to see what exists.")
    text = target.read_text(encoding="utf-8")
    if len(text) > MAX_FILE_CHARS:
        return text[:MAX_FILE_CHARS] + f"\n... [truncated, file has {len(text)} chars]"
    return text


_OPS: dict[type, Callable[..., Any]] = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.Pow: operator.pow,
    ast.Mod: operator.mod,
    ast.USub: operator.neg,
    ast.UAdd: operator.pos,
}


def _eval_node(node: ast.AST) -> float:
    if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
        return node.value
    if isinstance(node, ast.BinOp) and type(node.op) in _OPS:
        return _OPS[type(node.op)](_eval_node(node.left), _eval_node(node.right))
    if isinstance(node, ast.UnaryOp) and type(node.op) in _OPS:
        return _OPS[type(node.op)](_eval_node(node.operand))
    raise ValueError(f"Unsupported expression element: {ast.dump(node)}")


def calculator(expression: str) -> str:
    """Evaluate + - * / ** % and parentheses. No names, no function calls (no eval!)."""
    tree = ast.parse(expression, mode="eval")
    result = _eval_node(tree.body)
    return str(round(result, 6))


# ---------- schemas (what the model sees) ----------

TOOLS: dict[str, dict[str, Any]] = {
    "list_dir": {
        "fn": list_dir,
        "schema": {
            "name": "list_dir",
            "description": (
                "List files and subfolders in the data folder. Folders end with '/'. "
                "Call this first when you don't know which files exist."
            ),
            "input_schema": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "Folder relative to the data folder. Use '.' for the root.",
                    }
                },
                "required": [],
            },
        },
    },
    "read_file": {
        "fn": read_file,
        "schema": {
            "name": "read_file",
            "description": (
                "Read a UTF-8 text file (e.g. CSV, TXT) from the data folder and return "
                "its full contents. Large files are truncated."
            ),
            "input_schema": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "File path relative to the data folder, e.g. 'calendar.csv'.",
                    }
                },
                "required": ["path"],
            },
        },
    },
    "calculator": {
        "fn": calculator,
        "schema": {
            "name": "calculator",
            "description": (
                "Evaluate an arithmetic expression exactly. Supports + - * / ** % and "
                "parentheses. Put a whole sum in one expression, e.g. "
                "'120*19.99 + 45*49.5'."
            ),
            "input_schema": {
                "type": "object",
                "properties": {
                    "expression": {"type": "string", "description": "The expression to evaluate."}
                },
                "required": ["expression"],
            },
        },
    },
}


def tool_schemas(tools: dict[str, dict[str, Any]] = TOOLS) -> list[dict[str, Any]]:
    return [t["schema"] for t in tools.values()]


def execute_tool(call: Any, tools: dict[str, dict[str, Any]] = TOOLS) -> ToolResult:
    """Run one tool call (anything with .id, .name, .input) and return a ToolResult.

    Errors are *returned to the model* (is_error=True), not raised: the model can
    read the message and recover, e.g. by calling list_dir after a bad path.
    """
    tool = tools.get(call.name)
    if tool is None:
        return ToolResult(call.id, f"Unknown tool '{call.name}'. Available: {', '.join(tools)}", True)
    try:
        return ToolResult(call.id, str(tool["fn"](**call.input)))
    except Exception as exc:  # any tool failure becomes information for the model
        return ToolResult(call.id, f"{type(exc).__name__}: {exc}", True)
