/**
 * System metrics collection for heartbeat payloads.
 */
import { cpus, freemem, totalmem, loadavg } from "os";
import { execSync, execFileSync } from "child_process";
import { readFileSync } from "fs";

/**
 * Try to read MemAvailable (kB) from /proc/meminfo on Linux.
 * Falls back to null on macOS / non-Linux. MemAvailable is the
 * kernel's estimate of how much memory is actually reclaimable
 * for new allocations — it counts buffers/cache as free, which
 * is what users actually want to see.
 */
function memAvailableMB(): number | null {
  try {
    const txt = readFileSync("/proc/meminfo", "utf-8");
    const m = txt.match(/MemAvailable:\s+(\d+)\s*kB/);
    if (m) return Math.round(parseInt(m[1]) / 1024);
  } catch (_) {}
  return null;
}

export function getSystemMetrics() {
  const cpuInfo = cpus();
  const free = freemem();
  const total = totalmem();
  const load = loadavg();

  // Prefer MemAvailable (Linux 3.14+) over freemem(). freemem() is the OS
  // "free" page count, which excludes buffers/cache and makes Linux look
  // 80%+ used even when most of that is reclaimable cache.
  const availableMB = memAvailableMB();
  const totalMB = Math.round(total / 1048576);
  const freeMB = availableMB != null ? availableMB : Math.round(free / 1048576);
  const usedPct = totalMB > 0 ? Math.round(((totalMB - freeMB) / totalMB) * 100) : 0;

  // Disk usage via df (best-effort)
  let diskUsagePercent: number | null = null;
  try {
    const dfOut = execSync("df -h / | tail -1", { timeout: 3000 }).toString();
    const match = dfOut.match(/(\d+)%/);
    if (match) diskUsagePercent = parseInt(match[1]);
  } catch (_) {}

  return {
    cpu_count: cpuInfo.length,
    cpu_model: cpuInfo[0]?.model || "unknown",
    load_avg_1m: load[0],
    load_avg_5m: load[1],
    load_avg_15m: load[2],
    mem_free_mb: freeMB,
    mem_total_mb: totalMB,
    mem_used_percent: usedPct,
    disk_used_percent: diskUsagePercent,
  };
}
