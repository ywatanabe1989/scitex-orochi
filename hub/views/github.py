"""GitHub API proxy — avoids CORS / token exposure for private repos."""

import json
import os
import urllib.error
import urllib.request

from django.http import JsonResponse
from django.views.decorators.http import require_GET


@require_GET
def github_issues(request):
    """GET /api/github/issues — proxy to GitHub API for ywatanabe1989/todo issues."""
    token = os.environ.get("GITHUB_TOKEN")
    if not token:
        return JsonResponse(
            {"error": "GITHUB_TOKEN not configured", "code": "missing_token"},
            status=503,
        )

    github_url = (
        "https://api.github.com/repos/ywatanabe1989/todo/issues?state=open&per_page=30"
    )
    headers = {
        "Accept": "application/vnd.github.v3+json",
        "User-Agent": "Orochi-Dashboard",
        "Authorization": f"token {token}",
    }

    try:
        req = urllib.request.Request(github_url, headers=headers)
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read())
            return JsonResponse(data, safe=False)
    except urllib.error.HTTPError as e:
        return JsonResponse(
            {
                "error": f"GitHub API returned {e.code}: {e.reason}",
                "code": "github_error",
            },
            status=502,
        )
    except Exception as e:
        import traceback

        return JsonResponse(
            {
                "error": str(e),
                "code": "proxy_error",
                "traceback": traceback.format_exc(),
            },
            status=502,
        )
