"""Claude Code statusline (claude-hud) parsing for context/quota/model.

Statusline format (claude-hud):
  [Opus 4.6 (1M context) | Max] ████░░░░░░ 39% | ███████░░░ 73% (1h 8m / 5h)
  █████░░░░░ 54% (5d 15h / 7d) | wyusuuke@gmail.com

Reference: https://github.com/jarrodwatts/claude-hud
Upstream claude-hud reads its numbers from Claude Code's native
statusline stdin JSON. Scraping the rendered bars is a downgrade from
that source, but we do it here because this script never has access to
the stdin payload Claude Code only hands to its registered statusline
command. The authoritative replacement lives in scitex-agent-container
(``scitex-agent-container status --json``).
"""

from __future__ import annotations

import re


def parse_statusline(orochi_pane_tail_block: str) -> dict:
    """Extract context_pct, quota_5h, quota_weekly, model, email from statusline.

    Returns a dict with keys:
      - statusline_context_pct: Optional[float]
      - quota_5h_pct: Optional[float]
      - quota_5h_remaining: str
      - quota_weekly_pct: Optional[float]
      - quota_weekly_remaining: str
      - orochi_statusline_model: str
      - account_email: str
    """
    out: dict = {
        "statusline_context_pct": None,
        "quota_5h_pct": None,
        "quota_5h_remaining": "",
        "quota_weekly_pct": None,
        "quota_weekly_remaining": "",
        "orochi_statusline_model": "",
        "account_email": "",
    }
    src = orochi_pane_tail_block or ""

    # Extract model from statusline: [Model Name (context) | Mode]
    m_model = re.search(r"\[([^\]]+)\]", src)
    if m_model:
        out["orochi_statusline_model"] = m_model.group(1).strip()

    # Extract account email
    m_email = re.search(r"([\w.+-]+@[\w.-]+\.\w+)", src)
    if m_email:
        out["account_email"] = m_email.group(1)

    # Extract percentages from statusline bars: ██░░ NN% (Xh Ym / 5h)
    pct_matches = re.findall(r"[█░▓▒]{2,}\s+(\d+)%(?:\s*\(([^)]+)\))?", src)
    # First bar = context, second = 5h quota, third = weekly quota
    if len(pct_matches) >= 1:
        out["statusline_context_pct"] = float(pct_matches[0][0])
    if len(pct_matches) >= 2:
        out["quota_5h_pct"] = float(pct_matches[1][0])
        out["quota_5h_remaining"] = pct_matches[1][1] if pct_matches[1][1] else ""
    if len(pct_matches) >= 3:
        out["quota_weekly_pct"] = float(pct_matches[2][0])
        out["quota_weekly_remaining"] = pct_matches[2][1] if pct_matches[2][1] else ""
    return out
