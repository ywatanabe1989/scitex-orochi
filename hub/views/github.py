"""GitHub API proxy — avoids CORS / token exposure for private repos."""

import json
import os
import urllib.request

from django.http import JsonResponse
from django.views.decorators.http import require_GET


@require_GET
def github_issues(request):
    """GET /api/github/issues — proxy to GitHub API for ywatanabe1989/todo issues."""
    github_url = (
        "https://api.github.com/repos/ywatanabe1989/todo/issues?state=open&per_page=30"
    )
    headers = {
        "Accept": "application/vnd.github.v3+json",
        "User-Agent": "Orochi-Dashboard",
    }
    token = os.environ.get("GITHUB_TOKEN")
    if token:
        headers["Authorization"] = f"token {token}"

    try:
        req = urllib.request.Request(github_url, headers=headers)
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read())
            return JsonResponse(data, safe=False)
    except Exception as e:
        import traceback

        return JsonResponse(
            {"error": str(e), "traceback": traceback.format_exc()},
            status=502,
        )
