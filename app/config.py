import json
import logging
import os
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

logger = logging.getLogger(__name__)

env_path = Path(__file__).parent / ".env"
load_dotenv(dotenv_path=env_path)

# ---------------------------------------------------------------------------
# All known API keys (primary from .env, then fallbacks)
# ---------------------------------------------------------------------------
_CANDIDATE_KEYS: list[str] = [k for k in [
    os.getenv("GOOGLE_API_KEY", ""),
    "REDACTED",
    "REDACTED",
    "REDACTED",
    "REDACTED",
    "REDACTED",
    "REDACTED",
    "REDACTED",
    "REDACTED",
    "REDACTED",
] if k]

# Ordered by preference: lite first (more RPM), then full flash
_CANDIDATE_MODELS: list[str] = [
    "gemini-2.5-flash-lite",
    "gemini-2.5-flash",
    "gemini-2.0-flash-lite",
    "gemini-2.0-flash",
]


def _probe(key: str, model: str, timeout: int = 8) -> bool:
    """Return True if the key+model combo responds with HTTP 200."""
    url = (
        f"https://generativelanguage.googleapis.com/v1beta"
        f"/models/{model}:generateContent?key={key}"
    )
    payload = json.dumps({"contents": [{"parts": [{"text": "Hi"}]}]}).encode()
    req = urllib.request.Request(
        url, data=payload, headers={"Content-Type": "application/json"}
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status == 200
    except urllib.error.HTTPError:
        return False
    except Exception:
        return False


def pick_working_key_and_model(
    keys: list[str] = _CANDIDATE_KEYS,
    models: list[str] = _CANDIDATE_MODELS,
) -> tuple[str, str]:
    """Test every key × model combination and return the first (key, model) that works.

    Iterates keys in order, and for each key tries all models in preference order.
    Falls back to the last key + first model if nothing responds 200.
    """
    for key in keys:
        for model in models:
            if _probe(key, model):
                logger.info(f"[model-select] Using key=...{key[-8:]} model={model}")
                return key, model
            logger.debug(f"[model-select] Skip key=...{key[-8:]} model={model} (quota/error)")

    fallback_key = keys[-1] if keys else ""
    fallback_model = models[0]
    logger.warning(
        f"[model-select] All probes failed — falling back to key=...{fallback_key[-8:]} "
        f"model={fallback_model}"
    )
    return fallback_key, fallback_model


# ---------------------------------------------------------------------------
# Run selection at import time
# ---------------------------------------------------------------------------
_selected_key, _selected_model = pick_working_key_and_model()

# Override the active API key so the Gemini SDK picks it up
os.environ["GOOGLE_API_KEY"] = _selected_key
os.environ.setdefault("GOOGLE_GENAI_USE_VERTEXAI", "False")


@dataclass
class FXFROConfiguration:
    """Configuration for FX Front-Running-Order (FX-FRO) surveillance."""

    critic_model: str = field(default_factory=lambda: _selected_model)
    worker_model: str = field(default_factory=lambda: _selected_model)
    max_investigation_iterations: int = 5
    escalation_threshold: float = 0.80

    orders_data_path: str = "data/orders.csv"
    trades_data_path: str = "data/trades.csv"
    market_data_path: str = "data/market_data.csv"
    comms_data_path: str = "data/comms.csv"

    output_base_dir: str = "agent_outputs"

    lookback_minutes: int = 60
    cancel_rate_threshold: float = 0.70
    front_run_seconds: int = 60
    wash_trade_seconds: int = 300
    anomaly_threshold: float = 0.65


config = FXFROConfiguration()


# ---------------------------------------------------------------------------
# Rate-limit event tracker  (written by the patch, read by server.py endpoint)
# ---------------------------------------------------------------------------
import threading
import time as _time


class RateLimitTracker:
    """Thread-safe store for key-rotation events surfaced to the frontend."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.events: list[dict] = []

    def clear(self) -> None:
        with self._lock:
            self.events = []

    def push(self, event: dict) -> None:
        with self._lock:
            self.events.append({**event, "ts": _time.time()})

    def get_all(self) -> list[dict]:
        with self._lock:
            return list(self.events)


rate_limit_tracker = RateLimitTracker()


# ---------------------------------------------------------------------------
# Runtime key-rotation patch
# Catches 429 RESOURCE_EXHAUSTED mid-run and retries with the next key.
# api_client is a @cached_property — we delete it from __dict__ so it
# gets recreated with the new GOOGLE_API_KEY on the next LLM call.
# ---------------------------------------------------------------------------

def _install_key_rotation_patch() -> None:
    try:
        from google.adk.models import google_llm as _gllm
        from google.adk.models.google_llm import _ResourceExhaustedError

        _original = _gllm.Gemini.generate_content_async
        _all_keys = list(_CANDIDATE_KEYS)
        _all_models = list(_CANDIDATE_MODELS)

        async def _patched(self, llm_request, stream: bool = False):
            combos = [
                (key, model)
                for model in _all_models
                for key in _all_keys
            ]
            total = len(combos)
            last_error: Exception | None = None
            failed: list[str] = []

            for n, (key, model) in enumerate(combos, start=1):
                if os.environ.get("GOOGLE_API_KEY") != key:
                    os.environ["GOOGLE_API_KEY"] = key
                    self.__dict__.pop("api_client", None)
                    self.__dict__.pop("_api_backend", None)

                llm_request.model = model

                try:
                    async for item in _original(self, llm_request, stream):
                        yield item
                    return
                except _ResourceExhaustedError as exc:
                    last_error = exc
                    label = f"...{key[-8:]} / {model}"
                    failed.append(f"  {n:>2}. {label}  → QUOTA EXHAUSTED")
                    logger.warning(f"[key-rotation] combo {n}/{total}: {label} quota exhausted")

                    if n < total:
                        # Push a retry event so the frontend can display it
                        rate_limit_tracker.push({
                            "type": "retry",
                            "attempt": n,
                            "total": total,
                            "failed_combo": label,
                        })
                    continue

            # All combos exhausted
            summary = "\n".join(failed)
            logger.error(
                f"\n{'='*60}\n"
                f"[key-rotation] ALL {total} KEY+MODEL COMBOS EXHAUSTED:\n"
                f"{summary}\n"
                f"Free-tier daily quota is fully used up.\n"
                f"Wait until quota resets (midnight PT) or add a paid API key.\n"
                f"{'='*60}"
            )
            rate_limit_tracker.push({
                "type": "exhausted",
                "total": total,
                "failed": failed,
            })
            raise last_error

        _gllm.Gemini.generate_content_async = _patched
        logger.info(
            f"[key-rotation] Patch installed — "
            f"{len(_all_keys)} keys × {len(_all_models)} models = "
            f"{len(_all_keys) * len(_all_models)} combos"
        )
    except Exception as exc:
        logger.warning(f"[key-rotation] Could not install patch: {exc}")


_install_key_rotation_patch()
