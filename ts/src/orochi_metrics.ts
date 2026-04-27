/**
 * System orochi_metrics collection for heartbeat payloads.
 *
 * Tries, in order:
 *   1. `python3 -c "import scitex.resource as r; import json; ..."` — the
 *      single source of truth used by scitex throughout the fleet. Reports
 *      MemAvailable-based usage, matches `free -h` exactly.
 *   2. `/proc/meminfo` directly — same math, no scitex dependency.
 *   3. Node `os.totalmem()/freemem()` — last-resort macOS fallback; known
 *      to over-report on Linux because `os.freemem()` returns MemFree.
 *
 * The ~96% false-positive bug (scitex-orochi#5) was caused by (3) running
 * as the primary path on every Linux agent.
 */
import { cpus, freemem, totalmem, loadavg, platform } from "os";
import { execSync } from "child_process";
import { readFileSync } from "fs";

type Gpu = {
  name: string;
  utilization_percent: number;
  memory_used_mb: number;
  memory_total_mb: number;
};

type Metrics = {
  cpu_count: number;
  cpu_model: string;
  load_avg_1m: number;
  load_avg_5m: number;
  load_avg_15m: number;
  mem_free_mb: number;
  mem_total_mb: number;
  mem_used_mb: number;
  mem_used_percent: number;
  disk_used_percent: number | null;
  disk_total_mb: number | null;
  disk_used_mb: number | null;
  gpus: Gpu[];
};

/** Try scitex.resource.get_specs() via a short python subprocess. */
function _tryScitexResource(): Partial<Metrics> | null {
  try {
    const script =
      "import json,sys\n" +
      "try:\n" +
      "  from scitex.resource import get_specs\n" +
      "except Exception as e:\n" +
      "  sys.stderr.write(str(e)); sys.exit(1)\n" +
      "try:\n" +
      "  s = get_specs(verbose=False)\n" +
      "except TypeError:\n" +
      "  s = get_specs()\n" +
      "print(json.dumps(s, default=str))\n";
    const out = execSync(`python3 -c ${JSON.stringify(script)}`, {
      timeout: 3000,
      stdio: ["ignore", "pipe", "ignore"],
    }).toString();
    const obj = JSON.parse(out);
    // scitex get_specs returns nested sections; keys vary between versions
    // so we look up a few plausible names.
    const mem = obj.Memory || obj.memory || {};
    const cpu = obj.CPU || obj.cpu || obj["CPU Info"] || {};
    const disk = obj.Disk || obj.disk || {};
    const memTotalGiB = parseFloat(
      String(mem["Total"] ?? mem.total ?? "").replace(/[^\d.]/g, ""),
    );
    const memUsedPct = parseFloat(
      String(mem["Percentage"] ?? mem.percent ?? "").replace(/[^\d.]/g, ""),
    );
    if (!memTotalGiB || !Number.isFinite(memUsedPct)) return null;
    const result: Partial<Metrics> = {
      mem_total_mb: Math.round(memTotalGiB * 1024),
      mem_used_percent: Math.round(memUsedPct),
    };
    const freeGiB = parseFloat(
      String(mem["Available"] ?? mem.available ?? "").replace(/[^\d.]/g, ""),
    );
    if (Number.isFinite(freeGiB)) result.mem_free_mb = Math.round(freeGiB * 1024);
    const cpuPct = parseFloat(
      String(cpu["Percentage"] ?? cpu.percent ?? "").replace(/[^\d.]/g, ""),
    );
    // We return cpu as load_avg; cpuPct is separate and lives in orochi_metrics too.
    // Disk usage: try to parse the first "X%" we find anywhere under disk
    const diskStr = JSON.stringify(disk);
    const diskMatch = diskStr.match(/(\d+(?:\.\d+)?)\s*%/);
    if (diskMatch) result.disk_used_percent = Math.round(parseFloat(diskMatch[1]));
    return result;
  } catch (_) {
    return null;
  }
}

/** Read /proc/meminfo directly as a second option (Linux only). */
function _tryProcMeminfo(): Partial<Metrics> | null {
  if (platform() !== "linux") return null;
  try {
    const txt = readFileSync("/proc/meminfo", "utf8");
    const get = (k: string) => {
      const m = txt.match(new RegExp("^" + k + ":\\s+(\\d+)", "m"));
      return m ? parseInt(m[1], 10) : null; // kB
    };
    const total = get("MemTotal");
    const avail = get("MemAvailable") ?? get("MemFree");
    if (!total || avail == null) return null;
    const used = total - avail;
    return {
      mem_total_mb: Math.round(total / 1024),
      mem_free_mb: Math.round(avail / 1024),
      mem_used_mb: Math.round(used / 1024),
      mem_used_percent: Math.round((used / total) * 100),
    };
  } catch (_) {
    return null;
  }
}

/** Best-effort disk-total/used via ``df -k --output=``. ~200 ms max. */
function _tryDiskTotals(): {
  disk_total_mb: number;
  disk_used_mb: number;
  disk_used_percent: number;
} | null {
  try {
    // POSIX df -Pk is portable (Darwin + Linux) and prints blocks in KB.
    // Columns: Filesystem 1024-blocks Used Available Capacity Mounted
    const out = execSync("df -Pk / | tail -1", { timeout: 3000 }).toString();
    const cols = out.trim().split(/\s+/);
    if (cols.length < 5) return null;
    const totalKb = parseInt(cols[1], 10);
    const usedKb = parseInt(cols[2], 10);
    if (!Number.isFinite(totalKb) || !Number.isFinite(usedKb)) return null;
    return {
      disk_total_mb: Math.round(totalKb / 1024),
      disk_used_mb: Math.round(usedKb / 1024),
      disk_used_percent: Math.round((usedKb / Math.max(totalKb, 1)) * 100),
    };
  } catch (_) {
    return null;
  }
}

/** Per-GPU list via ``nvidia-smi``. Empty when no NVIDIA GPU present. */
function _tryGpus(): Gpu[] {
  try {
    const out = execSync(
      "nvidia-smi --query-gpu=name,utilization.gpu,memory.used,memory.total --format=csv,noheader,nounits",
      { timeout: 3000, stdio: ["ignore", "pipe", "ignore"] },
    ).toString();
    const gpus: Gpu[] = [];
    for (const line of out.split("\n")) {
      const parts = line.split(",").map((s) => s.trim());
      if (parts.length < 4) continue;
      const util = parseFloat(parts[1]);
      const used = parseFloat(parts[2]);
      const total = parseFloat(parts[3]);
      if (!Number.isFinite(util) || !Number.isFinite(total)) continue;
      gpus.push({
        name: parts[0] || "gpu",
        utilization_percent: util,
        memory_used_mb: used,
        memory_total_mb: total,
      });
    }
    return gpus;
  } catch (_) {
    return [];
  }
}

/** Node.js fallback — only honest on macOS. */
function _fromNodeOs(): Partial<Metrics> {
  const free = freemem();
  const total = totalmem();
  return {
    mem_free_mb: Math.round(free / 1048576),
    mem_total_mb: Math.round(total / 1048576),
    mem_used_mb: Math.round((total - free) / 1048576),
    mem_used_percent: Math.round(((total - free) / total) * 100),
  };
}

export function getSystemMetrics(): Metrics {
  const cpuInfo = cpus();
  const load = loadavg();

  // Disk: prefer full totals (ywatanabe msg#16215 — N/M TB display)
  // with percent-only df fallback for parity with the pre-16215 shape.
  const diskTotals = _tryDiskTotals();
  let diskUsagePercent: number | null = diskTotals?.disk_used_percent ?? null;
  if (diskUsagePercent == null) {
    try {
      const dfOut = execSync("df -h / | tail -1", { timeout: 3000 }).toString();
      const match = dfOut.match(/(\d+)%/);
      if (match) diskUsagePercent = parseInt(match[1]);
    } catch (_) {}
  }

  /* NOTE: `scitex.resource` has a module-import side effect that
   * spawns a local Flask dashboard on 127.0.0.1:5000. Sidecars must
   * NOT spawn surprise web listeners, so we intentionally do NOT
   * import it here. /proc/meminfo is the correct primary on Linux
   * (same MemAvailable that scitex.resource reads underneath), and
   * os.freemem() is only honest on macOS. scitex-orochi#5 / mamba's
   * warning 2026-04-09. */
  const mem = _tryProcMeminfo() || _fromNodeOs();

  return {
    cpu_count: cpuInfo.length,
    cpu_model: cpuInfo[0]?.orochi_model || "unknown",
    load_avg_1m: load[0],
    load_avg_5m: load[1],
    load_avg_15m: load[2],
    mem_free_mb: mem.mem_free_mb ?? 0,
    mem_total_mb: mem.mem_total_mb ?? 0,
    mem_used_mb: mem.mem_used_mb ?? 0,
    mem_used_percent: mem.mem_used_percent ?? 0,
    disk_used_percent: diskUsagePercent ?? (mem.disk_used_percent ?? null),
    disk_total_mb: diskTotals?.disk_total_mb ?? null,
    disk_used_mb: diskTotals?.disk_used_mb ?? null,
    gpus: _tryGpus(),
  };
}
