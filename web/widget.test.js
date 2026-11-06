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

test("options stay minimal", () => {
  const api = load();
  const right = api.readOptions({ dataset: {} });
  assert.equal(right.position, "right");
  assert.equal(right.zIndex, "2147483000");
  const left = api.readOptions({ dataset: { position: "left", zIndex: "20" } });
  assert.equal(left.position, "left");
  assert.equal(left.zIndex, "20");
  const junk = api.readOptions({ dataset: { position: "top", zIndex: "nope" } });
  assert.equal(junk.position, "right");
  assert.equal(junk.zIndex, "2147483000");
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
});
