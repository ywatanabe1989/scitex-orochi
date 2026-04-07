"""Gitea and GitHub proxy routes for Orochi dashboard."""

from __future__ import annotations

import asyncio
import logging
import os
from typing import TYPE_CHECKING

import aiohttp
import aiohttp.web as web

from scitex_orochi._auth import verify_token

if TYPE_CHECKING:
    from scitex_orochi._server import OrochiServer

log = logging.getLogger("orochi.web.gitea")


async def handle_gitea_list_issues(request: web.Request) -> web.Response:
    """GET /api/gitea/issues/{owner}/{repo} -- list issues."""
    server: OrochiServer = request.app["orochi_server"]
    owner = request.match_info["owner"]
    repo = request.match_info["repo"]
    state = request.query.get("state", "open")
    try:
        issues = await server.gitea.list_issues(owner, repo, state=state)
        return web.json_response(issues)
    except Exception as exc:
        return web.json_response({"error": str(exc)}, status=502)


async def handle_gitea_create_issue(request: web.Request) -> web.Response:
    """POST /api/gitea/issues/{owner}/{repo} -- create an issue."""
    token = request.query.get("token")
    if not await verify_token(token):
        return web.json_response({"error": "Unauthorized"}, status=401)
    server: OrochiServer = request.app["orochi_server"]
    owner = request.match_info["owner"]
    repo = request.match_info["repo"]
    body = await request.json()
    title = body.get("title", "")
    if not title:
        return web.json_response({"error": "title is required"}, status=400)
    try:
        issue = await server.gitea.create_issue(
            owner=owner,
            repo=repo,
            title=title,
            body=body.get("body", ""),
            labels=body.get("labels"),
        )
        return web.json_response(issue, status=201)
    except Exception as exc:
        return web.json_response({"error": str(exc)}, status=502)


async def handle_gitea_list_repos(request: web.Request) -> web.Response:
    """GET /api/gitea/repos -- list repositories."""
    server: OrochiServer = request.app["orochi_server"]
    org = request.query.get("org", "")
    try:
        repos = await server.gitea.list_repos(org=org)
        return web.json_response(repos)
    except Exception as exc:
        return web.json_response({"error": str(exc)}, status=502)


async def handle_github_issues(request: web.Request) -> web.Response:
    """GET /api/github/issues -- proxy to GitHub API for ywatanabe1989/todo issues."""
    github_url = (
        "https://api.github.com/repos/ywatanabe1989/todo/issues?state=open&per_page=30"
    )
    headers = {
        "Accept": "application/vnd.github.v3+json",
        "User-Agent": "Orochi-Dashboard",
    }
    github_token = os.environ.get("GITHUB_TOKEN")
    if github_token:
        headers["Authorization"] = f"token {github_token}"

    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(
                github_url, headers=headers, timeout=aiohttp.ClientTimeout(total=10)
            ) as resp:
                if resp.status != 200:
                    body = await resp.text()
                    return web.json_response(
                        {"error": f"GitHub API returned {resp.status}", "detail": body},
                        status=resp.status,
                    )
                data = await resp.json()
                return web.json_response(data)
    except asyncio.TimeoutError:
        return web.json_response({"error": "GitHub API request timed out"}, status=504)
    except Exception as exc:
        return web.json_response({"error": str(exc)}, status=502)


def register_gitea_routes(app: web.Application) -> None:
    """Register Gitea and GitHub proxy routes on the app."""
    app.router.add_get("/api/gitea/issues/{owner}/{repo}", handle_gitea_list_issues)
    app.router.add_post("/api/gitea/issues/{owner}/{repo}", handle_gitea_create_issue)
    app.router.add_get("/api/gitea/repos", handle_gitea_list_repos)
    app.router.add_get("/api/github/issues", handle_github_issues)
