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
    var data = script && script.dataset ? script.dataset : {};
    var position = data.position === "left" ? "left" : "right";
    var raw = data.zIndex || "";
    var zIndex = /^[0-9]{1,8}$/.test(raw) ? raw : "2147483000";
    var title = typeof data.title === "string" ? data.title.trim() : "";
    var label = typeof data.label === "string" ? data.label.trim() : "";
    var ariaLabel =
      typeof data.ariaLabel === "string" && data.ariaLabel.trim()
        ? data.ariaLabel.trim()
        : "Open chat";
    return {
      position: position,
      zIndex: zIndex,
      title: title,
      label: label,
      ariaLabel: ariaLabel,
    };
  }

  function sheetForWidth(width) {
    return Number(width) <= 720;
  }

  function headerTitle(options, config) {
    if (options && options.title) return options.title;
    if (config && typeof config.ai_label === "string" && config.ai_label.trim()) {
      return config.ai_label.trim();
    }
    if (config && typeof config.bot_name === "string" && config.bot_name.trim()) {
      return config.bot_name.trim() + " is an AI";
    }
    return "Chat assistant";
  }

  if (root.PersonaChatWidget && root.PersonaChatWidget.mounted) return;
  if (root.BenBotWidget && root.BenBotWidget.mounted) return;

  var script = doc && doc.currentScript;
  var api = {
    version: 3,
    mounted: false,
    chatOrigin: chatOrigin,
    readOptions: readOptions,
    sheetForWidth: sheetForWidth,
    headerTitle: headerTitle,
  };
  root.PersonaChatWidget = api;
  /* Legacy embeds: keep alias until everyone migrates (see README breaking changes). */
  root.BenBotWidget = api;
  if (!doc || !script || !script.src) return;

  var origin = chatOrigin(script.src);
  if (!origin) return;
  var options = readOptions(script);
  api.mounted = true;

  function chatIcon() {
    var svg = doc.createElementNS("http://www.w3.org/2000/svg", "svg");
    svg.setAttribute("viewBox", "0 0 24 24");
    svg.setAttribute("aria-hidden", "true");
    svg.setAttribute("focusable", "false");
    svg.classList.add("icon");
    var path = doc.createElementNS("http://www.w3.org/2000/svg", "path");
    path.setAttribute(
      "d",
      "M4.5 5.75A2.25 2.25 0 0 1 6.75 3.5h10.5a2.25 2.25 0 0 1 2.25 2.25v8a2.25 2.25 0 0 1-2.25 2.25H11.1L7 19.5v-3.5H6.75A2.25 2.25 0 0 1 4.5 13.75v-8z",
    );
    path.setAttribute("fill", "currentColor");
    svg.appendChild(path);
    return svg;
  }

  function mount() {
    var host = doc.createElement("div");
    host.setAttribute("data-persona-chat-widget", "");
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
    bubble.className = options.label ? "bubble labeled" : "bubble";
    bubble.setAttribute("aria-label", options.ariaLabel);
    bubble.setAttribute("aria-expanded", "false");
    if (options.label) {
      bubble.textContent = options.label;
    } else {
      bubble.appendChild(chatIcon());
    }
    shadow.append(style, bubble);
    doc.body.append(host);

    var panel = null;
    var frame = null;
    var titleEl = null;
    var open = false;
    var previousOverflow = null;
    var resolvedTitle = headerTitle(options, null);

    function applyTitle(text) {
      resolvedTitle = text || resolvedTitle;
      if (titleEl) titleEl.textContent = resolvedTitle;
      if (panel) panel.setAttribute("aria-label", resolvedTitle);
      if (frame) frame.title = resolvedTitle;
    }

    function loadTitle() {
      if (options.title) {
        applyTitle(options.title);
        return;
      }
      try {
        fetch(origin + "/api/config", { credentials: "omit" })
          .then(function (response) {
            if (!response.ok) return null;
            return response.json();
          })
          .then(function (config) {
            if (!config) return;
            applyTitle(headerTitle(options, config));
          })
          .catch(function () {});
      } catch (error) {
        /* ignore */
      }
    }

    function isSheet() {
      return sheetForWidth(root.innerWidth);
    }

    function ensurePanel() {
      if (panel) return;
      panel = doc.createElement("section");
      panel.className = "panel";
      panel.setAttribute("role", "dialog");
      panel.setAttribute("aria-label", resolvedTitle);
      panel.hidden = true;
      var header = doc.createElement("div");
      header.className = "bar";
      titleEl = doc.createElement("p");
      titleEl.textContent = resolvedTitle;
      var close = doc.createElement("button");
      close.type = "button";
      close.className = "close";
      close.setAttribute("aria-label", "Close chat");
      close.textContent = "Close";
      close.addEventListener("click", function () {
        setOpen(false);
      });
      header.append(titleEl, close);
      frame = doc.createElement("iframe");
      frame.title = resolvedTitle;
      frame.src = origin + "/embed?widget=1";
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
        host.setAttribute("data-open", "");
        if (isSheet()) lockScroll();
        else unlockScroll();
        frame.focus();
        return;
      }
      if (!panel) return;
      panel.hidden = true;
      open = false;
      bubble.setAttribute("aria-expanded", "false");
      host.removeAttribute("data-open");
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

    loadTitle();
  }

  if (doc.body) mount();
  else doc.addEventListener("DOMContentLoaded", mount);

  function css() {
    return [
      ":host{all:initial;position:fixed;bottom:calc(16px + env(safe-area-inset-bottom));right:calc(16px + env(safe-area-inset-right));left:auto;font-family:system-ui,sans-serif;color:#1c1915;--panel-bg:#fffdf8;--panel-text:#1c1915;--bar-bg:#1f4e3d;--bar-text:#f4fff8;--bubble-bg:#1f4e3d;--bubble-text:#f4fff8;--focus:#0b57d0;--shadow:0 12px 40px rgb(28 25 21 / 28%);}",
      ":host([data-side=left]){left:calc(16px + env(safe-area-inset-left));right:auto;}",
      "@media (prefers-color-scheme:dark){:host{color:#f3efe6;--panel-bg:#141311;--panel-text:#f3efe6;--bar-bg:#1a3d30;--bar-text:#f4fff8;--bubble-bg:#2f6d56;--bubble-text:#f4fff8;--focus:#9ec1ff;--shadow:0 12px 40px rgb(0 0 0 / 55%);}}",
      ".bubble{display:inline-flex;align-items:center;justify-content:center;width:56px;height:56px;padding:0;border:0;border-radius:999px;background:var(--bubble-bg);color:var(--bubble-text);font:700 14px/1 system-ui,sans-serif;cursor:pointer;box-shadow:var(--shadow);transition:transform .18s ease,filter .18s ease;}",
      ".bubble.labeled{width:auto;min-width:56px;padding:0 16px;}",
      ".bubble .icon{width:24px;height:24px;display:block;}",
      ".bubble:hover{filter:brightness(1.12);}",
      ".bubble:focus-visible,.close:focus-visible{outline:3px solid var(--focus);outline-offset:3px;}",
      ".panel{position:absolute;right:0;bottom:72px;width:min(380px,calc(100vw - 32px));height:min(600px,calc(100dvh - 96px));display:flex;flex-direction:column;background:var(--panel-bg);color:var(--panel-text);border-radius:16px;overflow:hidden;box-shadow:var(--shadow);transform-origin:bottom right;animation:panel-in .18s ease;}",
      ":host([data-side=left]) .panel{left:0;right:auto;transform-origin:bottom left;}",
      ".panel[hidden]{display:none;}",
      ".panel.sheet{position:fixed;inset:0;width:100%;height:100dvh;border-radius:0;transform-origin:center;}",
      "@keyframes panel-in{from{opacity:0;transform:translateY(8px) scale(.98)}to{opacity:1;transform:none}}",
      ".bar{display:flex;align-items:center;justify-content:space-between;gap:8px;min-height:44px;padding:4px 8px 4px 12px;background:var(--bar-bg);color:var(--bar-text);}",
      ".bar p{margin:0;font:700 15px/1.2 system-ui,sans-serif;overflow-wrap:anywhere;}",
      ".close{min-width:44px;min-height:44px;border:0;border-radius:10px;background:transparent;color:var(--bar-text);font:inherit;cursor:pointer;}",
      "iframe{flex:1;width:100%;border:0;background:var(--panel-bg);}",
      "@media (max-width:720px){.bubble:not(.labeled){width:48px;height:48px;}}",
      "@media (prefers-reduced-motion:reduce){.bubble{transition:none;}.panel{animation:none;}}",
    ].join("");
  }
})(typeof window === "undefined" ? globalThis : window, typeof document === "undefined" ? null : document);
