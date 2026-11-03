/* One file. No build. The host page loads it with defer.
   The chat origin is this script's own src. */
(function (root, doc) {
  function chatOrigin(src) {
    try {
      return new URL(src).origin;
    } catch (error) {
      return "";
    }
  }

  function readOptions(script) {
    var position = script && script.dataset && script.dataset.position === "left" ? "left" : "right";
    var raw = script && script.dataset ? script.dataset.zIndex || "" : "";
    var zIndex = /^[0-9]{1,8}$/.test(raw) ? raw : "2147483000";
    return { position: position, zIndex: zIndex };
  }

  function sheetForWidth(width) {
    return Number(width) <= 720;
  }

  if (root.BenBotWidget && root.BenBotWidget.mounted) return;

  var script = doc && doc.currentScript;
  root.BenBotWidget = {
    version: 1,
    mounted: false,
    chatOrigin: chatOrigin,
    readOptions: readOptions,
    sheetForWidth: sheetForWidth,
  };
  if (!doc || !script || !script.src) return;

  var origin = chatOrigin(script.src);
  if (!origin) return;
  var options = readOptions(script);
  root.BenBotWidget.mounted = true;

  function mount() {
    var host = doc.createElement("div");
    host.setAttribute("data-benbot-widget", "");
    host.setAttribute("data-side", options.position);
    host.style.position = "fixed";
    host.style.bottom = "calc(16px + env(safe-area-inset-bottom))";
    host.style.zIndex = options.zIndex;
    if (options.position === "left") {
      host.style.left = "calc(16px + env(safe-area-inset-left))";
      host.style.right = "auto";
    } else {
      host.style.right = "calc(16px + env(safe-area-inset-right))";
      host.style.left = "auto";
    }
    var shadow = host.attachShadow({ mode: "open" });
    var style = doc.createElement("style");
    style.textContent = css();
    var bubble = doc.createElement("button");
    bubble.type = "button";
    bubble.className = "bubble";
    bubble.setAttribute("aria-label", "Chat with BenBot, an AI");
    bubble.setAttribute("aria-expanded", "false");
    bubble.textContent = "Chat";
    shadow.append(style, bubble);
    doc.body.append(host);

    var panel = null;
    var frame = null;
    var open = false;
    var previousOverflow = null;

    function isSheet() {
      return sheetForWidth(root.innerWidth);
    }

    function ensurePanel() {
      if (panel) return;
      panel = doc.createElement("section");
      panel.className = "panel";
      panel.setAttribute("role", "dialog");
      panel.setAttribute("aria-label", "Chat with BenBot, an AI");
      var header = doc.createElement("div");
      header.className = "bar";
      var title = doc.createElement("p");
      title.textContent = "BenBot is an AI";
      var close = doc.createElement("button");
      close.type = "button";
      close.className = "close";
      close.textContent = "Close";
      close.addEventListener("click", function () {
        setOpen(false);
      });
      header.append(title, close);
      frame = doc.createElement("iframe");
      frame.title = "Chat with BenBot, an AI";
      frame.src = origin + "/embed";
      panel.append(header, frame);
      shadow.append(panel);
    }

    function lockScroll() {
      if (previousOverflow) return;
      previousOverflow = {
        html: doc.documentElement.style.overflow,
        body: doc.body.style.overflow,
      };
      doc.documentElement.style.overflow = "hidden";
      doc.body.style.overflow = "hidden";
    }

    function unlockScroll() {
      if (!previousOverflow) return;
      doc.documentElement.style.overflow = previousOverflow.html;
      doc.body.style.overflow = previousOverflow.body;
      previousOverflow = null;
    }

    function setOpen(next) {
      if (next) {
        ensurePanel();
        panel.classList.toggle("sheet", isSheet());
        panel.hidden = false;
        open = true;
        bubble.setAttribute("aria-expanded", "true");
        if (isSheet()) lockScroll();
        else unlockScroll();
        frame.focus();
        return;
      }
      if (!panel) return;
      panel.hidden = true;
      open = false;
      bubble.setAttribute("aria-expanded", "false");
      unlockScroll();
      bubble.focus();
    }

    bubble.addEventListener("click", function () {
      setOpen(!open);
    });
    doc.addEventListener("keydown", function (event) {
      if (event.key === "Escape" && open) setOpen(false);
    });
    root.addEventListener("resize", function () {
      if (!open || !panel) return;
      panel.classList.toggle("sheet", isSheet());
      if (isSheet()) lockScroll();
      else unlockScroll();
    });
  }

  if (doc.body) mount();
  else doc.addEventListener("DOMContentLoaded", mount);

  function css() {
    return [
      ":host{all:initial;position:fixed;bottom:calc(16px + env(safe-area-inset-bottom));right:calc(16px + env(safe-area-inset-right));left:auto;font-family:system-ui,sans-serif;color:#1c1915;}",
      ":host([data-side=left]){left:calc(16px + env(safe-area-inset-left));right:auto;}",
      ".bubble{width:56px;height:56px;border:0;border-radius:999px;background:#1f4e3d;color:#f4fff8;font:700 14px/1 system-ui,sans-serif;cursor:pointer;}",
      ".bubble:hover{filter:brightness(1.12);}",
      ".bubble:focus-visible,.close:focus-visible{outline:3px solid #0b57d0;outline-offset:3px;}",
      ".panel{position:absolute;right:0;bottom:72px;width:min(380px,calc(100vw - 32px));height:min(600px,calc(100dvh - 96px));display:flex;flex-direction:column;background:#fffdf8;color:#1c1915;border-radius:16px;overflow:hidden;box-shadow:0 12px 40px rgb(28 25 21 / 28%);}",
      ":host([data-side=left]) .panel{left:0;right:auto;}",
      ".panel[hidden]{display:none;}",
      ".panel.sheet{position:fixed;inset:0;width:100%;height:100dvh;border-radius:0;}",
      ".bar{display:flex;align-items:center;justify-content:space-between;gap:8px;min-height:44px;padding:4px 8px 4px 12px;background:#1f4e3d;color:#f4fff8;}",
      ".bar p{margin:0;font:700 15px/1.2 system-ui,sans-serif;}",
      ".close{min-width:44px;min-height:44px;border:0;border-radius:10px;background:transparent;color:#f4fff8;font:inherit;cursor:pointer;}",
      "iframe{flex:1;width:100%;border:0;background:#fffdf8;}",
      "@media (max-width:720px){.bubble{width:48px;height:48px;}}",
    ].join("");
  }
})(typeof window === "undefined" ? globalThis : window, typeof document === "undefined" ? null : document);
