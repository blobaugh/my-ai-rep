import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import vm from "node:vm";

const source = readFileSync(new URL("./widget.js", import.meta.url), "utf8");

function load() {
  const context = { URL };
  vm.createContext(context);
  vm.runInContext(source, context);
  return context.PersonaChatWidget;
}

test("origin comes from the script src", () => {
  const api = load();
  assert.equal(api.chatOrigin("https://bot.example.com/widget.js"), "https://bot.example.com");
  assert.equal(api.chatOrigin("not a url"), "");
  assert.equal(api.mounted, false);
});

test("options stay minimal and accept title or label", () => {
  const api = load();
  const right = api.readOptions({ dataset: {} });
  assert.equal(right.position, "right");
  assert.equal(right.zIndex, "2147483000");
  assert.equal(right.title, "");
  assert.equal(right.label, "");
  assert.equal(right.ariaLabel, "Open chat");
  const left = api.readOptions({
    dataset: {
      position: "left",
      zIndex: "20",
      title: " BenBot is an AI ",
      label: "Ask",
      ariaLabel: "Open BenBot",
    },
  });
  assert.equal(left.position, "left");
  assert.equal(left.zIndex, "20");
  assert.equal(left.title, "BenBot is an AI");
  assert.equal(left.label, "Ask");
  assert.equal(left.ariaLabel, "Open BenBot");
  const junk = api.readOptions({ dataset: { position: "top", zIndex: "nope" } });
  assert.equal(junk.position, "right");
  assert.equal(junk.zIndex, "2147483000");
});

test("headerTitle prefers data-title, then config, then a fallback", () => {
  const api = load();
  assert.equal(api.headerTitle({ title: "Custom title" }, { ai_label: "Ignored" }), "Custom title");
  assert.equal(
    api.headerTitle({ title: "" }, { ai_label: "BenBot is an AI that speaks for Ben." }),
    "BenBot is an AI that speaks for Ben.",
  );
  assert.equal(api.headerTitle({ title: "" }, { bot_name: "BenBot" }), "BenBot is an AI");
  assert.equal(api.headerTitle({ title: "" }, null), "Chat assistant");
});

test("a narrow window is a sheet", () => {
  const api = load();
  assert.equal(api.sheetForWidth(720), true);
  assert.equal(api.sheetForWidth(721), false);
});

test("the script is one file with no markup injection", () => {
  assert.equal(source.includes("innerHTML"), false);
  assert.equal(source.includes("import "), false);
  assert.equal(source.includes("console."), false);
  assert.equal(source.includes("prefers-color-scheme:dark"), true);
  assert.equal(source.includes("/embed?widget=1"), true);
  assert.equal(source.includes("createElementNS"), true);
});
