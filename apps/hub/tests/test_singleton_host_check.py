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

_SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "server" / "singleton-host-check.py"


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
        self.assertEqual(specs[0]["host_priority"], ["spartan", "ywata-note-win", "nas"])

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
        warnings = [{
            "agent": "proj-neurovista",
            "current_machine": "nas",
            "current_rank": 3,
            "preferred_host": "spartan",
            "preferred_rank": 1,
            "priority_list": ["spartan", "ywata-note-win", "nas"],
        }]
        report = _shc._format_report(warnings)
        self.assertIn("proj-neurovista", report)
        self.assertIn("spartan", report)
        self.assertIn("nas", report)
        self.assertIn("#250", report)
