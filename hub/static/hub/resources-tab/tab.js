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
   setMachineIcon,
   cronByHost, fetchCronJobs, renderCronJobsHtml, wireCronToggles */

function renderResources() {
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
  /* Sidebar machines = one-line rows (ywatanabe 2026-04-19). ywatanabe
   * msg#16215 (2026-04-21): mba + nas rendered empty fields because the
   * producer only sent ``disk_used_percent`` (no total). Spec target —
   * CPU=``N cores`` (integer), RAM=``N/M GB`` (integers), Storage=``N/M TB``
   * (1 decimal), GPU=``N/M`` when present else ``n/a``. */
  container.innerHTML = keys
    .map(function (k) {
      var d = resourceData[k];
      var health = (d.health && d.health.status) || "healthy";
      var healthy = health === "healthy";
      var cpuCount = d._cpuCount || 0;
      var cpuStr = cpuCount > 0 ? cpuCount + " cores" : "—";
      var memTotalMb = d._memTotalMb || 0;
      var memUsedMb = d._memUsedMb || 0;
      if (!memUsedMb && memTotalMb > 0) {
        memUsedMb = Math.max(0, memTotalMb - (d._memFreeMb || 0));
      }
      var memStr = "—";
      if (memTotalMb > 0) {
        memStr =
          Math.round(memUsedMb / 1024) +
          "/" +
          Math.round(memTotalMb / 1024) +
          " GB";
      }
      var diskTotalMb = d._diskTotalMb || 0;
      var diskUsedMb = d._diskUsedMb || 0;
      var diskStr = "—";
      if (diskTotalMb > 0) {
        var diskTotalTb = diskTotalMb / 1024 / 1024;
        var diskUsedTb = diskUsedMb / 1024 / 1024;
        diskStr = diskUsedTb.toFixed(1) + "/" + diskTotalTb.toFixed(1) + " TB";
      } else if (d.disk) {
        var _dk = Object.keys(d.disk)[0];
        if (_dk) {
          var _p = d.disk[_dk].percent || 0;
          if (_p > 0) diskStr = Math.round(_p) + "%";
        }
      }
      var color =
        typeof getAgentColor === "function" ? getAgentColor(k) : "#e6e6e6";
      var gpuStr = "";
      if (d.gpu && d.gpu.length > 0) {
        var totalGpus = d.gpu.length;
        var usedGpus = d.gpu.filter(function (g) {
          return (g.utilization_percent || 0) > 5;
        }).length;
        var meanUtil =
          d.gpu.reduce(function (acc, g) {
            return acc + (g.utilization_percent || 0);
          }, 0) / totalGpus;
        gpuStr =
          ' <span class="res-chip" title="GPU ' +
          Math.round(meanUtil) +
          '% avg util">' +
          usedGpus +
          "/" +
          totalGpus +
          " gpu</span>";
      }
      var orochi_slurmStr = "";
      if (d.orochi_slurm && d.orochi_slurm.total_jobs > 0) {
        orochi_slurmStr =
          ' <span class="res-chip" title="SLURM jobs">' +
          d.orochi_slurm.total_jobs +
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
            (d && (d._fqdn || d._machineFqdn || d.orochi_hostname_canonical)) || "";
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
        '<span class="res-chip" title="CPU cores">' +
        escapeHtml(cpuStr) +
        "</span>" +
        '<span class="res-chip" title="RAM used/total">' +
        escapeHtml(memStr) +
        "</span>" +
        '<span class="res-chip" title="Storage used/total">' +
        escapeHtml(diskStr) +
        "</span>" +
        gpuStr +
        orochi_slurmStr +
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

function renderResourcesTab() {
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
  /* Orochi cron Phase 2 — per-host collapse chevron. */
  if (typeof wireCronToggles === "function") {
    wireCronToggles(grid, renderResourcesTab);
  }
  if (inputHasFocus && document.activeElement !== msgInput) {
    msgInput.focus();
    try {
      msgInput.setSelectionRange(savedStart, savedEnd);
    } catch (_) {}
  }
}

function buildResourceCard(k) {
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
    var usedMb = d._memUsedMb || Math.round(d._memTotalMb - (d._memFreeMb || 0));
    memDetail =
      '<div class="res-meta">RAM: ' +
      Math.round(usedMb / 1024) +
      " / " +
      Math.round(d._memTotalMb / 1024) +
      " GB</div>";
  }
  var diskDetail = "";
  if (d._diskTotalMb) {
    var diskUsedTb = (d._diskUsedMb || 0) / 1024 / 1024;
    var diskTotalTb = d._diskTotalMb / 1024 / 1024;
    diskDetail =
      '<div class="res-meta">Storage: ' +
      diskUsedTb.toFixed(1) +
      " / " +
      diskTotalTb.toFixed(1) +
      " TB</div>";
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
  html += loadHtml + cpuInfo + memDetail + diskDetail;
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
  /* Orochi unified cron Phase 2 — collapsible cron-jobs subsection. */
  if (typeof renderCronJobsHtml === "function") {
    html += renderCronJobsHtml(k);
  }
  html += "</div>";
  return html;
}

/* todo#337: friendly canonical names so DXP480TPLUS-994 shows as "nas" etc. */
var MACHINE_ALIASES = {
  "DXP480TPLUS-994": "nas",
  "Yusukes-MacBook-Air.local": "mba",
  "spartan-login1.hpc.unimelb.edu.au": "spartan",
  "spartan-login1": "spartan",
};
function _friendlyMachine(raw) {
  if (!raw) return raw;
  if (MACHINE_ALIASES[raw]) return MACHINE_ALIASES[raw] + " (" + raw + ")";
  return raw;
}

async function fetchResources() {
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
      /* ywatanabe msg#16215 — GPU projection. See TS mirror for rationale. */
      var gpuList = null;
      if (Array.isArray(r.gpus) && r.gpus.length > 0) {
        gpuList = r.gpus.map(function (g) {
          return {
            name: g.name || "gpu",
            utilization_percent: g.utilization_percent || 0,
            memory_used_mb: g.memory_used_mb || 0,
            memory_total_mb: g.memory_total_mb || 0,
          };
        });
      } else if (r.cluster_gpus_total > 0) {
        gpuList = [
          {
            name: "cluster",
            utilization_percent: Math.round(
              ((r.cluster_gpus_allocated || 0) / r.cluster_gpus_total) * 100,
            ),
            total: r.cluster_gpus_total,
            allocated: r.cluster_gpus_allocated || 0,
          },
        ];
      }
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
        /* ywatanabe msg#16215 absolute MB for N/M display. */
        _memUsedMb: r.mem_used_mb || 0,
        _diskTotalMb: r.disk_total_mb || 0,
        _diskUsedMb: r.disk_used_mb || 0,
        // Slurm cluster aggregates (todo#87). Populated only when the
        // host reports `resource_source == "orochi_slurm"` — login-node metrics
        // are replaced with cluster-wide CPU/RAM at the agent, so the
        // existing cpu/memory bars above now reflect cluster busy%.
        _resourceSource: r.resource_source || "local",
        orochi_slurm:
          r.resource_source === "orochi_slurm"
            ? {
                total_jobs: r.orochi_slurm_total_jobs || 0,
                running: r.orochi_slurm_running || 0,
                pending: r.orochi_slurm_pending || 0,
                cluster_nodes: r.cluster_nodes || 0,
                cluster_cpus_total: r.cluster_cpus_total || 0,
                cluster_cpus_allocated: r.cluster_cpus_allocated || 0,
              }
            : null,
        gpu: gpuList,
      };
    });
    /* Orochi cron Phase 2 — piggyback fetch on the 30s resource poll. */
    if (typeof fetchCronJobs === "function") {
      await fetchCronJobs();
    }
    renderResources();
    if (activeTab === "resources") renderResourcesTab();
  } catch (e) {
    console.warn("fetchResources failed:", e);
  }
}
