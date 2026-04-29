"""Tests for scripts/server/observer-tsv-scan.py.

Loads the script as a module and tests:
1. TSV parsing and nginx row extraction.
2. Consecutive-spike detection (trigger / no-trigger).
3. State file cooldown logic.
4. Orochi post is suppressed in dry-run mode.
"""

import importlib.util
import json
import tempfile
import time
from pathlib import Path

from django.test import TestCase

# Load the script as a module (not importable via normal package path)
_SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "server" / "observer-tsv-scan.py"


def _load_obs():
    if not _SCRIPT.exists():
        return None
    spec = importlib.util.spec_from_file_location("obs_scan", _SCRIPT)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


_obs = _load_obs()


def _make_tsv(rows_5xx: list[float], rows_504: list[float] | None = None) -> Path:
    """Write a temporary TSV with _nginx rows for each given metric value."""
    if rows_504 is None:
        rows_504 = [0.0] * len(rows_5xx)
    header = (
        "ts_utc\tcontainer\tcpu_pct\tmem_mib\tmem_anon_mib\tmem_file_mib\t"
        "cg_events_max\tmem_psi_some_us\tmem_psi_full_us\tcpu_psi_some_us\t"
        "threads\test_conns\tnginx_req_1m\tnginx_5xx_1m\tnginx_504_1m\tnginx_499_1m"
    )
    lines = [header]
    for i, (v5xx, v504) in enumerate(zip(rows_5xx, rows_504)):
        ts = f"2026-04-29T10:{i:02d}:00Z"
        lines.append(f"{ts}\t_nginx\t\t\t\t\t\t\t\t\t\t\t100\t{v5xx}\t{v504}\t0")
    tf = tempfile.NamedTemporaryFile(mode="w", suffix=".tsv", delete=False)
    tf.write("\n".join(lines))
    tf.close()
    return Path(tf.name)


import unittest


@unittest.skipIf(_obs is None, "observer-tsv-scan.py not found")
class ObsTsvParseTest(TestCase):
    def test_parse_nginx_rows_returns_only_nginx(self):
        tsv = _make_tsv([5, 5, 5])
        rows = _obs._parse_nginx_rows(tsv)
        self.assertGreater(len(rows), 0)
        for r in rows:
            self.assertIn("_nginx", r["container"])
        tsv.unlink()

    def test_parse_missing_file_returns_empty(self):
        rows = _obs._parse_nginx_rows(Path("/nonexistent/path.tsv"))
        self.assertEqual(rows, [])

    def test_to_float_empty_is_zero(self):
        self.assertEqual(_obs._to_float(""), 0.0)
        self.assertEqual(_obs._to_float(None), 0.0)
        self.assertEqual(_obs._to_float("3.5"), 3.5)


@unittest.skipIf(_obs is None, "observer-tsv-scan.py not found")
class ObsTsvSpikeDetectionTest(TestCase):
    def _rows(self, vals_5xx, vals_504=None):
        if vals_504 is None:
            vals_504 = [0.0] * len(vals_5xx)
        return [
            {"ts_utc": f"T{i}", "nginx_5xx_1m": str(v), "nginx_504_1m": str(p)}
            for i, (v, p) in enumerate(zip(vals_5xx, vals_504))
        ]

    def test_spike_5xx_triggers(self):
        # 4 consecutive minutes at 5xx=25 (>20 threshold)
        rows = self._rows([5, 5, 5, 5, 5, 25, 25, 25, 25])
        triggered, offending = _obs._check_consecutive(rows, 3, 10, 20)
        self.assertTrue(triggered)
        self.assertEqual(len(offending), 3)

    def test_spike_504_triggers(self):
        rows = self._rows([0]*5 + [0]*3, [0]*5 + [15, 15, 15])
        triggered, offending = _obs._check_consecutive(rows, 3, 10, 20)
        self.assertTrue(triggered)

    def test_below_threshold_no_trigger(self):
        rows = self._rows([5, 5, 5, 5, 5, 5])
        triggered, _ = _obs._check_consecutive(rows, 3, 10, 20)
        self.assertFalse(triggered)

    def test_interrupted_run_no_trigger(self):
        # spike interrupted: 25, 5 (reset), 25, 25 — only 2 consecutive
        rows = self._rows([25, 5, 25, 25])
        triggered, _ = _obs._check_consecutive(rows, 3, 10, 20)
        self.assertFalse(triggered)

    def test_exactly_window_size_triggers(self):
        rows = self._rows([25, 25, 25])
        triggered, offending = _obs._check_consecutive(rows, 3, 10, 20)
        self.assertTrue(triggered)
        self.assertEqual(len(offending), 3)

    def test_empty_rows_no_trigger(self):
        triggered, _ = _obs._check_consecutive([], 3, 10, 20)
        self.assertFalse(triggered)


@unittest.skipIf(_obs is None, "observer-tsv-scan.py not found")
class ObsTsvCooldownTest(TestCase):
    def test_fresh_state_no_cooldown(self):
        self.assertFalse(_obs._cooldown_active({}))

    def test_recent_alert_cooldown_active(self):
        state = {"last_alert_ts": time.time() - 60}  # 60s ago < 3600s
        self.assertTrue(_obs._cooldown_active(state))

    def test_old_alert_cooldown_expired(self):
        state = {"last_alert_ts": time.time() - 7200}  # 2 hours ago
        self.assertFalse(_obs._cooldown_active(state))


@unittest.skipIf(_obs is None, "observer-tsv-scan.py not found")
class ObsTsvDryRunTest(TestCase):
    def test_dry_run_no_post(self):
        """dry_run=True should print but not call urlopen."""
        import io
        from contextlib import redirect_stdout

        buf = io.StringIO()
        with redirect_stdout(buf):
            result = _obs._post_to_orochi("test alert", dry_run=True)
        self.assertTrue(result)
        self.assertIn("dry-run", buf.getvalue())
