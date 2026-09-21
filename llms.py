import os
os.environ["LITELLM_LOCAL_MODEL_COST_MAP"] = "True"
from dotenv import load_dotenv
load_dotenv()

import litellm
litellm.telemetry = False
litellm.suppress_debug_info = True

from smolagents import LiteLLMModel, InferenceClientModel, OpenAIServerModel

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "fake_key_for_testing")
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY", "fake_key_for_testing")

# OpenRouter configuration to optimize latency
_openrouter_client_kwargs = {
    "default_headers": {
        "HTTP-Referer": "https://ascentrader.com",
        "X-Title": "Ascentrade",
    }
}
_openrouter_extra_body = {
    "provider": {
        "sort": "throughput",
    }
}

from smolagents.utils import Retrying
import logging

_logger = logging.getLogger("llms")

def is_network_or_rate_limit_error(exception: BaseException) -> bool:
    """Check if exception is a transient network error, timeout, or rate limit."""
    err_str = f"{type(exception).__name__}: {repr(exception)} {str(exception)}".lower()
    transient_indicators = [
        "429", "rate limit", "rate_limit", "too many requests",
        "timeout", "timed out", "connection", "connecterror",
        "connection reset", "connection refused", "remotedisconnected",
        "socket", "500", "502", "503", "504", "server error",
        "service unavailable", "bad gateway", "gateway timeout",
        "aborted", "reset by peer", "no such host", "temporary"
    ]
    return any(indicator in err_str for indicator in transient_indicators)

def _create_resilient_retryer(max_attempts: int = 5, wait_seconds: float = 3.0):
    return Retrying(
        max_attempts=max_attempts,
        wait_seconds=wait_seconds,
        exponential_base=2.0,
        jitter=True,
        retry_predicate=is_network_or_rate_limit_error,
        reraise=True,
        before_sleep_logger=(_logger, logging.WARNING),
    )

minimax_m3 = OpenAIServerModel( 
    model_id="nex-agi/nex-n2.5-pro:free",
    api_base="https://openrouter.ai/api/v1",
    api_key=OPENROUTER_API_KEY,
    temperature=0.1,
    max_tokens=2048,
    timeout=600,
    client_kwargs=_openrouter_client_kwargs,
    extra_body=_openrouter_extra_body,
)
minimax_m3.retryer = _create_resilient_retryer()

glm_53 = OpenAIServerModel( 
    model_id="nex-agi/nex-n2.5-pro:free",
    api_base="https://openrouter.ai/api/v1",
    api_key=OPENROUTER_API_KEY,
    temperature=0.1,
    max_tokens=2048,
    timeout=600,
    client_kwargs=_openrouter_client_kwargs,
    extra_body=_openrouter_extra_body,
)
glm_53.retryer = _create_resilient_retryer()