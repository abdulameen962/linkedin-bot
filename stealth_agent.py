import os
import asyncio
import json
import time
from typing import Dict, Any, Optional
from dotenv import load_dotenv
from smolagents import CodeAgent, OpenAIServerModel, tool
from stealth_bridge import stealth_bridge

load_dotenv()

# Configure LLM model directly via OpenRouter
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY", "")

import logging
from smolagents.utils import Retrying

_logger = logging.getLogger("stealth_agent")

def is_network_or_rate_limit_error(exception: BaseException) -> bool:
    """Check if exception is a transient network error, timeout, or rate limit."""
    err_str = f"{type(exception).__name__}: {repr(exception)} {str(exception)}".lower()
    transient_indicators = [
        "429", "rate limit", "rate_limit", "too many requests",
        "timeout", "timed out", "connection", "connecterror",
        "connection reset", "connection refused", "remotedisconnected",
        "socket", "500", "502", "503", "504", "server error",
        "service unavailable", "bad gateway", "gateway timeout",
        "aborted", "reset by peer", "no such host", "temporary", "network"
    ]
    return any(indicator in err_str for indicator in transient_indicators)

def _create_resilient_retryer(max_attempts: int = 100, wait_seconds: float = 3.0):
    return Retrying(
        max_attempts=max_attempts,
        wait_seconds=wait_seconds,
        exponential_base=1.5,
        jitter=True,
        retry_predicate=is_network_or_rate_limit_error,
        reraise=True,
        before_sleep_logger=(_logger, logging.WARNING),
    )

stealth_model = OpenAIServerModel(
    model_id="inclusionai/ling-3.0-flash-vl:free",
    api_base="https://openrouter.ai/api/v1",
    api_key=OPENROUTER_API_KEY,
    temperature=0.1,
    max_tokens=2048,
    timeout=120,
    client_kwargs={
        "default_headers": {
            "HTTP-Referer": "https://testinspector.com",
            "X-Title": "Stealth QA Agent",
        }
    }
)
stealth_model.retryer = _create_resilient_retryer(max_attempts=100, wait_seconds=3.0)

def run_async(coro, timeout: float = 35.0):
    """Executes a coroutine safely on the stealth bridge background thread."""
    if stealth_bridge.loop and stealth_bridge.loop.is_running():
        future = asyncio.run_coroutine_threadsafe(coro, stealth_bridge.loop)
        return future.result(timeout=timeout)
    else:
        try:
            loop = asyncio.get_event_loop()
            return loop.run_until_complete(coro)
        except Exception:
            return asyncio.run(coro)

@tool
def dom_structure_query_tool() -> str:
    """
    Queries the DOM of the currently active foreground Chrome tab in a stealth, read-only manner.
    Dumps the entire DOM structure of the page (HTML with tags, IDs, names, text, values, options, and inputs).
    Never alters or clicks elements on the page.

    Returns:
        A formatted string detailing the active tab's page title, URL, and the entire DOM structure.
    """
    try:
        data = run_async(stealth_bridge.query_dom_structure())
        title = data.get("title", "Untitled")
        url = data.get("url", "")
        dom = data.get("dom", "")

        return (
            f"=== ACTIVE TAB DOM SNAPSHOT ===\n"
            f"Page Title: {title}\n"
            f"Page URL: {url}\n\n"
            f"=== ENTIRE DOM STRUCTURE ===\n"
            f"{dom}"
        )
    except Exception as e:
        return f"[ERROR] Could not query active tab DOM: {e}"

STEALTH_INSTRUCTIONS = """You are an autonomous Question-Answering CodeAgent operating on the user's active Chrome browser tab.

Goal & Execution Strategy:
Whenever the user instructs you to start, resume, or run:
Continuously monitor and inspect the active Chrome browser tab:
1. Call `dom_structure_query_tool()` to receive the entire DOM structure of the active tab.
2. Directly inspect the raw DOM structure. Different websites structure questions and multiple-choice options differently (e.g. form inputs, custom divs, buttons, list elements, cards, etc.).
   - IF QUESTIONS WITH OPTIONS ARE FOUND ANYWHERE IN THE DOM:
     * Carefully analyze the question and all available options from the DOM.
     * Your answer must be ONLY the exact content of the option to choose, verbatim, and NOTHING ELSE (no explanations, reasoning, prefixes, or filler words). Provide this via `final_answer(...)` or `print(...)`.
   - IF NO QUESTIONS WITH OPTIONS ARE FOUND:
     * Output `skip`.
3. Call `time.sleep(30)` to wait 30 seconds before repeating the inspection.
4. Continue repeating this cycle continuously across steps.

Strict Operating Rules:
- STRICT OUTPUT REQUIREMENT: Output ONLY the exact option content to choose (or `skip` if no questions with options exist). Absolutely nothing else.
- STRICTLY READ-ONLY: You NEVER attempt to click, select, navigate, or modify elements on the page.
- You only have one tool: `dom_structure_query_tool`.
- Use Python's `time.sleep(30)` for the 30-second interval between queries.
"""

def create_stealth_agent() -> CodeAgent:
    """Creates and configures the autonomous stealth CodeAgent."""
    agent = CodeAgent(
        tools=[dom_structure_query_tool],
        model=stealth_model,
        instructions=STEALTH_INSTRUCTIONS,
        additional_authorized_imports=["time", "json"],
        max_steps=99999999999999999,
        verbosity_level=1,
    )
    return agent

# Singleton agent instance
stealth_agent = create_stealth_agent()
