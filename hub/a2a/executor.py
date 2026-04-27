"""SDK ``AgentExecutor`` for orochi-served agents.

Resolves the target agent name from the request context (set by
:class:`hub.a2a.auth.WorkspaceTokenContextBuilder` from the URL's
``{name}`` segment), looks up the registry entry, and dispatches via:

1. **Tier-3 HTTP-direct** — if the registry has a non-empty
   ``a2a_url``, POST the JSON-RPC envelope synthesised from the SDK
   request to it. Reply is returned as a single agent message.
2. **WebSocket fallback** — push an ``a2a.dispatch`` Channels frame to
   the per-agent group and await a reply via the existing ``_PENDING``
   correlation map (set by ``api_a2a_reply``).

The agent's reply is mapped to either a single ``new_agent_message``
(immediate completion) or, when the reply contains an artifact-shaped
payload, an ``add_artifact`` event followed by ``complete()``.
"""

from __future__ import annotations

import asyncio
import json
import logging
import secrets
import time
from typing import Any

from a2a.server.agent_execution import AgentExecutor
from a2a.server.agent_execution.context import RequestContext
from a2a.server.events import EventQueue
from a2a.server.tasks import TaskUpdater
from a2a.types import Part, Task, TaskState, TaskStatus
from channels.layers import get_channel_layer

from hub.a2a._dispatch_internals import (
    _PENDING,
    DISPATCH_TIMEOUT_SECONDS,
    _agent_group,
    _resolve_workspace_id,
    _try_http_direct,
)

log = logging.getLogger("orochi.a2a.executor")


def _extract_text_from_message(msg: Any) -> str:
    """Concatenate text parts from an SDK ``Message`` protobuf."""
    if msg is None:
        return ""
    chunks: list[str] = []
    for part in msg.parts:
        # ``Part`` is a oneof: ``text | raw | url | data``.
        if part.HasField("text"):
            chunks.append(part.text)
        elif part.HasField("data"):
            try:
                chunks.append(json.dumps(dict(part.data)))
            except Exception:  # noqa: BLE001
                chunks.append(str(part.data))
    return "\n".join(chunks)


class _AgentNotFoundError(Exception):
    """Raised when the URL-named agent has no registry entry."""


class _UnauthenticatedError(Exception):
    """Raised when the request carries no valid WorkspaceToken."""


class OrochiAgentExecutor(AgentExecutor):
    """Single shared executor — agent name comes from the request context.

    One instance is registered with the SDK ``DefaultRequestHandler``
    and serves every ``/v1/agents/<name>/`` route via the
    :class:`Mount` URL parameter that
    :class:`WorkspaceTokenContextBuilder` extracts.
    """

    async def execute(self, context: RequestContext, event_queue: EventQueue) -> None:
        state = (context.call_context and context.call_context.state) or {}
        workspace = state.get("workspace")
        agent_name = state.get("agent_name") or ""

        updater = TaskUpdater(
            event_queue=event_queue,
            task_id=context.task_id,
            context_id=context.context_id,
        )

        # SDK contract: a Task must be enqueued before any
        # TaskStatusUpdateEvent. The legacy view didn't have to do this
        # because it was not SDK-aware. We seed a SUBMITTED task so the
        # framework's task store has something to update.
        if context.orochi_current_task is None:
            seed = Task()
            seed.id = context.task_id
            seed.context_id = context.context_id
            seed.status.CopyFrom(TaskStatus(state=TaskState.TASK_STATE_SUBMITTED))
            await event_queue.enqueue_event(seed)

        if workspace is None:
            await updater.failed(
                updater.new_agent_message(
                    [self._text_part("authentication required (WorkspaceToken)")]
                )
            )
            return
        if not agent_name:
            await updater.failed(
                updater.new_agent_message(
                    [self._text_part("agent name missing from URL")]
                )
            )
            return

        from hub.registry import _agents  # local import — avoid bootstrap order

        reg_entry = _agents.get(agent_name)
        if reg_entry is None:
            await updater.failed(
                updater.new_agent_message(
                    [self._text_part(f"agent not found or offline: {agent_name}")]
                )
            )
            return

        # SDK 1.x JSON-RPC envelope — the agent's sac sidecar serves
        # pure a2a-sdk 1.x (no v0.3 compat) after Phase 1, so we use
        # the gRPC-style ``SendMessage`` method with proto snake_case
        # params. The WS bridge handler must accept the same shape.
        body = {
            "jsonrpc": "2.0",
            "id": context.task_id,
            "method": "SendMessage",
            "params": {
                "message": {
                    "message_id": context.task_id,
                    "role": "ROLE_USER",
                    "parts": [{"text": _extract_text_from_message(context.message)}],
                },
            },
        }

        # Move the task into the WORKING state — distinct from the
        # initial SUBMITTED that we seeded with the Task event above.
        await updater.start_work()

        # Tier-3: HTTP-direct if a sidecar is announced.
        a2a_url = (reg_entry.get("a2a_url") or "").strip()
        result: dict | None = None
        if a2a_url:
            ok, http_result = await asyncio.to_thread(_try_http_direct, a2a_url, body)
            if ok and http_result is not None:
                result = http_result

        # Fallback: Channels group_send → agent's WS bridge → api_a2a_reply.
        if result is None:
            ws_id = await _resolve_workspace_id(str(workspace.id))
            if ws_id is None:
                await updater.failed(
                    updater.new_agent_message(
                        [
                            self._text_part(
                                f"workspace not found: {getattr(workspace, 'id', '?')}"
                            )
                        ]
                    )
                )
                return

            reply_id = secrets.token_urlsafe(16)
            event = asyncio.Event()
            _PENDING[reply_id] = {"event": event, "value": None, "ts": time.time()}

            layer = get_channel_layer()
            if layer is None:
                _PENDING.pop(reply_id, None)
                await updater.failed(
                    updater.new_agent_message(
                        [self._text_part("no channel layer configured")]
                    )
                )
                return

            try:
                await layer.group_send(
                    _agent_group(ws_id, agent_name),
                    {
                        "type": "a2a.dispatch",
                        "reply_id": reply_id,
                        "body": body,
                    },
                )
                try:
                    await asyncio.wait_for(
                        event.wait(), timeout=DISPATCH_TIMEOUT_SECONDS
                    )
                    result = _PENDING[reply_id]["value"]
                except asyncio.TimeoutError:
                    result = None
            except Exception as exc:  # noqa: BLE001
                log.exception("a2a executor dispatch failed: %s", exc)
                result = None
            finally:
                _PENDING.pop(reply_id, None)

        if result is None:
            await updater.failed(
                updater.new_agent_message(
                    [
                        self._text_part(
                            f"timeout waiting for reply from agent {agent_name!r}"
                        )
                    ]
                )
            )
            return

        # Map JSON-RPC reply → SDK events. The legacy reply shape is
        # ``{"jsonrpc":..,"id":..,"result":{"status":"completed",
        # "message":{"parts":[...]}}}`` or a plain dict; be permissive.
        text = self._reply_text(result)
        await updater.complete(updater.new_agent_message([self._text_part(text)]))

    async def cancel(self, context: RequestContext, event_queue: EventQueue) -> None:
        # The legacy bridge has no cancel channel; mark the task
        # cancelled locally so the SDK state orochi_machine stays consistent.
        updater = TaskUpdater(
            event_queue=event_queue,
            task_id=context.task_id,
            context_id=context.context_id,
        )
        await updater.cancel(
            updater.new_agent_message(
                [
                    self._text_part(
                        "cancellation requested; agent bridge has no cancel hook"
                    )
                ]
            )
        )

    # ------------------------------------------------------------------
    # helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _text_part(text: str) -> Part:
        p = Part()
        p.text = text
        return p

    @staticmethod
    def _reply_text(result: Any) -> str:
        """Extract a human-readable text payload from a legacy reply."""
        if isinstance(result, str):
            return result
        if not isinstance(result, dict):
            return json.dumps(result, ensure_ascii=False)
        # JSON-RPC envelope?
        inner = result.get("result", result)
        if isinstance(inner, dict):
            msg = inner.get("message")
            if isinstance(msg, dict):
                parts = msg.get("parts") or []
                texts = [p.get("text", "") for p in parts if isinstance(p, dict)]
                joined = "\n".join(t for t in texts if t)
                if joined:
                    return joined
            for key in ("text", "content", "output"):
                v = inner.get(key)
                if isinstance(v, str):
                    return v
        return json.dumps(result, ensure_ascii=False)


__all__ = ["OrochiAgentExecutor"]
