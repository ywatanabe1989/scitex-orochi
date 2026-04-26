/**
 * MCP request handler wiring — ListTools + CallTool dispatch table.
 */
import type { Server } from "@modelcontextprotocol/sdk/server/index.js";
import {
  ListToolsRequestSchema,
  CallToolRequestSchema,
} from "@modelcontextprotocol/sdk/types.js";
import { TOOL_DEFS } from "../src/tool_defs.js";
import {
  handleContext,
  handleCronStatus,
  handleDmList,
  handleDmOpen,
  handleDownloadMedia,
  handleHealth,
  handleReply,
  handleHistory,
  handleSubscribe,
  handleUnsubscribe,
  handleChannelInfo,
  handleChannelMembers,
  handleMySubscriptions,
  handleConnectivityMatrix,
  handleReact,
  handleRsyncMedia,
  handleRsyncStatus,
  handleSidecarStatus,
  handleStatus,
  handleSelfCommand,
  handleSubagents,
  handleTask,
  handleUploadMedia,
  handleExportChannel,
  handleA2aCall,
  handleA2aSendStreaming,
  handleA2aGetTask,
  handleA2aCancelTask,
  handleA2aListAgents,
} from "../src/tools.js";
import { conn } from "./connection.js";

export function registerMcpHandlers(mcp: Server): void {
  mcp.setRequestHandler(ListToolsRequestSchema, async () => ({
    tools: TOOL_DEFS,
  }));

  mcp.setRequestHandler(CallToolRequestSchema, async (req) => {
    const { name, arguments: args } = req.params;
    if (name === "reply") return handleReply(conn as any, args as any);
    if (name === "history") return handleHistory(args as any);
    if (name === "react") return handleReact(args as any);
    if (name === "subagents") return handleSubagents(conn as any, args as any);
    if (name === "task") return handleTask(conn as any, args as any);
    if (name === "health") return handleHealth(args as any);
    if (name === "context") return handleContext(args as any);
    if (name === "status") return handleStatus(conn as any);
    if (name === "subscribe") return handleSubscribe(conn as any, args as any);
    if (name === "unsubscribe")
      return handleUnsubscribe(conn as any, args as any);
    if (name === "channel_info") return handleChannelInfo(args as any);
    if (name === "channel_members") return handleChannelMembers(args as any);
    if (name === "my_subscriptions") return handleMySubscriptions(args as any);
    if (name === "download_media") return handleDownloadMedia(args as any);
    if (name === "upload_media") return handleUploadMedia(args as any);
    if (name === "rsync_media") return handleRsyncMedia(args as any);
    if (name === "rsync_status") return handleRsyncStatus(args as any);
    if (name === "sidecar_status") return handleSidecarStatus();
    if (name === "connectivity_matrix") return handleConnectivityMatrix();
    if (name === "cron_status") return handleCronStatus(args as any);
    if (name === "self_command") return handleSelfCommand(args as any);
    if (name === "dm_list") return handleDmList(args as any);
    if (name === "dm_open") return handleDmOpen(args as any);
    if (name === "export_channel") return handleExportChannel(args as any);
    if (name === "a2a_call") return handleA2aCall(args as any);
    if (name === "a2a_send_streaming")
      return handleA2aSendStreaming(args as any);
    if (name === "a2a_get_task") return handleA2aGetTask(args as any);
    if (name === "a2a_cancel_task") return handleA2aCancelTask(args as any);
    if (name === "a2a_list_agents") return handleA2aListAgents();
    throw new Error(`Unknown tool: ${name}`);
  });
}
