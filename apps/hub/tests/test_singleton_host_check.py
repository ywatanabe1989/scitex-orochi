"""Tests for scripts/server/singleton-host-check.py (#250 Option C).

Loads the script as a module and tests:
1. YAML spec collection with multi-host lists.
2. Machine map and online-machines computation from agent registry data.
3. check_placements logic — on top host, on wrong host, higher host alive/down.
4. Format report.
"""

import importlib.util
import tempfile
import unittest
from pathlib import Path

# Tests live at apps/hub/tests/test_singleton_host_check.py. parents:
#   parents[0] = apps/hub/tests
#   parents[1] = apps/hub
#   parents[2] = apps
#   parents[3] = <repo-root>  ← script lives at repo-root/scripts/server/
# The original ``parents[2]`` was correct under the pre-ADR-0002 layout
# (hub at repo root); commit b059a14 moved hub under apps/ but missed
# this path-resolution update, so the 18 tests had been silently
# ``skipped 'singleton-host-check.py not found'`` ever since.
_REPO_ROOT = Path(__file__).resolve().parents[3]
_SCRIPT = _REPO_ROOT / "scripts" / "server" / "singleton-host-check.py"


def _load_shc():
    if not _SCRIPT.exists():
        return None
    spec = importlib.util.spec_from_file_location("shc", _SCRIPT)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


_shc = _load_shc()


def _write_spec(directory: Path, agent_name: str, hosts: list[str]) -> None:
    agent_dir = directory / agent_name
    agent_dir.mkdir(parents=True, exist_ok=True)
    content = "name: {}\nhost:\n".format(agent_name)
    for h in hosts:
        content += f"  - {h}\n"
    (agent_dir / "spec.yaml").write_text(content)


@unittest.skipIf(_shc is None, "singleton-host-check.py not found")
class CollectSpecsTest(unittest.TestCase):
    def test_multi_host_spec_collected(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp)
            _write_spec(p, "proj-neurovista", ["spartan", "ywata-note-win", "nas"])
            specs = _shc._collect_specs(p)
        self.assertEqual(len(specs), 1)
        self.assertEqual(specs[0]["name"], "proj-neurovista")
        self.assertEqual(
            specs[0]["host_priority"], ["spartan", "ywata-note-win", "nas"]
        )

    def test_single_host_spec_skipped(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp)
            _write_spec(p, "proj-single", ["spartan"])
            specs = _shc._collect_specs(p)
        self.assertEqual(specs, [])

    def test_no_host_spec_skipped(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp)
            agent_dir = p / "proj-nohost"
            agent_dir.mkdir()
            (agent_dir / "spec.yaml").write_text("name: proj-nohost\n")
            specs = _shc._collect_specs(p)
        self.assertEqual(specs, [])

    def test_missing_dir_returns_empty(self):
        specs = _shc._collect_specs(Path("/nonexistent/dir"))
        self.assertEqual(specs, [])

    def test_multiple_specs_collected(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp)
            _write_spec(p, "proj-a", ["spartan", "nas"])
            _write_spec(p, "proj-b", ["mba", "spartan", "nas"])
            specs = _shc._collect_specs(p)
        self.assertEqual(len(specs), 2)
        names = {s["name"] for s in specs}
        self.assertEqual(names, {"proj-a", "proj-b"})


@unittest.skipIf(_shc is None, "singleton-host-check.py not found")
class BuildMachineMapTest(unittest.TestCase):
    def _agent(self, name, machine, liveness="online"):
        return {"name": name, "machine": machine, "liveness": liveness}

    def test_live_agent_mapped(self):
        agents = [self._agent("proj-neurovista", "spartan")]
        result = _shc._build_machine_map(agents)
        self.assertEqual(result["proj-neurovista"], "spartan")

    def test_offline_agent_not_mapped(self):
        agents = [self._agent("proj-x", "nas", liveness="offline")]
        result = _shc._build_machine_map(agents)
        self.assertNotIn("proj-x", result)

    def test_idle_agent_mapped(self):
        agents = [self._agent("proj-y", "mba", liveness="idle")]
        result = _shc._build_machine_map(agents)
        self.assertIn("proj-y", result)

    def test_online_machines(self):
        agents = [
            self._agent("a", "spartan", "online"),
            self._agent("b", "nas", "offline"),
            self._agent("c", "mba", "idle"),
        ]
        result = _shc._online_machines(agents)
        self.assertIn("spartan", result)
        self.assertIn("mba", result)
        self.assertNotIn("nas", result)


@unittest.skipIf(_shc is None, "singleton-host-check.py not found")
class CheckPlacementsTest(unittest.TestCase):
    def _spec(self, name, hosts):
        return {"name": name, "host_priority": hosts, "spec_path": "/fake"}

    def test_on_top_priority_host_no_warning(self):
        specs = [self._spec("proj-a", ["spartan", "nas"])]
        machine_map = {"proj-a": "spartan"}
        online = {"spartan", "nas"}
        warnings = _shc.check_placements(specs, machine_map, online)
        self.assertEqual(warnings, [])

    def test_on_lower_host_higher_alive_warns(self):
        specs = [self._spec("proj-neurovista", ["spartan", "nas"])]
        machine_map = {"proj-neurovista": "nas"}
        online = {"spartan", "nas"}
        warnings = _shc.check_placements(specs, machine_map, online)
        self.assertEqual(len(warnings), 1)
        w = warnings[0]
        self.assertEqual(w["agent"], "proj-neurovista")
        self.assertEqual(w["preferred_host"], "spartan")
        self.assertEqual(w["preferred_rank"], 1)
        self.assertEqual(w["current_rank"], 2)

    def test_on_lower_host_higher_offline_no_warning(self):
        specs = [self._spec("proj-neurovista", ["spartan", "nas"])]
        machine_map = {"proj-neurovista": "nas"}
        online = {"nas"}  # spartan is down
        warnings = _shc.check_placements(specs, machine_map, online)
        self.assertEqual(warnings, [])

    def test_agent_not_in_registry_skipped(self):
        specs = [self._spec("proj-x", ["spartan", "nas"])]
        machine_map = {}
        online = {"spartan", "nas"}
        warnings = _shc.check_placements(specs, machine_map, online)
        self.assertEqual(warnings, [])

    def test_machine_not_in_priority_list_reports_last_rank(self):
        specs = [self._spec("proj-a", ["spartan", "nas"])]
        machine_map = {"proj-a": "mba"}  # mba not in list
        online = {"spartan", "nas", "mba"}
        warnings = _shc.check_placements(specs, machine_map, online)
        # mba is rank len(list) = 2 (after the 2 known hosts)
        self.assertEqual(len(warnings), 1)
        self.assertEqual(warnings[0]["preferred_host"], "spartan")

    def test_reports_highest_available_preferred_host(self):
        specs = [self._spec("proj-a", ["spartan", "mba", "nas"])]
        machine_map = {"proj-a": "nas"}
        # spartan is down, mba is up
        online = {"mba", "nas"}
        warnings = _shc.check_placements(specs, machine_map, online)
        self.assertEqual(len(warnings), 1)
        self.assertEqual(warnings[0]["preferred_host"], "mba")
        self.assertEqual(warnings[0]["preferred_rank"], 2)

    def test_fqdn_stripping(self):
        specs = [self._spec("proj-a", ["spartan", "nas"])]
        # machine might be reported as "spartan.local" or "user@spartan"
        machine_map = {"proj-a": "user@nas.local"}
        online = {"spartan", "nas.local"}
        warnings = _shc.check_placements(specs, machine_map, online)
        self.assertEqual(len(warnings), 1)


@unittest.skipIf(_shc is None, "singleton-host-check.py not found")
class FormatReportTest(unittest.TestCase):
    def test_empty_warnings_returns_empty(self):
        self.assertEqual(_shc._format_report([]), "")

    def test_warning_appears_in_report(self):
        warnings = [
            {
                "agent": "proj-neurovista",
                "current_machine": "nas",
                "current_rank": 3,
                "preferred_host": "spartan",
                "preferred_rank": 1,
                "priority_list": ["spartan", "ywata-note-win", "nas"],
            }
        ]
        report = _shc._format_report(warnings)
        self.assertIn("proj-neurovista", report)
        self.assertIn("spartan", report)
        self.assertIn("nas", report)
        self.assertIn("#250", report)


# ---------------------------------------------------------------------------
# DM-healer dispatch tests (#250 Optional follow-up)
# ---------------------------------------------------------------------------


def _sample_warning() -> dict:
    return {
        "agent": "proj-neurovista",
        "current_machine": "nas",
        "current_rank": 3,
        "preferred_host": "spartan",
        "preferred_rank": 1,
        "priority_list": ["spartan", "ywata-note-win", "nas"],
    }


@unittest.skipIf(_shc is None, "singleton-host-check.py not found")
class ResolveHealerNameTest(unittest.TestCase):
    def test_default_template_head_dash_host(self):
        self.assertEqual(
            _shc._resolve_healer_name("spartan", "head-{host}"),
            "head-spartan",
        )

    def test_strips_user_at_prefix(self):
        self.assertEqual(
            _shc._resolve_healer_name("ywatanabe@spartan", "head-{host}"),
            "head-spartan",
        )

    def test_strips_fqdn_suffix(self):
        self.assertEqual(
            _shc._resolve_healer_name("spartan.unimelb.edu.au", "head-{host}"),
            "head-spartan",
        )

    def test_custom_template(self):
        self.assertEqual(
            _shc._resolve_healer_name("nas", "caduceus@{host}"),
            "caduceus@nas",
        )

    def test_bad_placeholder_raises(self):
        # Template referencing an unknown placeholder must NOT silently
        # produce a malformed name — fail loud so the operator notices.
        with self.assertRaises(KeyError):
            _shc._resolve_healer_name("spartan", "{role}-{host}")


@unittest.skipIf(_shc is None, "singleton-host-check.py not found")
class DmChannelNameTest(unittest.TestCase):
    def test_canonical_form_sorted(self):
        # Sorted-principal-key shape (spec v3 §2.3): regardless of which
        # side is the sender, the channel name is identical so the hub's
        # ``_ensure_dm_channel`` get-or-create is idempotent.
        a = _shc._dm_channel_name("singleton-host-check", "head-spartan")
        b = _shc._dm_channel_name("head-spartan", "singleton-host-check")
        self.assertEqual(a, b)
        self.assertTrue(a.startswith("dm:"))
        self.assertIn("agent:head-spartan", a)
        self.assertIn("agent:singleton-host-check", a)

    def test_principals_sorted_alphabetically(self):
        # Sanity-check the exact canonical shape so spec drift is caught.
        name = _shc._dm_channel_name("zeta", "alpha")
        self.assertEqual(name, "dm:agent:alpha|agent:zeta")


@unittest.skipIf(_shc is None, "singleton-host-check.py not found")
class FormatDmForHealerTest(unittest.TestCase):
    def test_includes_agent_and_action(self):
        text = _shc._format_dm_for_healer(_sample_warning())
        self.assertIn("proj-neurovista", text)
        self.assertIn("spartan", text)
        self.assertIn("nas", text)
        self.assertIn("sac singleton-reconcile --execute", text)
        self.assertIn("#250", text)

    def test_priority_list_rendered_arrow_separated(self):
        text = _shc._format_dm_for_healer(_sample_warning())
        self.assertIn("spartan > ywata-note-win > nas", text)


@unittest.skipIf(_shc is None, "singleton-host-check.py not found")
class DispatchDmWarningsTest(unittest.TestCase):
    def test_dispatches_one_per_warning_with_resolved_healer(self):
        captured: list[tuple[str, str]] = []

        def fake_post(healer: str, text: str) -> bool:
            captured.append((healer, text))
            return True

        w1 = _sample_warning()
        w2 = {**_sample_warning(), "agent": "proj-other", "preferred_host": "mba"}
        results = _shc.dispatch_dm_warnings(
            [w1, w2], template="head-{host}", post=fake_post
        )

        self.assertEqual(len(captured), 2)
        self.assertEqual(captured[0][0], "head-spartan")
        self.assertEqual(captured[1][0], "head-mba")
        # Every result records its outcome so operators can see at a
        # glance which DMs landed.
        self.assertTrue(all(r["ok"] for r in results))
        self.assertEqual(
            [r["agent"] for r in results], ["proj-neurovista", "proj-other"]
        )
        self.assertEqual([r["healer"] for r in results], ["head-spartan", "head-mba"])

    def test_post_failure_recorded_in_results(self):
        def fake_post(healer: str, text: str) -> bool:
            return False  # simulate hub unreachable

        results = _shc.dispatch_dm_warnings(
            [_sample_warning()], template="head-{host}", post=fake_post
        )
        self.assertEqual(
            results,
            [{"agent": "proj-neurovista", "healer": "head-spartan", "ok": False}],
        )

    def test_template_resolution_failure_skips_post(self):
        calls: list[tuple[str, str]] = []

        def fake_post(healer: str, text: str) -> bool:
            calls.append((healer, text))
            return True

        # Bad template — {role} is not defined → KeyError → no post call.
        results = _shc.dispatch_dm_warnings(
            [_sample_warning()], template="{role}-{host}", post=fake_post
        )
        self.assertEqual(calls, [])
        self.assertEqual(len(results), 1)
        self.assertFalse(results[0]["ok"])
        self.assertIsNone(results[0]["healer"])


@unittest.skipIf(_shc is None, "singleton-host-check.py not found")
class PostDmToHealerUrlShapeTest(unittest.TestCase):
    """Verify ``_post_dm_to_healer`` builds the correct request shape.

    Uses ``unittest.mock.patch`` against the helper module's local
    ``urllib.request.urlopen`` import — the helper imports inside the
    function to keep top-level imports stdlib-only, so the patch
    target is the ``urllib.request`` module rather than a re-bound
    name on ``_shc`` itself.
    """

    def test_post_url_and_body_shape(self):
        import urllib.request as _ur
        from unittest import mock

        # Force-known env values for deterministic URL/body assertions.
        captured: dict[str, object] = {}

        class _FakeResp:
            status = 200

            def __enter__(self):
                return self

            def __exit__(self, *_a):
                return False

        def _fake_urlopen(req, timeout=10):
            captured["url"] = req.full_url
            captured["data"] = req.data
            captured["method"] = req.get_method()
            captured["content_type"] = req.headers.get("Content-type")
            return _FakeResp()

        # Patch the env-driven module-level constants on the helper
        # module so the URL is fully deterministic, then patch urlopen
        # at the urllib.request level (helper does
        # ``import urllib.request`` inside the function body).
        with (
            mock.patch.object(_shc._dm, "HUB_URL", "https://hub.test"),
            mock.patch.object(_shc._dm, "HUB_TOKEN", "wks_TESTTOKEN"),
            mock.patch.object(_shc._dm, "WORKSPACE_SLUG", "fleet"),
            mock.patch.object(_shc._dm, "SCRIPT_AGENT_NAME", "singleton-host-check"),
            mock.patch.object(_ur, "urlopen", _fake_urlopen),
        ):
            ok = _shc._post_dm_to_healer("head-spartan", "hello")

        self.assertTrue(ok)
        self.assertEqual(captured["method"], "POST")
        self.assertEqual(captured["content_type"], "application/json")
        # URL — workspace-scoped messages endpoint with both query auth
        # keys present so the eventual token-auth landing on
        # ``api_messages`` can flip on without touching this caller.
        self.assertIn(
            "https://hub.test/api/workspace/fleet/messages/",
            captured["url"],
        )
        self.assertIn("token=wks_TESTTOKEN", captured["url"])
        self.assertIn("agent=singleton-host-check", captured["url"])
        # Body — canonical DM channel + the supplied text. JSON body
        # also carries the token for symmetry with the legacy
        # ``_post_to_heads`` payload shape.
        import json as _json

        body = _json.loads(captured["data"])
        self.assertEqual(body["text"], "hello")
        self.assertEqual(body["token"], "wks_TESTTOKEN")
        self.assertEqual(
            body["channel"],
            "dm:agent:head-spartan|agent:singleton-host-check",
        )

    def test_post_returns_false_on_urlopen_exception(self):
        import urllib.request as _ur
        from unittest import mock

        def _boom(req, timeout=10):
            raise OSError("hub unreachable")

        with mock.patch.object(_ur, "urlopen", _boom):
            ok = _shc._post_dm_to_healer("head-spartan", "hello")
        # Hub-unreachable is logged (not raised) so the cron loop keeps
        # going; the return value is the signal the caller checks.
        self.assertFalse(ok)
