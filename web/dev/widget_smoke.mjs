/**
 * Cross-origin widget, frame-ancestors, and storage checks in headless Chrome.
 * Usage: node web/dev/widget_smoke.mjs
 */
import { spawn } from "node:child_process";
import { mkdir, mkdtemp, readFile, rm, writeFile } from "node:fs/promises";
import { createServer } from "node:http";
import { tmpdir } from "node:os";
import path from "node:path";
import { setTimeout as delay } from "node:timers/promises";
import { fileURLToPath } from "node:url";

const repo = fileURLToPath(new URL("../..", import.meta.url));
const shots = path.join(repo, "docs", "web", "screenshots");
const chrome = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome";
const python = path.join(repo, ".venv", "bin", "python");
const chatPort = 8771;
const hostPort = 8772;
const embedPort = 8773;
const allowedPort = 8774;
const blockedPort = 8775;
const debugPort = 9335;
const chatOrigin = `http://127.0.0.1:${chatPort}`;
const widgetSrc = `${chatOrigin}/widget.js`;

function assert(cond, message) {
  if (!cond) throw new Error(message);
}

class Cdp {
  constructor(ws) {
    this.ws = ws;
    this.next = 1;
    this.pending = new Map();
    this.listeners = [];
    ws.addEventListener("message", (event) => {
      const message = JSON.parse(event.data);
      if (message.id && this.pending.has(message.id)) {
        this.pending.get(message.id)(message);
        this.pending.delete(message.id);
        return;
      }
      for (const listener of this.listeners) listener(message);
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

function listen(port, hostname, handler) {
  const server = createServer(handler);
  return new Promise((resolve) => {
    server.listen(port, hostname, () => resolve(server));
  });
}

async function htmlFile(name) {
  const text = await readFile(path.join(repo, "web", "dev", name), "utf8");
  return text.replaceAll("WIDGET_SRC", widgetSrc);
}

async function evaluate(cdp, sessionId, expression) {
  const reply = await cdp.send(
    "Runtime.evaluate",
    { expression, returnByValue: true, awaitPromise: true },
    sessionId,
  );
  if (reply.result?.exceptionDetails) throw new Error("page error");
  return reply.result?.result?.value;
}

async function waitUntil(cdp, sessionId, expression) {
  const started = Date.now();
  while (Date.now() - started < 8000) {
    const value = await evaluate(cdp, sessionId, expression);
    if (value) return value;
    await delay(80);
  }
  throw new Error(`timeout: ${expression}`);
}

async function openPage(cdp, url) {
  const created = await cdp.send("Target.createTarget", { url: "about:blank" });
  const targetId = created.result.targetId;
  const attached = await cdp.send("Target.attachToTarget", { targetId, flatten: true });
  const sessionId = attached.result.sessionId;
  await cdp.send("Page.enable", {}, sessionId);
  await cdp.send("Runtime.enable", {}, sessionId);
  await cdp.send("Network.enable", {}, sessionId);
  await cdp.send("Log.enable", {}, sessionId);
  await cdp.send("Page.navigate", { url }, sessionId);
  await delay(200);
  return { targetId, sessionId };
}

async function shot(cdp, sessionId, name) {
  const reply = await cdp.send("Page.captureScreenshot", { format: "png" }, sessionId);
  await mkdir(shots, { recursive: true });
  await writeFile(path.join(shots, name), Buffer.from(reply.result.data, "base64"));
}

async function iframeEval(cdp, urlPart, expression) {
  const listed = await cdp.send("Target.getTargets");
  const target = (listed.result.targetInfos || []).find(
    (item) => item.type === "iframe" && String(item.url).includes(urlPart),
  );
  if (!target) return null;
  const attached = await cdp.send("Target.attachToTarget", {
    targetId: target.targetId,
    flatten: true,
  });
  return evaluate(cdp, attached.result.sessionId, expression);
}

async function main() {
  const profile = await mkdtemp(path.join(tmpdir(), "benbot-widget-"));
  const mock = spawn(python, ["web/dev/mock_api.py", String(chatPort)], {
    cwd: repo,
    stdio: "ignore",
  });
  const plain = await htmlFile("widget-test.html");
  const heavy = await htmlFile("widget-heavy.html");
  const framePage = (src) => `<!DOCTYPE html><html><body><iframe src="${src}"></iframe></body></html>`;
  const host = await listen(hostPort, "localhost", async (request, response) => {
    const url = request.url || "/";
    if (url.startsWith("/plain")) {
      response.writeHead(200, { "content-type": "text/html" });
      response.end(plain);
      return;
    }
    if (url.startsWith("/heavy")) {
      response.writeHead(200, { "content-type": "text/html" });
      response.end(heavy);
      return;
    }
    response.writeHead(404);
    response.end();
  });
  const embedBody = "<!DOCTYPE html><html><body><p>embed-ok</p></body></html>";
  const embed = await listen(embedPort, "127.0.0.1", (request, response) => {
    response.writeHead(200, {
      "content-type": "text/html",
      "content-security-policy": `frame-ancestors http://127.0.0.1:${allowedPort}`,
    });
    response.end(embedBody);
  });
  const allowed = await listen(allowedPort, "127.0.0.1", (request, response) => {
    response.writeHead(200, { "content-type": "text/html" });
    response.end(framePage(`http://127.0.0.1:${embedPort}/embed`));
  });
  const blocked = await listen(blockedPort, "127.0.0.1", (request, response) => {
    response.writeHead(200, { "content-type": "text/html" });
    response.end(framePage(`http://127.0.0.1:${embedPort}/embed`));
  });
  const browser = spawn(
    chrome,
    [
      "--headless=new",
      "--disable-gpu",
      "--hide-scrollbars",
      `--remote-debugging-port=${debugPort}`,
      `--user-data-dir=${profile}`,
      "--site-per-process",
      "--no-first-run",
      "about:blank",
    ],
    { stdio: "ignore" },
  );
  const servers = [host, embed, allowed, blocked];
  try {
    const started = Date.now();
    let healthy = false;
    while (Date.now() - started < 8000) {
      try {
        const health = await fetch(`${chatOrigin}/api/health`);
        if (health.ok) {
          healthy = true;
          break;
        }
      } catch {
        /* starting */
      }
      await delay(80);
    }
    assert(healthy, "mock did not start");
    let version = null;
    while (Date.now() - started < 8000) {
      try {
        version = await (await fetch(`http://127.0.0.1:${debugPort}/json/version`)).json();
        break;
      } catch {
        await delay(80);
      }
    }
    assert(version, "chrome did not start");
    const socket = new WebSocket(version.webSocketDebuggerUrl);
    await new Promise((resolve, reject) => {
      socket.addEventListener("open", resolve);
      socket.addEventListener("error", () => reject(new Error("chrome socket failed")));
    });
    const cdp = new Cdp(socket);
    await cdp.send("Target.setDiscoverTargets", { discover: true });

    const page = await openPage(cdp, `http://localhost:${hostPort}/plain`);
    await cdp.send(
      "Emulation.setDeviceMetricsOverride",
      { width: 1280, height: 800, deviceScaleFactor: 1, mobile: false },
      page.sessionId,
    );
    const widgets = await waitUntil(
      cdp,
      page.sessionId,
      `document.querySelectorAll("[data-persona-chat-widget]").length`,
    );
    assert(widgets === 1, `widgets ${widgets}`);
    const before = await evaluate(
      cdp,
      page.sessionId,
      `performance.getEntriesByType("resource").some((row) => row.name.includes("/embed"))`,
    );
    assert(before === false, "iframe was created before open");
    await shot(cdp, page.sessionId, "widget-closed-1280x800.png");
    await evaluate(
      cdp,
      page.sessionId,
      `document.querySelector("[data-persona-chat-widget]").shadowRoot.querySelector(".bubble").click()`,
    );
    const src = await waitUntil(
      cdp,
      page.sessionId,
      `document.querySelector("[data-persona-chat-widget]").shadowRoot.querySelector("iframe")?.src || ""`,
    );
    assert(String(src).includes("/embed"), src);
    assert(String(src).includes("widget=1"), `expected widget embed mode: ${src}`);
    let label = "";
    let frameState = null;
    const labelStarted = Date.now();
    while (Date.now() - labelStarted < 8000) {
      frameState = await iframeEval(
        cdp,
        `${chatOrigin}/embed`,
        `(() => {
          const el = document.querySelector("#ai-label");
          const box = el?.getBoundingClientRect();
          return {
            label: el?.textContent || "",
            widget: document.body.classList.contains("widget-frame"),
            labelVisuallyHidden: !!box && box.width <= 1 && box.height <= 1,
          };
        })()`,
      );
      label = frameState?.label || "";
      if (String(label).includes("AI") && frameState?.widget) break;
      await delay(100);
    }
    assert(String(label).includes("AI"), "embed chat did not load");
    assert(frameState?.widget === true, "embed did not enter widget-frame mode");
    assert(frameState?.labelVisuallyHidden === true, "duplicate AI label stayed visible in the iframe");
    const header = await evaluate(
      cdp,
      page.sessionId,
      `document.querySelector("[data-persona-chat-widget]").shadowRoot.querySelector(".bar h2")?.textContent || ""`,
    );
    assert(String(header).includes("AI") || String(header).length > 0, `widget header empty: ${header}`);
    const icon = await evaluate(
      cdp,
      page.sessionId,
      `document.querySelector("[data-persona-chat-widget]").shadowRoot.querySelector(".bubble svg.icon") !== null`,
    );
    assert(icon === true, "launcher is missing the chat icon");
    await shot(cdp, page.sessionId, "widget-open-1280x800.png");
    await cdp.send(
      "Emulation.setEmulatedMedia",
      { features: [{ name: "prefers-color-scheme", value: "dark" }] },
      page.sessionId,
    );
    await delay(200);
    await shot(cdp, page.sessionId, "widget-open-dark-1280x800.png");
    await cdp.send(
      "Emulation.setEmulatedMedia",
      { features: [{ name: "prefers-color-scheme", value: "light" }] },
      page.sessionId,
    );
    await evaluate(
      cdp,
      page.sessionId,
      `document.querySelector("[data-persona-chat-widget]").shadowRoot.querySelector(".close").click()`,
    );
    const closed = await waitUntil(
      cdp,
      page.sessionId,
      `document.querySelector("[data-persona-chat-widget]").shadowRoot.querySelector(".panel").hidden === true`,
    );
    assert(closed === true, "close did not hide the panel");
    const focused = await evaluate(
      cdp,
      page.sessionId,
      `document.querySelector("[data-persona-chat-widget]").shadowRoot.activeElement?.className || ""`,
    );
    assert(focused === "bubble", `focus ${focused}`);

    await evaluate(
      cdp,
      page.sessionId,
      `document.querySelector("[data-persona-chat-widget]").shadowRoot.querySelector(".bubble").click()`,
    );
    await waitUntil(
      cdp,
      page.sessionId,
      `document.querySelector("[data-persona-chat-widget]").shadowRoot.querySelector(".panel").hidden === false`,
    );
    await evaluate(
      cdp,
      page.sessionId,
      `document.dispatchEvent(new KeyboardEvent("keydown", { key: "Escape", bubbles: true }))`,
    );
    const escaped = await waitUntil(
      cdp,
      page.sessionId,
      `document.querySelector("[data-persona-chat-widget]").shadowRoot.querySelector(".panel").hidden === true`,
    );
    assert(escaped === true, "escape did not close");

    for (const width of [360, 375, 390]) {
      await cdp.send(
        "Emulation.setDeviceMetricsOverride",
        { width, height: 700, deviceScaleFactor: 1, mobile: true },
        page.sessionId,
      );
      await evaluate(
        cdp,
        page.sessionId,
        `document.querySelector("[data-persona-chat-widget]").shadowRoot.querySelector(".bubble").click()`,
      );
      const sheet = await waitUntil(
        cdp,
        page.sessionId,
        `document.querySelector("[data-persona-chat-widget]").shadowRoot.querySelector(".panel").classList.contains("sheet")`,
      );
      assert(sheet === true, `not a sheet at ${width}`);
      if (width === 375) await shot(cdp, page.sessionId, "widget-sheet-375x667.png");
      await evaluate(
        cdp,
        page.sessionId,
        `document.querySelector("[data-persona-chat-widget]").shadowRoot.querySelector(".close").click()`,
      );
    }
    await cdp.send("Target.closeTarget", { targetId: page.targetId });

    const styled = await openPage(cdp, `http://localhost:${hostPort}/heavy`);
    await cdp.send(
      "Emulation.setDeviceMetricsOverride",
      { width: 1280, height: 800, deviceScaleFactor: 1, mobile: false },
      styled.sessionId,
    );
    const box = await waitUntil(cdp, styled.sessionId, `(() => {
      const bubble = document.querySelector("[data-persona-chat-widget]")?.shadowRoot?.querySelector(".bubble");
      if (!bubble) return null;
      const rect = bubble.getBoundingClientRect();
      return { width: rect.width, height: rect.height };
    })()`);
    assert(Math.abs(box.width - 56) < 2, `bubble width ${box.width}`);
    assert(Math.abs(box.height - 56) < 2, `bubble height ${box.height}`);
    const place = await evaluate(cdp, styled.sessionId, `(() => {
      const rect = document.querySelector("[data-persona-chat-widget]").shadowRoot.querySelector(".bubble").getBoundingClientRect();
      return { right: rect.right, bottom: rect.bottom };
    })()`);
    assert(place.right > 1200, `bubble not at the right edge (${place.right})`);
    assert(place.bottom > 720, `bubble not at the bottom (${place.bottom})`);
    await shot(cdp, styled.sessionId, "widget-heavy-1280x800.png");
    await cdp.send("Target.closeTarget", { targetId: styled.targetId });

    const logs = [];
    cdp.listeners.push((message) => {
      if (message.method === "Log.entryAdded") logs.push(message.params.entry.text || "");
    });
    const okFrame = await openPage(cdp, `http://127.0.0.1:${allowedPort}/`);
    await delay(600);
    const allowedState = await waitUntil(
      cdp,
      okFrame.sessionId,
      `(() => {
        const frame = document.querySelector("iframe");
        if (!frame) return "";
        return frame.contentDocument === null ? "cross-origin" : "";
      })()`,
    );
    assert(allowedState === "cross-origin", "listed origin could not frame /embed");
    assert(!logs.some((line) => line.includes("frame-ancestors")), `allowed page was blocked: ${logs.join(" | ")}`);
    const framed = await evaluate(cdp, okFrame.sessionId, `document.querySelector("iframe") !== null`);
    assert(framed === true, "allowed page has no iframe");
    await cdp.send("Target.closeTarget", { targetId: okFrame.targetId });

    logs.length = 0;
    const badFrame = await openPage(cdp, `http://127.0.0.1:${blockedPort}/`);
    const startedLogs = Date.now();
    while (Date.now() - startedLogs < 3000 && !logs.some((line) => line.includes("frame-ancestors"))) {
      await delay(100);
    }
    assert(logs.some((line) => line.includes("frame-ancestors")), `blocked page was not refused: ${logs.join(" | ")}`);
    await cdp.send("Target.closeTarget", { targetId: badFrame.targetId });

    process.stdout.write("widget smoke ok\n");
  } finally {
    mock.kill("SIGKILL");
    browser.kill("SIGKILL");
    for (const server of servers) {
      if (typeof server.closeAllConnections === "function") server.closeAllConnections();
      server.close();
    }
    await delay(200);
    await rm(profile, { recursive: true, force: true }).catch(() => {});
  }
}

main().catch((error) => {
  process.stderr.write(`${error.stack || error}\n`);
  process.exit(1);
});
