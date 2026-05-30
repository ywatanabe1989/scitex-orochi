"""Tests for scripts/server/scitex-smoke.py (#237 Part 2).

Tests the pure-logic helpers (error signal detection, report formatting)
without launching a real browser or hitting the network. Playwright
integration is tested separately in CI with the actual target.
"""

import importlib.util
import tempfile
import unittest
from pathlib import Path

_SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "server" / "scitex-smoke.py"


def _load_smoke():
    if not _SCRIPT.exists():
        return None
    spec = importlib.util.spec_from_file_location("scitex_smoke", _SCRIPT)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


_smoke = _load_smoke()


@unittest.skipIf(_smoke is None, "scitex-smoke.py not found")
class ErrorSignalTest(unittest.TestCase):
    """Verify that ERROR_SIGNALS do NOT false-positive on normal content."""

    def _page_content(self, path: str) -> bool:
        """Return True if a page with csrfmiddlewaretoken would fail."""
        content = '<input type="hidden" name="csrfmiddlewaretoken" value="abc123">'
        for sig in _smoke.ERROR_SIGNALS:
            if sig.lower() in content.lower():
                return True
        return False

    def test_csrfmiddlewaretoken_not_a_false_positive(self):
        self.assertFalse(self._page_content("/"))

    def test_real_traceback_detected(self):
        content = "Traceback (most recent call last):\n  File ...\nValueError: bad"
        detected = any(sig.lower() in content.lower() for sig in _smoke.ERROR_SIGNALS)
        self.assertTrue(detected)

    def test_django_500_page_detected(self):
        content = "<title>Server Error (500)</title>"
        detected = any(sig.lower() in content.lower() for sig in _smoke.ERROR_SIGNALS)
        self.assertTrue(detected)

    def test_django_url_patterns_error_detected(self):
        content = "Django tried these URL patterns in this order:"
        detected = any(sig.lower() in content.lower() for sig in _smoke.ERROR_SIGNALS)
        self.assertTrue(detected)

    def test_normal_page_no_detection(self):
        content = "<h1>Welcome to SciTeX</h1><p>Your research platform</p>"
        detected = any(sig.lower() in content.lower() for sig in _smoke.ERROR_SIGNALS)
        self.assertFalse(detected)


@unittest.skipIf(_smoke is None, "scitex-smoke.py not found")
class FormatReportTest(unittest.TestCase):
    def _result(self, label: str, ok: bool, status: int = 200, error: str = ""):
        return {"label": label, "url": f"https://scitex.ai/{label}/", "ok": ok,
                "status": status, "error": error}

    def test_all_pass_report_contains_pass(self):
        results = [
            self._result("home", True),
            self._result("landing", True),
            self._result("healthz", True),
            self._result("apps-home", True),
        ]
        report, all_ok = _smoke._format_report(results, True, "https://scitex.ai", 10.0, None)
        self.assertTrue(all_ok)
        self.assertIn("PASS", report)
        self.assertIn("✅", report)

    def test_failed_page_report_contains_fail(self):
        results = [
            self._result("home", False, 500, "HTTP 500"),
            self._result("landing", True),
            self._result("healthz", True),
            self._result("apps-home", True),
        ]
        report, all_ok = _smoke._format_report(results, True, "https://scitex.ai", 5.0, None)
        self.assertFalse(all_ok)
        self.assertIn("FAIL", report)
        self.assertIn("🚨", report)
        self.assertIn("home", report)
        self.assertIn("HTTP 500", report)

    def test_content_fail_shows_in_report(self):
        results = [self._result("home", True), self._result("landing", True),
                   self._result("healthz", True), self._result("apps-home", True)]
        report, all_ok = _smoke._format_report(results, False, "https://scitex.ai", 8.0, None)
        self.assertFalse(all_ok)
        self.assertIn("Content page", report)

    def test_screenshot_dir_shown_when_set(self):
        with tempfile.TemporaryDirectory() as tmp:
            screenshot_dir = Path(tmp)
            results = [self._result("home", True), self._result("landing", True),
                       self._result("healthz", True), self._result("apps-home", True)]
            report, _ = _smoke._format_report(results, True, "https://scitex.ai", 5.0, screenshot_dir)
            self.assertIn(str(screenshot_dir), report)

    def test_elapsed_time_in_report(self):
        results = [self._result("home", True), self._result("landing", True),
                   self._result("healthz", True), self._result("apps-home", True)]
        report, _ = _smoke._format_report(results, True, "https://scitex.ai", 14.2, None)
        self.assertIn("14.2s", report)


@unittest.skipIf(_smoke is None, "scitex-smoke.py not found")
class DryRunPostTest(unittest.TestCase):
    def test_dry_run_prints_and_returns_true(self):
        import io
        from contextlib import redirect_stdout

        buf = io.StringIO()
        with redirect_stdout(buf):
            result = _smoke._post_to_orochi("test message", dry_run=True)
        self.assertTrue(result)
        self.assertIn("dry-run", buf.getvalue())
        self.assertIn("test message", buf.getvalue())

    def test_no_token_skips_post(self):
        original = _smoke.OROCHI_TOKEN
        _smoke.OROCHI_TOKEN = ""
        try:
            result = _smoke._post_to_orochi("test", dry_run=False)
            self.assertFalse(result)
        finally:
            _smoke.OROCHI_TOKEN = original
