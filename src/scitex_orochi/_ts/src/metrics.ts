/**
 * System metrics collection for heartbeat payloads.
 */
import { cpus, freemem, totalmem, loadavg } from "os";
import { execSync } from "child_process";

export function getSystemMetrics() {
  const cpuInfo = cpus();
  const free = freemem();
  const total = totalmem();
  const load = loadavg();

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
    mem_free_mb: Math.round(free / 1048576),
    mem_total_mb: Math.round(total / 1048576),
    mem_used_percent: Math.round(((total - free) / total) * 100),
    disk_used_percent: diskUsagePercent,
  };
}
