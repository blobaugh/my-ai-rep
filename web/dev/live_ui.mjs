/**
 * One real two-message chat in the page. Skipped unless RUN_INTEGRATION=1.
 * Prints lengths only, never the reply text.
 */
import { spawn } from "node:child_process";
import { mkdtemp, readFile, rm } from "node:fs/promises";
import { createServer } from "node:http";
import { tmpdir } from "node:os";
import path from "node:path";
import { setTimeout as delay } from "node:timers/promises";
import { fileURLToPath } from "node:url";

if (process.env.RUN_INTEGRATION !== "1") {
  process.stdout.write("skip live ui (set RUN_INTEGRATION=1)\n");
  process.exit(0);
}

const repo = fileURLToPath(new URL("../..", import.meta.url));
const chrome = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome";
const python = path.join(repo, ".venv", "bin", "python");
const apiPort = 8000;
const webPort = 8766;
const debugPort = 9334;

function assert(cond, message) {
  if (!cond) throw new Error(message);
}

class Cdp {
  constructor(ws) {
    this.ws = ws;
    this.next = 1;
    this.pending = new Map();
    ws.addEventListener("message", (event) => {
      const message = JSON.parse(event.data);
      if (message.id && this.pending.has(message.id)) {
        this.pending.get(message.id)(message);
        this.pending.delete(message.id);
      }
    });
  }

  send(method, params = {}, sessionId) {
    const id = this.next++;
    const payload = { id, method, params };
    if (sessionId) payload.sessionId = sessionId;
    return new Promise((resolve) => {
      this.pending.set(id, resolve);
      this.ws.send(JSON.stringify(payload));
    });
  }
}

async function waitFor(url) {
  const started = Date.now();
  while (Date.now() - started < 20000) {
    try {
      const response = await fetch(url);
      if (response.ok) return;
    } catch {
      /* starting */
    }
    await delay(150);
  }
  throw new Error(`nothing answered ${url}`);
}

async function evaluate(cdp, sessionId, expression) {
  const reply = await cdp.send(
    "Runtime.evaluate",
    { expression, returnByValue: true, awaitPromise: true },
    sessionId,
  );
  if (reply.result?.exceptionDetails) {
    throw new Error("page error");
  }
  return reply.result?.result?.value;
}

async function sendAndWait(cdp, sessionId, message, count) {
  await evaluate(
    cdp,
    sessionId,
    `(() => {
      const box = document.querySelector("#message");
      box.value = ${JSON.stringify(message)};
      document.querySelector("#composer").requestSubmit();
      return true;
    })()`,
  );
  const started = Date.now();
  while (Date.now() - started < 90000) {
    const ready = await evaluate(
      cdp,
      sessionId,
      `document.querySelector(".typing") === null && document.querySelectorAll(".msg.visitor").length >= ${count}`,
    );
    if (ready) return;
    await delay(200);
  }
  throw new Error("timed out waiting for a reply");
}

async function main() {
  const profile = await mkdtemp(path.join(tmpdir(), "benbot-live-"));
  const env = { ...process.env, CORS_ALLOWED_ORIGINS: `http://127.0.0.1:${webPort}` };
  delete env.CONTENT_DIR;
  const api = spawn(python, ["-m", "src.api"], {
    cwd: repo,
    env,
    stdio: ["ignore", "ignore", "pipe"],
  });
  let apiError = "";
  api.stderr.on("data", (chunk) => {
    apiError += chunk.toString();
  });
  const web = await serveWeb(webPort, path.join(repo, "web"), `http://127.0.0.1:${apiPort}`);
  const browser = spawn(
    chrome,
    [
      "--headless=new",
      "--disable-gpu",
      `--remote-debugging-port=${debugPort}`,
      `--user-data-dir=${profile}`,
      "--no-first-run",
      "about:blank",
    ],
    { stdio: "ignore" },
  );
  try {
    await waitFor(`http://127.0.0.1:${apiPort}/api/health`);
    await waitFor(`http://127.0.0.1:${webPort}/`);
    const version = await (await fetch(`http://127.0.0.1:${debugPort}/json/version`)).json();
    const socket = new WebSocket(version.webSocketDebuggerUrl);
    await new Promise((resolve, reject) => {
      socket.addEventListener("open", resolve);
      socket.addEventListener("error", () => reject(new Error("chrome socket failed")));
    });
    const cdp = new Cdp(socket);
    const created = await cdp.send("Target.createTarget", { url: "about:blank" });
    const targetId = created.result.targetId;
    const attached = await cdp.send("Target.attachToTarget", { targetId, flatten: true });
    const sessionId = attached.result.sessionId;
    await cdp.send("Page.enable", {}, sessionId);
    await cdp.send("Page.navigate", { url: `http://127.0.0.1:${webPort}/` }, sessionId);
    const started = Date.now();
    let label = "";
    while (Date.now() - started < 8000) {
      label = await evaluate(cdp, sessionId, `document.querySelector("#ai-label")?.textContent || ""`);
      if (String(label).includes("AI")) break;
      await delay(100);
    }
    assert(String(label).includes("AI"), "label did not load");
    await sendAndWait(cdp, sessionId, "Who is Avery?", 1);
    await sendAndWait(cdp, sessionId, "Say more about that", 2);
    const summary = await evaluate(
      cdp,
      sessionId,
      `(() => {
        const visitors = document.querySelectorAll(".msg.visitor").length;
        const bots = [...document.querySelectorAll(".msg.bot p")].map((node) => node.textContent);
        const replies = bots.slice(-visitors);
        return {
          replies: replies.length,
          lengths: replies.map((text) => text.length),
          session: (document.querySelector("#session-id")?.textContent || "").length,
          unavailable: replies.some((text) => text.includes("not available")),
          network: replies.some((text) => text.includes("could not be sent")),
        };
      })()`,
    );
    assert(summary.replies === 2, "expected two replies");
    assert(summary.session === 32, `session length ${summary.session}`);
    assert(summary.unavailable === false, "model unavailable");
    assert(summary.network === false, "browser could not reach the API");
    assert(summary.lengths.every((length) => length > 0), "empty reply");
    process.stdout.write(
      `live ui ok replies=${summary.replies} lengths=${summary.lengths.join(",")} session=${summary.session}\n`,
    );
  } catch (error) {
    const line = (apiError.split("\n").find((item) => item.startsWith("error:")) || "").slice(0, 200);
    if (line) process.stderr.write(`${line}\n`);
    throw error;
  } finally {
    api.kill("SIGKILL");
    if (typeof web.closeAllConnections === "function") web.closeAllConnections();
    web.close();
    browser.kill("SIGKILL");
    await delay(200);
    await rm(profile, { recursive: true, force: true }).catch(() => {});
  }
}

function serveWeb(port, directory, apiBase) {
  const types = { ".html": "text/html", ".css": "text/css", ".js": "text/javascript" };
  const server = createServer(async (request, response) => {
    const url = new URL(request.url || "/", "http://127.0.0.1");
    let name = url.pathname === "/" ? "index.html" : url.pathname.slice(1);
    if (name.includes("..")) {
      response.writeHead(404);
      response.end();
      return;
    }
    const file = path.join(directory, name);
    try {
      if (name.endsWith(".html")) {
        const html = await readFile(file, "utf8");
        const stamped = html.replace("<body", `<body data-api-base="${apiBase}"`);
        response.writeHead(200, { "content-type": "text/html; charset=utf-8" });
        response.end(stamped);
        return;
      }
      const body = await readFile(file);
      response.writeHead(200, { "content-type": types[path.extname(file)] || "text/plain" });
      response.end(body);
    } catch {
      response.writeHead(404);
      response.end();
    }
  });
  return new Promise((resolve) => {
    server.listen(port, "127.0.0.1", () => resolve(server));
  });
}

main().catch((error) => {
  process.stderr.write(`${error.message || error}\n`);
  process.exit(1);
});
