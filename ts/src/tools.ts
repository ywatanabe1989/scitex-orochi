/**
 * MCP tool handlers for Orochi push client.
 *
 * Thin orchestrator: re-exports handlers from focused sub-modules under
 * ./tools/. Consumers (ts/mcp_channel/handlers.ts) import from here so the
 * public surface stays stable across refactors.
 */
export {
  handleReply,
  handleHistory,
  handleReact,
  handleExportChannel,
} from "./tools/messaging.js";

export {
  handleSubscribe,
  handleUnsubscribe,
  handleChannelInfo,
  handleChannelMembers,
  handleMySubscriptions,
  handleDmList,
  handleDmOpen,
} from "./tools/channels.js";

export { handleDownloadMedia, handleUploadMedia } from "./tools/media.js";

export {
  handleHealth,
  handleTask,
  handleSubagents,
  handleStatus,
  handleContext,
} from "./tools/agent_status.js";

export { handleRsyncMedia, handleRsyncStatus } from "./tools/rsync.js";

export {
  handleConnectivityMatrix,
  handleCronStatus,
  handleSidecarStatus,
} from "./tools/sidecar.js";

export {
  handleSelfCommand,
  isSafeForSelfCommand,
} from "./tools/self_command.js";

export { handleA2aCall } from "./tools/a2a.js";
export { handleA2aSendStreaming } from "./tools/a2a_streaming.js";
export { handleA2aGetTask } from "./tools/a2a_get_task.js";
export { handleA2aCancelTask } from "./tools/a2a_cancel_task.js";
export { handleA2aListAgents } from "./tools/a2a_list_agents.js";
