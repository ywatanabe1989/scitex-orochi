/**
 * GitHub issue title cache for #NNN decoration in agent messages.
 */
import { OROCHI_TOKEN, buildHttpBase } from "./config.js";

const _issueTitleCache: Map<string, string> = new Map();
let _issueCacheLastFetch = 0;
const _ISSUE_CACHE_TTL_MS = 5 * 60 * 1000;

export async function refreshIssueTitleCache(): Promise<void> {
  const now = Date.now();
  if (now - _issueCacheLastFetch < _ISSUE_CACHE_TTL_MS) return;
  try {
    const url = `${buildHttpBase()}/api/github/issues${OROCHI_TOKEN ? `?token=${OROCHI_TOKEN}&state=all` : "?state=all"}`;
    const resp = await fetch(url);
    if (!resp.ok) return;
    const issues = (await resp.json()) as Array<{
      number?: number;
      title?: string;
    }>;
    for (const i of issues) {
      if (i && i.number && i.title)
        _issueTitleCache.set(String(i.number), i.title);
    }
    _issueCacheLastFetch = now;
  } catch (_) {
    /* ignore — next message will retry */
  }
}

export function decorateIssueRefs(text: string): string {
  return text.replace(/(^|[^\w\/])#(\d+)\b/g, (match, lead, num) => {
    const title = _issueTitleCache.get(num);
    if (!title) return match;
    return `${lead}#${num} (${title})`;
  });
}
