#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# quota_scraper.py — Lane A quota scraping from ~/.claude/
# Outputs NDJSON compatible with fleet-health-daemon PR #147 §4.2 schema
# mamba-auth-manager-mba 2026-04-15

import glob
import json
import os
import socket
import time
from datetime import datetime, timedelta, timezone

HOST = socket.gethostname().split('.')[0]

def scrape_credentials():
    """Read subscription/rate-limit metadata from ~/.claude/.credentials.json"""
    cred_path = os.path.expanduser('~/.claude/.credentials.json')
    result = {
        'subscription_type': 'unknown',
        'rate_limit_tier': 'unknown',
        'token_expires_at': None,
        'token_valid': False,
    }
    try:
        d = json.load(open(cred_path))
        oauth = d.get('claudeAiOauth', {})
        result['subscription_type'] = oauth.get('subscriptionType', 'unknown')
        result['rate_limit_tier'] = oauth.get('rateLimitTier', 'unknown')
        expires_ms = oauth.get('expiresAt', 0)
        result['token_expires_at'] = datetime.fromtimestamp(
            expires_ms / 1000, tz=timezone.utc
        ).isoformat()
        result['token_valid'] = (expires_ms / 1000) > time.time()
    except Exception as e:
        result['error'] = str(e)
    return result


def scrape_usage(hours=5):
    """Read usage data from ~/.claude/projects/*/*.jsonl for the last N hours"""
    cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)

    total_input = 0
    total_output = 0
    total_cache_read = 0
    total_cache_create = 0
    calls = 0
    service_tiers = []

    for jsonl in glob.glob(os.path.expanduser('~/.claude/projects/*/*.jsonl')):
        try:
            with open(jsonl) as f:
                for line in f:
                    try:
                        e = json.loads(line)
                        ts_str = e.get('timestamp', '')
                        if not ts_str:
                            continue
                        ts = datetime.fromisoformat(ts_str.replace('Z', '+00:00'))
                        if ts < cutoff:
                            continue
                        msg = e.get('message', {})
                        usage = msg.get('usage', {})
                        if usage:
                            calls += 1
                            total_input += usage.get('input_tokens', 0)
                            total_output += usage.get('output_tokens', 0)
                            total_cache_read += usage.get('cache_read_input_tokens', 0)
                            total_cache_create += usage.get('cache_creation_input_tokens', 0)
                        st = msg.get('service_tier')
                        if st:
                            service_tiers.append(st)
                    except Exception:
                        pass
        except Exception:
            pass

    return {
        'session_calls_5h': calls,
        'session_output_tokens_5h': total_output,
        'session_cache_read_5h': total_cache_read,
        'session_cache_create_5h': total_cache_create,
        'service_tier_latest': service_tiers[-1] if service_tiers else 'unknown',
    }


def main():
    now = datetime.now(timezone.utc)
    creds = scrape_credentials()
    usage = scrape_usage(hours=5)

    record = {
        'ts': now.isoformat(),
        'host': HOST,
        **creds,
        **usage,
    }
    print(json.dumps(record))


if __name__ == '__main__':
    main()
