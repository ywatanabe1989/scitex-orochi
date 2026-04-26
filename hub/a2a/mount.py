"""Build the Starlette sub-app that orochi mounts under ``/v1/agents/``.

The whole subtree is a single Starlette ``Mount("/v1/agents/{name}",
app=inner)``. The ``{name}`` path-param is propagated through to the
inner app's request scope, so :class:`hub.a2a.auth.WorkspaceTokenContextBuilder`
can read it from ``request.path_params`` and a single shared
:class:`OrochiAgentExecutor` instance handles every agent.

Card customisation per agent is done with a ``card_modifier`` async
hook on the well-known endpoint, which inspects the incoming request
and rebuilds the card from the live registry.

Task store
----------
Defaults to :class:`InMemoryTaskStore` — matches today's ``_PENDING``
semantics (single daphne process, fine for current scale). When
``SCITEX_OROCHI_A2A_DB_URL`` is set we build a SQLAlchemy async
engine and use :class:`DatabaseTaskStore` so tasks survive restarts.
The pre-flight recommended Database, but Redis isn't shipped by the
SDK and pointing at orochi's SQLite file races with Django writers,
so the conservative default is in-memory until a dedicated Postgres
URL is configured.
"""

from __future__ import annotations

import logging
import os
from functools import lru_cache
from typing import Any

from a2a.server.request_handlers import DefaultRequestHandler
from a2a.server.request_handlers.response_helpers import agent_card_to_dict
from a2a.server.routes.jsonrpc_routes import create_jsonrpc_routes
from a2a.server.tasks import InMemoryTaskStore
from a2a.types import AgentCard
from a2a.utils.constants import AGENT_CARD_WELL_KNOWN_PATH
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Mount, Route

from hub.a2a.auth import WorkspaceTokenContextBuilder
from hub.a2a.card import project_card
from hub.a2a.executor import OrochiAgentExecutor

log = logging.getLogger("orochi.a2a.mount")


def _build_task_store() -> Any:
    """Pick a task store. ``InMemory`` unless an A2A DB url is configured."""
    db_url = os.environ.get("SCITEX_OROCHI_A2A_DB_URL", "").strip()
    if not db_url:
        return InMemoryTaskStore()
    try:
        from a2a.server.tasks import DatabaseTaskStore
        from sqlalchemy.ext.asyncio import create_async_engine

        engine = create_async_engine(db_url, future=True)
        return DatabaseTaskStore(engine=engine, create_table=True)
    except Exception as exc:  # noqa: BLE001
        log.warning(
            "SCITEX_OROCHI_A2A_DB_URL set but DatabaseTaskStore init "
            "failed (%s); falling back to InMemoryTaskStore.",
            exc,
        )
        return InMemoryTaskStore()


@lru_cache(maxsize=1)
def _build_inner_app() -> Starlette:
    """Construct the inner Starlette app once.

    Uses a placeholder card on the SDK handler — the per-request card
    is rebuilt by ``_card_modifier`` so each
    ``.well-known/agent-card.json`` advertises the URL-named agent.
    """
    placeholder = AgentCard()
    placeholder.name = "orochi-fleet"
    placeholder.description = "orochi A2A surface — see /v1/agents/<name>/"
    placeholder.version = "scitex-orochi/1"

    handler = DefaultRequestHandler(
        agent_executor=OrochiAgentExecutor(),
        task_store=_build_task_store(),
        agent_card=placeholder,
    )

    builder = WorkspaceTokenContextBuilder()

    routes: list = []
    routes.extend(
        create_jsonrpc_routes(
            request_handler=handler,
            rpc_url="/",
            context_builder=builder,
            # v0.3 compat lets older clients keep using ``message/send``
            # and ``tasks/send`` method names alongside the gRPC-style
            # ``SendMessage`` names that the SDK 1.x core expects.
            enable_v0_3_compat=True,
        )
    )
    # Custom well-known route — the SDK's ``create_agent_card_routes``
    # ``card_modifier`` callback doesn't receive the request, so it
    # can't look up the per-Mount ``{name}`` path-param. We serve the
    # well-known path ourselves and project the registry entry on the
    # fly.
    routes.append(
        Route(
            AGENT_CARD_WELL_KNOWN_PATH,
            endpoint=_serve_agent_card,
            methods=["GET"],
        )
    )
    # Compat alias — older clients hit ``/.well-known/agent.json``.
    routes.append(
        Route("/.well-known/agent.json", endpoint=_serve_agent_card, methods=["GET"])
    )
    return Starlette(routes=routes)


async def _serve_agent_card(request: Request) -> JSONResponse:
    """Project the per-agent card from the registry and return JSON."""
    name = request.path_params.get("name") or ""
    base = f"{request.url.scheme}://{request.url.netloc}" if request.url.netloc else ""
    card = project_card(name, base_url=base)
    return JSONResponse(agent_card_to_dict(card))


def build_a2a_app() -> Starlette:
    """Top-level Starlette app mounted by ``orochi/asgi.py``."""
    inner = _build_inner_app()
    routes = [
        Mount("/v1/agents/{name}", app=inner),
    ]
    return Starlette(routes=routes)


__all__ = ["build_a2a_app"]
