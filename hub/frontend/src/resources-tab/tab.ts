// @ts-nocheck
import { apiUrl, escapeHtml, getAgentColor, HOSTNAME_ALIASES } from "../app/utils";
import { syncHostHover } from "../connectivity-map";
import { addTag } from "../filter/state";
import { _applyMachinesViewVisibility, _machineIcons, _wireMachinesControls, donutHtml, hideMachineTooltip, moveMachineTooltip, resourceData, setMachineIcon, showMachineTooltip } from "./panel";
import { activeTab } from "../tabs";

/* Resource Monitor Panel + Resources Tab — part 2: renderers, card
 * builder, machine aliases, fetchResources. Split from resources-tab.js
 * (697 lines) — depends on resources-tab/panel.js (resourceData,
 * _machineIcons, donutHtml, _wireMachinesControls,
 * _applyMachinesViewVisibility, showMachineTooltip, moveMachineTooltip,
 * hideMachineTooltip, setMachineIcon). */
/* globals: escapeHtml, activeTab, addTag, apiUrl, getAgentColor,
   syncHostHover, resourceData, _machineIcons, donutHtml,
   _wireMachinesControls, _applyMachinesViewVisibility,
   showMachineTooltip, moveMachineTooltip, hideMachineTooltip,
   setMachineIcon */

export function renderResources() {
  var msgInput = document.getElementById("msg-input");
  var inputHasFocus = msgInput && document.activeElement === msgInput;
  var savedStart = inputHasFocus ? msgInput.selectionStart : 0;
  var savedEnd = inputHasFocus ? msgInput.selectionEnd : 0;
  var container = document.getElementById("resources");
  var keys = Object.keys(resourceData);
  var cEl = document.getElementById("sidebar-count-machines");
  if (cEl) cEl.textContent = keys.length ? "(" + keys.length + ")" : "";
  if (keys.length === 0) {
    container.innerHTML = '<p class="empty-notice">No reports yet</p>';
    if (inputHasFocus && document.activeElement !== msgInput) {
      msgInput.focus();
      try {
        msgInput.setSelectionRange(savedStart, savedEnd);
      } catch (_) {}
    }
    return;
  }
  /* Sidebar machines = one-line rows (ywatanabe 2026-04-19: "name only
   * and connectivity and pin; X%, Y/Z GB, A/B TB"). Connectivity dot
   * on the left; host name color-coded by its own hash; compact chips
   * for CPU% / Mem Y/Z GB / Disk%. Total disk GB/TB isn't pushed by
   * heartbeat yet, so disk stays percent-only for now. */
  container.innerHTML = keys
    .map(function (k) {
      var d = resourceData[k];
      var health = (d.health && d.health.status) || "healthy";
      var healthy = health === "healthy";
      var cpu = (d.cpu && d.cpu.percent) || 0;
      var memPct = (d.memory && d.memory.percent) || 0;
      var memTotalMb =
        (d.memory && d.memory.total_mb) ||
        (d._metrics && d._metrics.mem_total_mb) ||
        0;
      var memStr = "—";
      if (memTotalMb > 0) {
        var memTotalGb = memTotalMb / 1024;
        var memUsedGb = (memTotalMb * memPct) / 100 / 1024;
        memStr = memUsedGb.toFixed(1) + "/" + memTotalGb.toFixed(0) + "GB";
      } else if (memPct > 0) {
        memStr = memPct.toFixed(0) + "%";
      }
      var diskPct = 0;
      if (d.disk) {
        var dk = Object.keys(d.disk)[0];
        if (dk) diskPct = d.disk[dk].percent || 0;
      }
      var color =
        typeof getAgentColor === "function" ? getAgentColor(k) : "#e6e6e6";
      var gpuStr = "";
      if (d.gpu && d.gpu.length > 0) {
        gpuStr =
          ' <span class="res-chip" title="GPU utilization">' +
          Math.round(d.gpu[0].utilization_percent || 0) +
          "% gpu</span>";
      }
      var slurmStr = "";
      if (d.slurm && d.slurm.total_jobs > 0) {
        slurmStr =
          ' <span class="res-chip" title="SLURM jobs">' +
          d.slurm.total_jobs +
          " jobs</span>";
      }
      /* #284 Machine card order: [icon] [star] [LED] [<host-label>
       * (<hostname-canonical>)] [metrics].
       *
       * The single LED replaces the old leading connection dot; it
       * sits BETWEEN star and the name so the icon/star columns line
       * up with agent + DM sidebar rows. Machines don't have the
       * 4-LED liveness model agents do (no WS handshake / ping / pane
       * state / nonce-echo signal is meaningful for a bare host), so
       * we keep a single health LED driven by the heartbeat health
       * status. Metrics (CPU / Mem / Disk / GPU / SLURM) stay inline
       * where horizontal space allows — the full metric breakdown is
       * always available on the hover tooltip regardless. */
      var mStarred = !!(d && d._starred);
      return (
        '<div class="res-card res-card-compact" data-machine="' +
        escapeHtml(k) +
        '" title="' +
        escapeHtml(k) +
        (d._status ? " · " + d._status : "") +
        '">' +
        '<span class="res-machine-icon" title="right-click to change" aria-hidden="true">' +
        (_machineIcons[k] || "\uD83D\uDDA5\uFE0F") +
        "</span>" +
        '<span class="res-star ' +
        (mStarred ? "res-star-on" : "res-star-off") +
        '" data-machine="' +
        escapeHtml(k) +
        '" title="' +
        (mStarred ? "Unstar machine" : "Star machine (float to top)") +
        '">' +
        (mStarred ? "\u2605" : "\u2606") +
        "</span>" +
        '<span class="res-conn res-conn-' +
        (healthy ? "ok" : "stale") +
        '" title="' +
        (healthy ? "Host healthy" : "Host stale / degraded") +
        '"></span>' +
        /* Spec: machine: [icon] [star] [LED] [<host-label>
         * (<hostname-canonical>)] — show the canonical FQDN in
         * parentheses after the short label when it differs
         * meaningfully from the label. Uses the same collapse rules
         * as the agents-tab Machine detail view (.local /
         * .localdomain suffixes aren't "different"). */
        '<span class="res-host-name" style="color:' +
        color +
        '">' +
        escapeHtml(k) +
        (function () {
          var fqdn =
            (d && (d._fqdn || d._machineFqdn || d.hostname_canonical)) || "";
          if (!fqdn || fqdn === k) return "";
          var redundant = [".local", ".localdomain", ".lan", ".home.arpa"];
          for (var _r = 0; _r < redundant.length; _r++) {
            if (fqdn === k + redundant[_r]) return "";
          }
          return (
            ' <span class="res-host-fqdn" title="canonical hostname">(' +
            escapeHtml(fqdn) +
            ")</span>"
          );
        })() +
        "</span>" +
        '<span class="res-metrics">' +
        '<span class="res-chip" title="CPU %">' +
        Math.round(cpu) +
        "%</span>" +
        '<span class="res-chip" title="Mem used/total">' +
        escapeHtml(memStr) +
        "</span>" +
        '<span class="res-chip" title="Disk %">' +
        Math.round(diskPct) +
        "%</span>" +
        gpuStr +
        slurmStr +
        "</span>" +
        "</div>"
      );
    })
    .join("");
  /* todo#86: hover tooltip on sidebar rows with CPU/RAM/GPU/VRAM/Disk. */
  container.querySelectorAll(".res-card[data-machine]").forEach(function (el) {
    var host = el.getAttribute("data-machine");
    el.addEventListener("mouseenter", function (ev) {
      showMachineTooltip(host, ev);
    });
    el.addEventListener("mousemove", moveMachineTooltip);
    el.addEventListener("mouseleave", hideMachineTooltip);
    /* Right-click → emoji picker to customize the machine icon.
     * Stored in localStorage so each user's pick survives reloads
     * without a new Django model (TODO.md Entity Consistency). */
    el.addEventListener("contextmenu", function (ev) {
      ev.preventDefault();
      hideMachineTooltip();
      if (typeof window.openEmojiPicker === "function") {
        window.openEmojiPicker(function (emoji) {
          setMachineIcon(host, emoji);
        });
      }
    });
  });
  if (inputHasFocus && document.activeElement !== msgInput) {
    msgInput.focus();
    try {
      msgInput.setSelectionRange(savedStart, savedEnd);
    } catch (_) {}
  }
}

export function renderResourcesTab() {
  var msgInput = document.getElementById("msg-input");
  var inputHasFocus = msgInput && document.activeElement === msgInput;
  var savedStart = inputHasFocus ? msgInput.selectionStart : 0;
  var savedEnd = inputHasFocus ? msgInput.selectionEnd : 0;
  _wireMachinesControls();
  _applyMachinesViewVisibility();
  var grid = document.getElementById("resources-grid");
  var keys = Object.keys(resourceData);
  if (keys.length === 0) {
    grid.innerHTML = '<p class="empty-notice">No resource reports yet.</p>';
    if (inputHasFocus && document.activeElement !== msgInput) {
      msgInput.focus();
      try {
        msgInput.setSelectionRange(savedStart, savedEnd);
      } catch (_) {}
    }
    return;
  }
  grid.innerHTML = keys.map(buildResourceCard).join("");
  grid.querySelectorAll(".res-card[data-host-name]").forEach(function (el) {
    el.addEventListener("click", function () {
      addTag("host", el.getAttribute("data-host-name"));
    });
    /* todo#51: bidirectional hover-sync with SSH-mesh + activity cards. */
    el.addEventListener("mouseenter", function () {
      if (typeof syncHostHover === "function")
        syncHostHover(el.getAttribute("data-host-name"), true);
    });
    el.addEventListener("mouseleave", function () {
      if (typeof syncHostHover === "function")
        syncHostHover(el.getAttribute("data-host-name"), false);
    });
  });
  if (inputHasFocus && document.activeElement !== msgInput) {
    msgInput.focus();
    try {
      msgInput.setSelectionRange(savedStart, savedEnd);
    } catch (_) {}
  }
}

export function buildResourceCard(k) {
  var d = resourceData[k];
  var health = (d.health && d.health.status) || "healthy";
  var cpu = (d.cpu && d.cpu.percent) || 0;
  var mem = (d.memory && d.memory.percent) || 0;
  var diskPct = 0;
  if (d.disk) {
    var dk = Object.keys(d.disk)[0];
    if (dk) diskPct = d.disk[dk].percent || 0;
  }
  var subtitleParts = [];
  if (d._machine) subtitleParts.push(escapeHtml(d._machine));
  if (d._status) {
    subtitleParts.push(escapeHtml(d._status));
  }
  var subtitleHtml =
    subtitleParts.length > 0
      ? '<div class="res-meta">' + subtitleParts.join(" &middot; ") + "</div>"
      : "";
  var loadHtml = "";
  if (d._loadAvg) {
    loadHtml =
      '<div class="res-meta">Load avg: ' +
      d._loadAvg
        .map(function (v) {
          return v.toFixed(2);
        })
        .join(" / ") +
      "</div>";
  }
  var memDetail = "";
  if (d._memTotalMb) {
    var usedMb = Math.round(d._memTotalMb - (d._memFreeMb || 0));
    memDetail =
      '<div class="res-meta">' + usedMb + " / " + d._memTotalMb + " MB</div>";
  }
  var cpuInfo = "";
  if (d._cpuCount) {
    cpuInfo =
      '<div class="res-meta">' +
      d._cpuCount +
      " cores" +
      (d._cpuModel ? " &middot; " + escapeHtml(d._cpuModel) : "") +
      "</div>";
  }
  var donutRow =
    '<div class="res-donut-row">' +
    donutHtml("CPU", cpu) +
    donutHtml("Mem", mem) +
    donutHtml("Disk", diskPct) +
    "</div>";
  var html =
    '<div class="res-card" data-host-name="' +
    escapeHtml(k) +
    '">' +
    '<div class="res-host"><span class="res-dot"></span>' +
    escapeHtml(k) +
    "</div>" +
    subtitleHtml +
    donutRow;
  if (d.gpu && d.gpu.length > 0) {
    var gpuRow = '<div class="res-donut-row">';
    d.gpu.forEach(function (g, i) {
      gpuRow += donutHtml(
        "GPU" + (d.gpu.length > 1 ? i + 1 : ""),
        g.utilization_percent || 0,
      );
    });
    gpuRow += "</div>";
    html += gpuRow;
  }
  html += loadHtml + cpuInfo + memDetail;
  if (d.subagents !== undefined) {
    html += '<div class="res-meta">Subagents: ' + d.subagents + "</div>";
  }
  if (d.docker && d.docker.containers !== undefined) {
    html +=
      '<div class="res-meta">Containers: ' + d.docker.containers + "</div>";
  }
  if (d.uptime) {
    html += '<div class="res-meta">Uptime: ' + escapeHtml(d.uptime) + "</div>";
  }
  if (d._lastHeartbeat) {
    var hbDate = new Date(d._lastHeartbeat);
    var hbStr = isNaN(hbDate.getTime())
      ? d._lastHeartbeat
      : hbDate.toLocaleString();
    html += '<div class="res-meta">Heartbeat: ' + escapeHtml(hbStr) + "</div>";
  }
  html += "</div>";
  return html;
}

/* todo#337: friendly canonical names so DXP480TPLUS-994 shows as "nas" etc.
 *
 * msg#17472 — the alias map used to be hard-coded here (resources tab
 * local). Consolidated to ``HOSTNAME_ALIASES`` in ``app/utils.ts`` so
 * the chat header / sidebar / agents-tab all apply the same canonical
 * labels. Re-export under the old name for any external caller that
 * still imports it directly. */
export var MACHINE_ALIASES = HOSTNAME_ALIASES;
export function _friendlyMachine(raw) {
  if (!raw) return raw;
  if (HOSTNAME_ALIASES[raw]) return HOSTNAME_ALIASES[raw] + " (" + raw + ")";
  return raw;
}

export async function fetchResources() {
  try {
    var res = await fetch(apiUrl("/api/resources"));
    if (!res.ok) return;
    var data = await res.json();
    Object.keys(data).forEach(function (agentName) {
      var entry = data[agentName];
      var r = entry.resources || {};
      /* Don't overwrite richer WS data with empty REST metrics (#337) */
      var existing = resourceData[agentName];
      if (
        existing &&
        !existing._api &&
        (r.mem_used_percent || 0) === 0 &&
        (existing.memory || {}).percent > 0
      )
        return;
      resourceData[agentName] = {
        hostname: _friendlyMachine(entry.machine || agentName),
        agent: agentName,
        cpu: {
          percent: Math.round(
            ((r.load_avg_1m || 0) / Math.max(r.cpu_count || 1, 1)) * 100,
          ),
        },
        memory: { percent: r.mem_used_percent || 0 },
        disk: { "/": { percent: r.disk_used_percent || 0 } },
        health: {
          status:
            r.mem_used_percent > 80 || r.disk_used_percent > 80
              ? "critical"
              : r.mem_used_percent > 60 || r.disk_used_percent > 60
                ? "warning"
                : "healthy",
        },
        _api: true,
        _status: entry.status || "unknown",
        _machine: entry.machine || "",
        _lastHeartbeat: entry.last_heartbeat || "",
        _cpuModel: r.cpu_model || "",
        _cpuCount: r.cpu_count || 0,
        _loadAvg: [r.load_avg_1m || 0, r.load_avg_5m || 0, r.load_avg_15m || 0],
        _memFreeMb: r.mem_free_mb || 0,
        _memTotalMb: r.mem_total_mb || 0,
        // Slurm cluster aggregates (todo#87). Populated only when the
        // host reports `resource_source == "slurm"` — login-node metrics
        // are replaced with cluster-wide CPU/RAM at the agent, so the
        // existing cpu/memory bars above now reflect cluster busy%.
        _resourceSource: r.resource_source || "local",
        slurm:
          r.resource_source === "slurm"
            ? {
                total_jobs: r.slurm_total_jobs || 0,
                running: r.slurm_running || 0,
                pending: r.slurm_pending || 0,
                cluster_nodes: r.cluster_nodes || 0,
                cluster_cpus_total: r.cluster_cpus_total || 0,
                cluster_cpus_allocated: r.cluster_cpus_allocated || 0,
              }
            : null,
        gpu:
          r.cluster_gpus_total > 0
            ? [
                {
                  utilization_percent:
                    r.cluster_gpus_total > 0
                      ? Math.round(
                          ((r.cluster_gpus_allocated || 0) /
                            r.cluster_gpus_total) *
                            100,
                        )
                      : 0,
                  total: r.cluster_gpus_total,
                  allocated: r.cluster_gpus_allocated || 0,
                },
              ]
            : null,
      };
    });
    renderResources();
    if (activeTab === "resources") renderResourcesTab();
  } catch (e) {
    console.warn("fetchResources failed:", e);
  }
}
