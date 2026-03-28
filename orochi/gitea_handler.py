"""Gitea message handler for OrochiServer."""

from __future__ import annotations

import logging
from typing import Any

from orochi.gitea import GiteaClient, GiteaError
from orochi.models import Message

log = logging.getLogger("orochi.gitea_handler")


async def handle_gitea_message(gitea: GiteaClient, ws: Any, msg: Message) -> None:
    """Forward Gitea API requests from agents and return results."""
    action = msg.payload.get("action", "")
    params = msg.payload.get("params", {})
    try:
        result = await _dispatch_action(gitea, action, params)
        if result is None:
            await ws.send(
                Message(
                    type="error",
                    sender="orochi-server",
                    payload={
                        "code": "GITEA_UNKNOWN_ACTION",
                        "detail": f"Unknown gitea action: {action}",
                    },
                ).to_json()
            )
            return

        await ws.send(
            Message(
                type="gitea_result",
                sender="orochi-server",
                payload={"action": action, "result": result, "ref": msg.id},
            ).to_json()
        )
    except GiteaError as exc:
        await ws.send(
            Message(
                type="error",
                sender="orochi-server",
                payload={
                    "code": "GITEA_API_ERROR",
                    "detail": exc.detail,
                    "status": exc.status,
                    "ref": msg.id,
                },
            ).to_json()
        )
    except KeyError as exc:
        await ws.send(
            Message(
                type="error",
                sender="orochi-server",
                payload={
                    "code": "GITEA_MISSING_PARAM",
                    "detail": f"Missing required parameter: {exc}",
                    "ref": msg.id,
                },
            ).to_json()
        )


async def _dispatch_action(gitea: GiteaClient, action: str, params: dict) -> Any:
    """Dispatch a gitea action, returning the result or None for unknown."""
    if action == "create_issue":
        return await gitea.create_issue(
            owner=params["owner"],
            repo=params["repo"],
            title=params["title"],
            body=params.get("body", ""),
            labels=params.get("labels"),
        )
    if action == "list_issues":
        return await gitea.list_issues(
            owner=params["owner"],
            repo=params["repo"],
            state=params.get("state", "open"),
        )
    if action == "close_issue":
        return await gitea.close_issue(
            owner=params["owner"],
            repo=params["repo"],
            issue_number=params["issue_number"],
        )
    if action == "add_comment":
        return await gitea.add_comment(
            owner=params["owner"],
            repo=params["repo"],
            issue_number=params["issue_number"],
            body=params["body"],
        )
    if action == "create_repo":
        return await gitea.create_repo(
            name=params["name"],
            org=params.get("org", ""),
            private=params.get("private", False),
        )
    if action == "create_org":
        return await gitea.create_org(
            name=params["name"],
            description=params.get("description", ""),
        )
    if action == "list_repos":
        return await gitea.list_repos(org=params.get("org", ""))
    if action == "get_version":
        return {"version": await gitea.get_version()}
    return None
