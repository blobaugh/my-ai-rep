/**
 * Load both chat pages against the mock and save status screenshots.
 * Usage: node web/dev/smoke.mjs
 */
import { spawn } from "node:child_process";
import { mkdir, mkdtemp, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import path from "node:path";
import { setTimeout as delay } from "node:timers/promises";
import { fileURLToPath } from "node:url";

const repo = fileURLToPath(new URL("../..", import.meta.url));
const shotsDir = path.join(repo, "docs", "web", "screenshots");
const chrome = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome";
const mockPort = 8765;
const debugPort = 9333;
const python = path.join(repo, ".venv", "bin", "python");

const states = [
  { name: "ready" },
  { name: "ok", message: "Hello" },
  { name: "session-full", message: "!full" },
  { name: "unavailable", message: "!down" },
  { name: "busy", message: "!busy" },
  { name: "daily-limit", message: "!limit" },
  { name: "error", message: "!error" },
  { name: "invalid", message: "!bad" },
  { name: "expired", message: "!expire", prime: true },
  { name: "xss", message: "!xss" },
  { name: "network", message: "Hello", fail: true },
];

const sizes = [
  [375, 667],
  [1280, 800],
];

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
        const { resolve } = this.pending.get(message.id);
        this.pending.delete(message.id);
        resolve(message);
        return;
      }
      for (const listener of this.listeners) listener(message);
    });
  }

  send(method, params = {}, sessionId) {
    const id = this.next++;
    const payload = { id, method, params };
    if (sessionId) payload.sessionId = sessionId;
    return new Promise((resolve, reject) => {
      this.pending.set(id, { resolve, reject });
      this.ws.send(JSON.stringify(payload));
    });
  }

  waitEvent(method, timeoutMs = 8000) {
    return new Promise((resolve, reject) => {
      const timer = setTimeout(() => {
        this.listeners = this.listeners.filter((item) => item !== onEvent);
        reject(new Error(`timeout waiting for ${method}`));
      }, timeoutMs);
      const onEvent = (message) => {
        if (message.method !== method) return;
        clearTimeout(timer);
        this.listeners = this.listeners.filter((item) => item !== onEvent);
        resolve(message.params);
      };
      this.listeners.push(onEvent);
    });
  }
}

async function waitForJson(url) {
  const started = Date.now();
  while (Date.now() - started < 8000) {
    try {
      const response = await fetch(url);
      if (response.ok) return response.json();
    } catch {
      /* server still starting */
    }
    await delay(100);
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
    throw new Error(JSON.stringify(reply.result.exceptionDetails));
  }
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
  const loaded = cdp.waitEvent("Page.loadEventFired");
  await cdp.send("Page.navigate", { url }, sessionId);
  await loaded;
  return { targetId, sessionId };
}

async function sendChat(cdp, sessionId, message) {
  const before = await evaluate(
    cdp,
    sessionId,
    `document.querySelectorAll(".msg.visitor").length`,
  );
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
  await waitUntil(
    cdp,
    sessionId,
    `document.querySelector(".typing") === null && document.querySelectorAll(".msg.visitor").length > ${before}`,
  );
}

async function shot(cdp, sessionId, file) {
  const reply = await cdp.send("Page.captureScreenshot", { format: "png" }, sessionId);
  const bytes = Buffer.from(reply.result.data, "base64");
  await mkdir(shotsDir, { recursive: true });
  const { writeFile } = await import("node:fs/promises");
  await writeFile(file, bytes);
}

async function main() {
  const profile = await mkdtemp(path.join(tmpdir(), "benbot-chrome-"));
  const mock = spawn(python, ["web/dev/mock_api.py", String(mockPort)], {
    cwd: repo,
    stdio: ["ignore", "pipe", "pipe"],
  });
  const browser = spawn(
    chrome,
    [
      "--headless=new",
      "--disable-gpu",
      "--hide-scrollbars",
      `--remote-debugging-port=${debugPort}`,
      `--user-data-dir=${profile}`,
      "--no-first-run",
      "about:blank",
    ],
    { stdio: "ignore" },
  );
  try {
    await waitForJson(`http://127.0.0.1:${mockPort}/api/health`);
    const version = await waitForJson(`http://127.0.0.1:${debugPort}/json/version`);
    const cdp = new Cdp(new WebSocket(version.webSocketDebuggerUrl));
    await delay(100);

    for (const page of ["/", "/embed"]) {
      const opened = await openPage(cdp, `http://127.0.0.1:${mockPort}${page}`);
      const label = await waitUntil(
        cdp,
        opened.sessionId,
        `document.querySelector("#ai-label")?.textContent || ""`,
      );
      assert(String(label).includes("AI"), `${page} label: ${label}`);
      const ids = await evaluate(
        cdp,
        opened.sessionId,
        `["#messages","#message","#new-chat","#logging-notice","#copy-id"].every((sel) => document.querySelector(sel))`,
      );
      assert(ids === true, `${page} missing a control`);
      await cdp.send("Target.closeTarget", { targetId: opened.targetId });
    }

    const page = await openPage(cdp, `http://127.0.0.1:${mockPort}/`);
    await waitUntil(
      cdp,
      page.sessionId,
      `(document.querySelector("#ai-label")?.textContent || "").includes("AI")`,
    );

    const overflow = [];
    for (const width of [360, 375, 390, 768, 1280]) {
      await cdp.send(
        "Emulation.setDeviceMetricsOverride",
        { width, height: 800, deviceScaleFactor: 1, mobile: width < 800 },
        page.sessionId,
      );
      const wide = await evaluate(
        cdp,
        page.sessionId,
        `document.documentElement.scrollWidth > document.documentElement.clientWidth + 1`,
      );
      overflow.push([width, wide]);
    }
    assert(overflow.every((row) => row[1] === false), `horizontal scroll ${JSON.stringify(overflow)}`);

    await sendChat(cdp, page.sessionId, "!xss");
    const xss = await evaluate(
      cdp,
      page.sessionId,
      `(() => {
        const nodes = [...document.querySelectorAll(".msg.bot p")];
        const node = nodes[nodes.length - 1];
        return {
          text: node.textContent,
          html: node.innerHTML,
          images: document.images.length,
        };
      })()`,
    );
    assert(xss.text.includes("<script>"), "xss text was not literal");
    assert(xss.text.includes("<img"), "xss image text missing");
    assert(!xss.html.includes("<script>"), "xss became a script");
    assert(xss.images === 0, "xss created an image");

    await evaluate(cdp, page.sessionId, `document.querySelector("#new-chat").click()`);
    await waitUntil(
      cdp,
      page.sessionId,
      `document.querySelectorAll(".msg.visitor").length === 0`,
    );

    await sendChat(cdp, page.sessionId, "!down");
    const kept = await evaluate(cdp, page.sessionId, `document.querySelector("#message").value`);
    assert(kept === "!down", `draft not kept: ${kept}`);
    const botTexts = `[...document.querySelectorAll(".msg.bot p")].map((node) => node.textContent)`;
    const downTexts = await evaluate(cdp, page.sessionId, botTexts);
    assert(
      downTexts.filter((text) => text.includes("afterburners")).length === 1,
      `expected one afterburners bubble: ${JSON.stringify(downTexts)}`,
    );
    assert(
      downTexts[downTexts.length - 1].includes("not available"),
      `last reply after both attempts: ${downTexts[downTexts.length - 1]}`,
    );

    await evaluate(cdp, page.sessionId, `document.querySelector("#new-chat").click()`);
    await waitUntil(
      cdp,
      page.sessionId,
      `document.querySelectorAll(".msg.visitor").length === 0`,
    );
    await sendChat(cdp, page.sessionId, "!warm");
    const warmTexts = await evaluate(cdp, page.sessionId, botTexts);
    assert(
      warmTexts.some((text) => text.includes("afterburners")),
      `no afterburners bubble: ${JSON.stringify(warmTexts)}`,
    );
    assert(
      warmTexts[warmTexts.length - 1] === "Warmed up and ready.",
      `retry did not answer: ${warmTexts[warmTexts.length - 1]}`,
    );
    const warmVisitors = await evaluate(
      cdp,
      page.sessionId,
      `document.querySelectorAll(".msg.visitor").length`,
    );
    assert(warmVisitors === 1, `visitor bubble repeated: ${warmVisitors}`);

    await sendChat(cdp, page.sessionId, "!full");
    const restart = await evaluate(
      cdp,
      page.sessionId,
      `document.querySelector(".restart")?.textContent || ""`,
    );
    assert(restart === "Start a new chat", restart);

    const beforeKeys = await evaluate(
      cdp,
      page.sessionId,
      `document.querySelectorAll(".msg.visitor").length`,
    );
    await evaluate(
      cdp,
      page.sessionId,
      `(() => {
        const box = document.querySelector("#message");
        box.value = "line one";
        box.dispatchEvent(new KeyboardEvent("keydown", { key: "Enter", shiftKey: true, bubbles: true }));
        return box.value;
      })()`,
    );
    const afterShift = await evaluate(
      cdp,
      page.sessionId,
      `document.querySelectorAll(".msg.visitor").length`,
    );
    assert(afterShift === beforeKeys, "shift+enter sent a message");
    await evaluate(
      cdp,
      page.sessionId,
      `document.querySelector("#message").dispatchEvent(new KeyboardEvent("keydown", { key: "Enter", bubbles: true }))`,
    );
    await waitUntil(
      cdp,
      page.sessionId,
      `document.querySelector(".typing") === null && document.querySelectorAll(".msg.visitor").length > ${beforeKeys}`,
    );

    await cdp.send("Target.closeTarget", { targetId: page.targetId });

    for (const [width, height] of sizes) {
      for (const state of states) {
        const opened = await openPage(cdp, `http://127.0.0.1:${mockPort}/`);
        await cdp.send(
          "Emulation.setDeviceMetricsOverride",
          { width, height, deviceScaleFactor: 1, mobile: width < 800 },
          opened.sessionId,
        );
        await cdp.send(
          "Emulation.setEmulatedMedia",
          { features: [{ name: "prefers-color-scheme", value: "light" }] },
          opened.sessionId,
        );
        const reloaded = cdp.waitEvent("Page.loadEventFired");
        await cdp.send("Page.reload", {}, opened.sessionId);
        await reloaded;
        await waitUntil(
          cdp,
          opened.sessionId,
          `(document.querySelector("#ai-label")?.textContent || "").includes("AI")`,
        );
        if (state.fail) {
          await cdp.send(
            "Fetch.enable",
            { patterns: [{ urlPattern: "*://*/api/chat", requestStage: "Request" }] },
            opened.sessionId,
          );
          const failChat = (message) => {
            if (message.method !== "Fetch.requestPaused") return;
            if (message.sessionId !== opened.sessionId) return;
            void cdp.send(
              "Fetch.failRequest",
              { requestId: message.params.requestId, errorReason: "Failed" },
              opened.sessionId,
            );
          };
          cdp.listeners.push(failChat);
        }
        if (state.prime) {
          await sendChat(cdp, opened.sessionId, "Hello");
        }
        if (state.message) await sendChat(cdp, opened.sessionId, state.message);
        if (state.name === "expired") {
          const note = await evaluate(
            cdp,
            opened.sessionId,
            `document.querySelector(".session-note")?.textContent || ""`,
          );
          assert(note.includes("new conversation"), note);
        }
        const file = path.join(shotsDir, `${state.name}-${width}x${height}.png`);
        await shot(cdp, opened.sessionId, file);
        await cdp.send("Target.closeTarget", { targetId: opened.targetId });
        process.stdout.write(`shot ${path.basename(file)}\n`);
      }
    }

    const dark = await openPage(cdp, `http://127.0.0.1:${mockPort}/`);
    await cdp.send(
      "Emulation.setDeviceMetricsOverride",
      { width: 1280, height: 800, deviceScaleFactor: 1, mobile: false },
      dark.sessionId,
    );
    await cdp.send(
      "Emulation.setEmulatedMedia",
      { features: [{ name: "prefers-color-scheme", value: "dark" }] },
      dark.sessionId,
    );
    await cdp.send("Page.reload", {}, dark.sessionId);
    await delay(400);
    await waitUntil(
      cdp,
      dark.sessionId,
      `(document.querySelector("#ai-label")?.textContent || "").includes("AI")`,
    );
    await sendChat(cdp, dark.sessionId, "Hello");
    await shot(cdp, dark.sessionId, path.join(shotsDir, "ok-dark-1280x800.png"));
    await cdp.send("Target.closeTarget", { targetId: dark.targetId });
    process.stdout.write("smoke ok\n");
  } finally {
    mock.kill("SIGTERM");
    browser.kill("SIGKILL");
    await delay(200);
    await rm(profile, { recursive: true, force: true }).catch(() => {});
  }
}

main().catch((error) => {
  process.stderr.write(`${error.stack || error}\n`);
  process.exit(1);
});
