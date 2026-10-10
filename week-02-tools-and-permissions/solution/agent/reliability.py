"""Three kinds of tool failure, three different owners:

  model-fixable  bad arguments, unknown id, SQL typo  -> returned to the MODEL with a hint
  transient      "database is locked", network blip   -> retried by OUR CODE, model never sees it
  fatal          database gone, credentials revoked   -> the RUN stops (FatalToolError)

Plus timeouts: a tool that hangs must not hang the agent.
"""

import functools
import time
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeout
from typing import Callable

from . import config


class TransientError(Exception):
    """Worth retrying: the same call may succeed in a moment."""


def with_retries(fn: Callable[..., str], attempts: int = config.RETRY_ATTEMPTS,
                 base_delay: float = 0.2) -> Callable[..., str]:
    @functools.wraps(fn)
    def wrapper(**kwargs):
        for attempt in range(1, attempts + 1):
            try:
                return fn(**kwargs)
            except TransientError as exc:
                if attempt == attempts:
                    # Out of retries: now it IS the model's problem, phrased so it can act on it.
                    raise RuntimeError(f"temporarily unavailable after {attempts} attempts ({exc}); "
                                       "tell the user and try again later") from exc
                time.sleep(base_delay * 2 ** (attempt - 1))  # exponential backoff
    return wrapper


_pool = ThreadPoolExecutor(max_workers=4, thread_name_prefix="tool-timeout")


def with_timeout(fn: Callable[..., str], seconds: float = config.TOOL_TIMEOUT_S) -> Callable[..., str]:
    """Abandon a tool after `seconds`. (Python can't kill the thread: the work keeps running
    in the background. Real agents run risky tools in subprocesses they *can* kill.)"""
    @functools.wraps(fn)
    def wrapper(**kwargs):
        future = _pool.submit(fn, **kwargs)
        try:
            return future.result(timeout=seconds)
        except FutureTimeout:
            raise TimeoutError(f"tool timed out after {seconds:g}s; try a narrower request") from None
    return wrapper
