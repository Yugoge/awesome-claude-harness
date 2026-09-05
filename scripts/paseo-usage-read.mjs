#!/usr/bin/env node
// paseo-usage-read.mjs — READ-ONLY per-account usage adapter (blueprint M18).
//
// Connects to the paseo daemon WebSocket RPC surface and issues exactly ONE
// session message: provider.usage.list.request. No mutation RPC of any kind.
// Prints the providers[] array of provider.usage.list.response as JSON to
// stdout. This is THE usage-read route consumed by /paseo-daemon's tick via
// scripts/paseo-daemon-ledger.py usage-ingest.
//
// Usage:
//   node scripts/paseo-usage-read.mjs                     # live read
//   node scripts/paseo-usage-read.mjs --from-envelope F   # offline: parse a
//       captured provider.usage.list.response envelope file (no network)
//
// Config (documented defaults, overridable — no secrets ever printed):
//   PASEO_CONFIG_DIR        default: $HOME/.paseo
//     <dir>/config.json     daemon.listen (host:port) -> ws://<listen>/ws
//     <dir>/daemon-password.txt   WS subprotocol paseo.bearer.<password>
//   PASEO_USAGE_TIMEOUT_MS  default: 10000
//
// Exit codes: 0=ok, 2=connect/auth failure, 3=timeout, 4=rpc/parse error,
//             1=usage error.

import { readFileSync } from "node:fs";
import { homedir } from "node:os";
import { join } from "node:path";
import { fileURLToPath } from "node:url";
import { randomUUID } from "node:crypto";

// Node 20 ships WebSocket behind --experimental-websocket; newer majors expose
// it by default. Re-exec ourselves with the flag when absent so the invocation
// surface stays exactly `node scripts/paseo-usage-read.mjs`.
if (typeof WebSocket === "undefined") {
  const { spawnSync } = await import("node:child_process");
  const self = fileURLToPath(import.meta.url);
  const r = spawnSync(
    process.execPath,
    ["--experimental-websocket", self, ...process.argv.slice(2)],
    { stdio: "inherit" },
  );
  process.exit(r.status === null ? 2 : r.status);
}

function findResponse(node) {
  // Locate the provider.usage.list.response object anywhere in the envelope.
  if (node === null || typeof node !== "object") return null;
  if (node.type === "provider.usage.list.response") return node;
  for (const value of Object.values(node)) {
    const hit = findResponse(value);
    if (hit) return hit;
  }
  return null;
}

function extractProviders(envelope) {
  const resp = findResponse(envelope);
  if (!resp) return null;
  const providers = resp.providers ?? resp.payload?.providers;
  return Array.isArray(providers) ? providers : null;
}

const args = process.argv.slice(2);
const envelopeIdx = args.indexOf("--from-envelope");
if (envelopeIdx !== -1) {
  // Offline mode: deterministic parse of a captured envelope (fixture chain).
  const file = args[envelopeIdx + 1];
  if (!file) {
    console.error("ERROR: --from-envelope requires a file path");
    process.exit(1);
  }
  try {
    const providers = extractProviders(JSON.parse(readFileSync(file, "utf8")));
    if (!providers) {
      console.error("ERROR: no provider.usage.list.response providers[] in envelope");
      process.exit(4);
    }
    process.stdout.write(JSON.stringify(providers) + "\n");
    process.exit(0);
  } catch (err) {
    console.error(`ERROR: envelope parse failed: ${err.message}`);
    process.exit(4);
  }
}

const configDir = process.env.PASEO_CONFIG_DIR || join(homedir(), ".paseo");
const timeoutMs = Number(process.env.PASEO_USAGE_TIMEOUT_MS || 10000);

let listen;
let password;
try {
  const config = JSON.parse(readFileSync(join(configDir, "config.json"), "utf8"));
  listen = config?.daemon?.listen;
  if (!listen) throw new Error("daemon.listen missing from config.json");
  password = readFileSync(join(configDir, "daemon-password.txt"), "utf8").trim();
  if (!password) throw new Error("daemon-password.txt empty");
} catch (err) {
  console.error(`ERROR: config read failed: ${err.message}`);
  process.exit(2);
}

const url = `ws://${listen}/ws`;
const requestId = randomUUID();
let settled = false;

function finish(code, message) {
  if (settled) return;
  settled = true;
  if (message) console.error(message);
  try {
    ws.close();
  } catch {
    /* already closed */
  }
  // Allow the close frame to flush, then exit.
  setTimeout(() => process.exit(code), 20).unref?.();
  process.exitCode = code;
}

const timer = setTimeout(() => {
  finish(3, `ERROR: timed out after ${timeoutMs}ms waiting for provider.usage.list.response`);
}, timeoutMs);
timer.unref?.();

let ws;
try {
  ws = new WebSocket(url, [`paseo.bearer.${password}`]);
} catch (err) {
  console.error(`ERROR: websocket construction failed: ${err.message}`);
  process.exit(2);
}

ws.addEventListener("error", () => {
  finish(2, `ERROR: websocket connect/auth failure against ${url}`);
});
ws.addEventListener("close", () => {
  if (!settled) finish(2, `ERROR: websocket closed before response (${url})`);
});
ws.addEventListener("open", () => {
  ws.send(
    JSON.stringify({
      type: "hello",
      clientId: `paseo-usage-read-${requestId}`,
      clientType: "cli",
      protocolVersion: 1,
    }),
  );
  // The ONLY session message this adapter ever sends (read-only surface):
  ws.send(
    JSON.stringify({
      type: "session",
      message: { type: "provider.usage.list.request", requestId },
    }),
  );
});
ws.addEventListener("message", (event) => {
  let envelope;
  try {
    envelope = JSON.parse(typeof event.data === "string" ? event.data : String(event.data));
  } catch {
    return; // ignore non-JSON frames
  }
  const providers = extractProviders(envelope);
  if (providers) {
    clearTimeout(timer);
    process.stdout.write(JSON.stringify(providers) + "\n");
    finish(0);
  }
});
