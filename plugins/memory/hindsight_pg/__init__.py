"""PG-backed hindsight memory provider — subclasses HindsightMemoryProvider.

Adds PostgreSQL database URL passthrough for the embedded daemon,
LM Studio provider detection for local LLM endpoints, and embedding
model configuration.

Inherits all functionality from the upstream hindsight provider.
Only overrides what's needed for PG/local-LLM customization.
"""

from __future__ import annotations

import logging
import os

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Monkey-patch _build_embedded_profile_env so the embedded daemon's .env
# file includes our custom settings (LM Studio detection, embedding config,
# database URL).  This is called when materializing the daemon env file and
# when comparing config changes.
# ---------------------------------------------------------------------------

def _patch_build_env():
    import plugins.memory.hindsight as _h

    _orig = _h._build_embedded_profile_env

    def _patched(config, *, llm_api_key=None):
        env = _orig(config, llm_api_key=llm_api_key)

        current_provider = config.get("llm_provider", "")
        current_base_url = (
            config.get("llm_base_url")
            or os.environ.get("HINDSIGHT_API_LLM_BASE_URL", "")
        )

        if current_provider in {"openai_compatible", "openrouter"}:
            if current_base_url and (
                "127.0.0.1" in current_base_url or "localhost" in current_base_url
            ):
                env["HINDSIGHT_API_LLM_PROVIDER"] = "lmstudio"

        env["HINDSIGHT_API_EMBEDDINGS_PROVIDER"] = "openai"
        env["HINDSIGHT_API_EMBEDDINGS_OPENAI_MODEL"] = (
            "text-embedding-nomic-embed-text-v1.5@q5_0"
        )
        env["HINDSIGHT_API_RERANKER_PROVIDER"] = "rrf"
        if current_base_url:
            env["HINDSIGHT_API_EMBEDDINGS_OPENAI_BASE_URL"] = str(current_base_url)
            env["HINDSIGHT_API_EMBEDDINGS_BASE_URL"] = str(current_base_url)

        database_url = (
            config.get("database_url")
            or os.environ.get("HINDSIGHT_API_DATABASE_URL", "")
        )
        if database_url:
            env["HINDSIGHT_API_DATABASE_URL"] = str(database_url)

        return env

    _h._build_embedded_profile_env = _patched


_patch_build_env()


# ---------------------------------------------------------------------------
# Custom provider
# ---------------------------------------------------------------------------

from plugins.memory.hindsight import (  # noqa: E402
    HindsightMemoryProvider,
    _DEFAULT_IDLE_TIMEOUT,
    _DEFAULT_TIMEOUT,
    _parse_int_setting,
)


class HindsightPGMemoryProvider(HindsightMemoryProvider):
    """Hindsight memory provider with PostgreSQL storage support.

    Same as upstream HindsightMemoryProvider but adds:
      * ``HINDSIGHT_API_DATABASE_URL`` passthrough to HindsightEmbedded
      * ``database_url`` config key in the setup schema
    """

    @property
    def name(self) -> str:
        return "hindsight_pg"

    # ------------------------------------------------------------------
    # Config schema
    # ------------------------------------------------------------------

    def get_config_schema(self):
        schema = super().get_config_schema()
        schema.append({
            "key": "database_url",
            "description": (
                "External PostgreSQL connection string "
                "(default: embedded pg0)"
            ),
            "when": {"mode": "local_embedded"},
        })
        return schema

    # ------------------------------------------------------------------
    # Initialize — inject database_url from env into self._config
    # ------------------------------------------------------------------

    def initialize(self, session_id: str, **kwargs) -> None:
        super().initialize(session_id, **kwargs)
        if not self._config.get("database_url"):
            db_url = os.environ.get("HINDSIGHT_API_DATABASE_URL", "")
            if db_url:
                self._config["database_url"] = db_url

    # ------------------------------------------------------------------
    # Client creation — add database_url to HindsightEmbedded kwargs
    # ------------------------------------------------------------------

    def _get_client(self):
        if self._client is not None:
            return self._client

        if self._mode != "local_embedded":
            return super()._get_client()

        from tools.lazy_deps import ensure as _lazy_ensure
        _lazy_ensure("memory.hindsight", prompt=False)

        from hindsight import HindsightEmbedded
        HindsightEmbedded.__del__ = lambda self: None

        llm_provider = self._config.get("llm_provider", "")
        if llm_provider in {"openai_compatible", "openrouter"}:
            llm_provider = "openai"

        logger.debug(
            "Creating HindsightEmbedded client (profile=%s, provider=%s)",
            self._config.get("profile", "hermes"), llm_provider,
        )

        kwargs = dict(
            profile=self._config.get("profile", "hermes"),
            llm_provider=llm_provider,
            llm_api_key=(
                self._config.get("llmApiKey")
                or self._config.get("llm_api_key")
                or os.environ.get("HINDSIGHT_LLM_API_KEY", "")
            ),
            llm_model=self._config.get("llm_model", ""),
        )
        if self._llm_base_url:
            kwargs["llm_base_url"] = self._llm_base_url

        idle_timeout = _parse_int_setting(
            (
                self._config.get("idle_timeout")
                if self._config.get("idle_timeout") is not None
                else os.environ.get(
                    "HINDSIGHT_IDLE_TIMEOUT", self._idle_timeout
                )
            ),
            _DEFAULT_IDLE_TIMEOUT,
        )
        self._idle_timeout = idle_timeout
        kwargs["idle_timeout"] = idle_timeout

        database_url = (
            self._config.get("database_url")
            or os.environ.get("HINDSIGHT_API_DATABASE_URL", "")
        )
        if database_url:
            kwargs["database_url"] = database_url

        self._client = HindsightEmbedded(**kwargs)
        return self._client


def register(ctx) -> None:
    """Register hindsight_pg as a memory provider plugin."""
    ctx.register_memory_provider(HindsightPGMemoryProvider())
