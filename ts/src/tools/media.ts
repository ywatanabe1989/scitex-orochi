/**
 * Media transfer tools: download_media, upload_media (with content-addressable dedup).
 */
import { readFileSync, writeFileSync, mkdirSync, existsSync } from "fs";
import { basename, dirname } from "path";
import { createHash } from "crypto";
import {
  MCP_ERROR_CODES,
  OROCHI_AGENT,
  OROCHI_TOKEN,
  httpBase,
  mcpError,
  tokenParam,
  buildFetchHeaders,
  MIME,
} from "./_shared.js";

const MEDIA_DIR = "/tmp/orochi-media";

export async function handleDownloadMedia(args: {
  url: string;
  output_path?: string;
}): Promise<{ content: Array<{ type: string; text: string }> }> {
  try {
    // Resolve URL: if relative, prepend hub base
    let fullUrl = args.url;
    if (!fullUrl.startsWith("http")) {
      fullUrl =
        httpBase.replace(/\/$/, "") +
        (fullUrl.startsWith("/") ? "" : "/") +
        fullUrl;
    }

    // Append token if needed
    const sep = fullUrl.includes("?") ? "&" : "?";
    const fetchUrl = OROCHI_TOKEN
      ? `${fullUrl}${sep}token=${OROCHI_TOKEN}`
      : fullUrl;

    const resp = await fetch(fetchUrl, {
      headers: buildFetchHeaders(),
    });
    if (!resp.ok) {
      const code =
        resp.status === 401 || resp.status === 403
          ? MCP_ERROR_CODES.PERMISSION_DENIED
          : resp.status === 404
            ? MCP_ERROR_CODES.NOT_FOUND
            : MCP_ERROR_CODES.INTERNAL_ERROR;
      return mcpError(
        code,
        `HTTP ${resp.status} downloading ${fullUrl}`,
        "verify the URL and that the workspace token is valid",
      );
    }

    // Determine output path
    const urlPath = new URL(fullUrl).pathname;
    const filename = basename(urlPath) || "download";
    const outputPath = args.output_path || `${MEDIA_DIR}/${filename}`;

    // Ensure directory exists
    const dir = dirname(outputPath);
    if (!existsSync(dir)) {
      mkdirSync(dir, { recursive: true });
    }

    const buffer = Buffer.from(await resp.arrayBuffer());
    writeFileSync(outputPath, buffer);

    return {
      content: [
        {
          type: "text",
          text: `Downloaded to ${outputPath} (${buffer.length} bytes)`,
        },
      ],
    };
  } catch (err) {
    return mcpError(
      MCP_ERROR_CODES.INTERNAL_ERROR,
      `download_media failed: ${(err as Error).message}`,
      "check hub reachability and local disk space",
    );
  }
}

export async function handleUploadMedia(args: {
  file_path: string;
  channel?: string;
}): Promise<{ content: Array<{ type: string; text: string }> }> {
  try {
    if (!existsSync(args.file_path)) {
      return mcpError(
        MCP_ERROR_CODES.NOT_FOUND,
        `file not found: ${args.file_path}`,
        "pass an absolute path that exists on this host",
      );
    }

    const fileData = readFileSync(args.file_path);
    const filename = basename(args.file_path);

    // --- Content-addressable dedup: check hash before uploading ---
    //
    // todo#97: a HEAD/GET on /api/media/by-hash/ confirms the blob is
    // already on the hub, but we MUST also create a Message row so the
    // file shows up in the channel feed and Files tab. Prior versions
    // returned the existing URL here without creating a Message, leaving
    // dedup-hit uploads invisible (orphaned blobs). The fix is to POST
    // back to the same endpoint with {channel, sender}; the server then
    // creates the Message row referencing the existing blob without any
    // bandwidth cost.
    const contentHash = createHash("sha256").update(fileData).digest("hex");
    const hashCheckUrl = `${httpBase}/api/media/by-hash/${contentHash}${tokenParam("?")}`;
    const targetChannel = args.channel || "#general";
    try {
      const headResp = await fetch(hashCheckUrl, {
        method: "HEAD",
        headers: buildFetchHeaders(),
      });
      if (headResp.ok) {
        // Dedup hit — POST to attach the existing blob to the target
        // channel as a Message row (no upload required).
        const attachResp = await fetch(hashCheckUrl, {
          method: "POST",
          headers: buildFetchHeaders({ "Content-Type": "application/json" }),
          body: JSON.stringify({
            channel: targetChannel,
            sender: OROCHI_AGENT,
          }),
        });
        if (attachResp.ok) {
          const attached = (await attachResp.json()) as {
            url?: string;
            message_id?: number;
          };
          const mediaUrl = attached.url
            ? attached.url.startsWith("http")
              ? attached.url
              : `${httpBase}${attached.url}`
            : "unknown";
          return {
            content: [
              {
                type: "text",
                text: `Uploaded ${filename} -> ${mediaUrl} (deduplicated; attached as message ${attached.message_id ?? "?"})`,
              },
            ],
          };
        }
        // attach failed — fall through to full upload
      }
    } catch {
      // Dedup check failed — fall through to normal upload
    }

    const b64 = fileData.toString("base64");
    const ext = filename.split(".").pop()?.toLowerCase() || "";
    const mime_type = MIME[ext] || "application/octet-stream";

    const resp = await fetch(
      `${httpBase}/api/upload-base64${tokenParam("?")}`,
      {
        method: "POST",
        headers: buildFetchHeaders({ "Content-Type": "application/json" }),
        body: JSON.stringify({
          data: b64,
          filename,
          mime_type,
          channel: args.channel || "#general",
          sender: OROCHI_AGENT,
        }),
      },
    );

    if (!resp.ok) {
      const body = await resp.text();
      const code =
        resp.status === 401 || resp.status === 403
          ? MCP_ERROR_CODES.PERMISSION_DENIED
          : resp.status === 404
            ? MCP_ERROR_CODES.NOT_FOUND
            : MCP_ERROR_CODES.INTERNAL_ERROR;
      return mcpError(
        code,
        `upload_media HTTP ${resp.status}`,
        body.slice(0, 200) || "no response body",
      );
    }

    const result = (await resp.json()) as {
      url?: string;
      filename?: string;
      deduplicated?: boolean;
    };
    const mediaUrl = result.url
      ? result.url.startsWith("http")
        ? result.url
        : `${httpBase}${result.url}`
      : "unknown";
    const dedupeNote = result.deduplicated ? " (deduplicated)" : "";

    return {
      content: [
        {
          type: "text",
          text: `Uploaded ${filename} -> ${mediaUrl}${dedupeNote}`,
        },
      ],
    };
  } catch (err) {
    return mcpError(
      MCP_ERROR_CODES.INTERNAL_ERROR,
      `upload_media failed: ${(err as Error).message}`,
      "check hub reachability and local disk",
    );
  }
}
