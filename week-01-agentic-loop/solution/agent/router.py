"""Pick a model before the loop starts.

This part is a *workflow*: fixed steps, chosen by our code (classify -> look up -> run).
The loop that follows is the *agent*: the model chooses the steps.
"""

from dataclasses import dataclass
from typing import Any, Callable

from . import config
from .loop import AgentResult, run_agent
from .providers import is_available, open_conversation
from .tools import TOOLS, tool_schemas

TIERS = tuple(config.ROUTES)  # ("simple", "moderate", "hard")

CLASSIFIER_PROMPT = """\
You route tasks for a personal assistant. The assistant has tools to list and read files
(calendar, tasks, notes) and a calculator. Classify how demanding the task is FOR THAT AGENT:

- simple:   one or two tool calls, no real reasoning (list files, read one file, one sum)
- moderate: several tool calls and straightforward arithmetic over one or two files
- hard:     multi-step reasoning across several files, time arithmetic, judgement or ambiguity

Answer with the tier and a one-sentence reason."""

CLASSIFIER_SCHEMA = {
    "type": "object",
    "properties": {
        "tier": {"type": "string", "enum": list(TIERS)},
        "reason": {"type": "string"},
    },
    "required": ["tier", "reason"],
    "additionalProperties": False,
}


@dataclass
class Routing:
    tier: str
    reason: str
    provider: str
    model: str


def classify(task: str, *, client: Any = None) -> tuple[str, str]:
    """Return (tier, reason). Never raises: any failure falls back to DEFAULT_TIER."""
    provider, model = config.CLASSIFIER
    try:
        conv = open_conversation(provider, model, task, system=CLASSIFIER_PROMPT, client=client)
        answer = conv.complete_json(CLASSIFIER_SCHEMA)
        tier = answer.get("tier")
        if tier in TIERS:  # trust, but verify
            return tier, str(answer.get("reason", ""))
        return config.DEFAULT_TIER, f"classifier returned unknown tier {tier!r}"
    except Exception as exc:
        return config.DEFAULT_TIER, f"classifier failed ({type(exc).__name__}), using default"


def choose_model(tier: str, available: Callable[[str, str], bool] | None = None) -> tuple[str, str]:
    """First available candidate for `tier`; if none, try stronger tiers, then weaker ones."""
    available = available or is_available
    i = TIERS.index(tier)
    for t in TIERS[i:] + TIERS[:i][::-1]:
        for provider, model in config.ROUTES[t]:
            if available(provider, model):
                return provider, model
    raise RuntimeError("No configured model is available")


def route(task: str, *, client: Any = None,
          available: Callable[[str, str], bool] | None = None) -> Routing:
    tier, reason = classify(task, client=client)
    provider, model = choose_model(tier, available)
    return Routing(tier, reason, provider, model)


def run_routed(task: str, *, tools: dict = TOOLS, verbose: bool = True,
               clients: dict[str, Any] | None = None, **loop_kwargs: Any) -> tuple[Routing, AgentResult]:
    clients = clients or {}
    routing = route(task, client=clients.get(config.CLASSIFIER[0]))
    if verbose:
        print(f"🧭 tier={routing.tier} → {routing.provider}/{routing.model}  ({routing.reason})")
    conv = open_conversation(routing.provider, routing.model, task, tools=tool_schemas(tools),
                             system=config.SYSTEM_PROMPT, client=clients.get(routing.provider))
    return routing, run_agent(task, conversation=conv, tools=tools, verbose=verbose, **loop_kwargs)
