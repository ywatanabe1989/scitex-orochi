"""Async Gitea API client for Orochi agents."""

from __future__ import annotations

import logging
from typing import Any

import aiohttp

log = logging.getLogger("orochi.gitea")


class GiteaError(Exception):
    """Raised when a Gitea API call fails."""

    def __init__(self, status: int, detail: str) -> None:
        self.status = status
        self.detail = detail
        super().__init__(f"Gitea API error {status}: {detail}")


class GiteaClient:
    """Async client for the Gitea REST API (v1)."""

    def __init__(self, base_url: str, token: str = "") -> None:
        self.base_url = base_url.rstrip("/")
        self.token = token
        self._session: aiohttp.ClientSession | None = None

    def _headers(self) -> dict[str, str]:
        headers: dict[str, str] = {"Content-Type": "application/json"}
        if self.token:
            headers["Authorization"] = f"token {self.token}"
        return headers

    async def _ensure_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(headers=self._headers())
        return self._session

    async def close(self) -> None:
        if self._session and not self._session.closed:
            await self._session.close()

    async def _request(
        self, method: str, path: str, json_data: dict | None = None
    ) -> Any:
        session = await self._ensure_session()
        url = f"{self.base_url}/api/v1{path}"
        log.debug("%s %s", method, url)
        async with session.request(method, url, json=json_data) as resp:
            body = await resp.text()
            if resp.status >= 400:
                raise GiteaError(resp.status, body)
            if not body:
                return {}
            return await resp.json()

    # -- Public API methods --

    async def get_version(self) -> str:
        """Return the Gitea server orochi_version string."""
        data = await self._request("GET", "/orochi_version")
        return data.get("orochi_version", "")

    async def list_repos(self, org: str = "") -> list[dict]:
        """List repositories.  If *org* is given, list that org's repos."""
        if org:
            return await self._request("GET", f"/orgs/{org}/repos")
        return await self._request("GET", "/repos/search")

    async def create_repo(
        self, name: str, org: str = "", private: bool = False
    ) -> dict:
        """Create a new repository.  If *org* is given, create under that org."""
        payload: dict[str, Any] = {"name": name, "private": private}
        if org:
            return await self._request("POST", f"/orgs/{org}/repos", json_data=payload)
        return await self._request("POST", "/user/repos", json_data=payload)

    async def create_org(self, name: str, description: str = "") -> dict:
        """Create a new organisation."""
        payload: dict[str, Any] = {
            "username": name,
            "visibility": "public",
        }
        if description:
            payload["description"] = description
        return await self._request("POST", "/orgs", json_data=payload)

    async def create_issue(
        self,
        owner: str,
        repo: str,
        title: str,
        body: str = "",
        labels: list[str] | None = None,
    ) -> dict:
        """Create an issue on *owner/repo*."""
        payload: dict[str, Any] = {"title": title}
        if body:
            payload["body"] = body
        if labels:
            payload["labels"] = labels
        return await self._request(
            "POST", f"/repos/{owner}/{repo}/issues", json_data=payload
        )

    async def close_issue(self, owner: str, repo: str, issue_number: int) -> dict:
        """Close an issue by setting its state to 'closed'."""
        return await self._request(
            "PATCH",
            f"/repos/{owner}/{repo}/issues/{issue_number}",
            json_data={"state": "closed"},
        )

    async def list_issues(
        self, owner: str, repo: str, state: str = "open"
    ) -> list[dict]:
        """List issues on *owner/repo* filtered by *state*."""
        return await self._request("GET", f"/repos/{owner}/{repo}/issues?state={state}")

    async def add_comment(
        self, owner: str, repo: str, issue_number: int, body: str
    ) -> dict:
        """Add a comment to an issue."""
        return await self._request(
            "POST",
            f"/repos/{owner}/{repo}/issues/{issue_number}/comments",
            json_data={"body": body},
        )
