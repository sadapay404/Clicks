/* Clicks-Auto DOM recorder.
 *
 * Injected into every frame of the recorder browser.  It never records video:
 * it observes DOM events and reports a structured description of every action
 * (element identity + ranked selector candidates) back to Python through the
 * `window.__clicksAutoSend` binding.
 */
(() => {
  if (window.__clicksAutoRecorder) return;
  window.__clicksAutoRecorder = true;

  const STATE = {
    enabled: true,
    typing: false,
    recordScroll: false,
    recordHover: false,
    typingDelayMs: 700,
    typingMode: "fill", // fill | keystrokes
    lastEventAt: 0,
    pendingText: null,
    timers: {},
  };

  const send = (payload) => {
    if (typeof window.__clicksAutoSend !== "function") return;
    try {
      payload.ts = Date.now();
      window.__clicksAutoSend(JSON.stringify(payload));
    } catch (err) {
      /* binding gone (page closing) - ignore */
    }
  };

  /* ------------------------------------------------------------------ utils */

  const clean = (value) =>
    (value || "").replace(/\s+/g, " ").replace(/^\u200b+|\u200b+$/g, "").trim();

  const escapeCssIdent = (value) => {
    if (window.CSS && typeof window.CSS.escape === "function") {
      try {
        return window.CSS.escape(value);
      } catch (e) {
        /* fall through */
      }
    }
    return String(value).replace(/([^a-zA-Z0-9_\-\u00a0-\uffff])/g, "\\$1");
  };

  const escapeAttr = (value) =>
    String(value).replace(/\\/g, "\\\\").replace(/"/g, '\\"').replace(/\n/g, "\\n");

  const countCss = (selector) => {
    try {
      return document.querySelectorAll(selector).length;
    } catch (e) {
      return -1;
    }
  };

  const countXPath = (xpath) => {
    try {
      const result = document.evaluate(
        "count(" + xpath + ")",
        document,
        null,
        XPathResult.NUMBER_TYPE,
        null
      );
      return result.numberValue;
    } catch (e) {
      return -1;
    }
  };

  const indexInCss = (selector, el) => {
    try {
      const nodes = Array.prototype.slice.call(document.querySelectorAll(selector));
      const idx = nodes.indexOf(el);
      return idx < 0 ? 0 : idx;
    } catch (e) {
      return 0;
    }
  };

  const isVisible = (el) => {
    if (!el || el.nodeType !== 1) return false;
    try {
      const rect = el.getBoundingClientRect();
      if (rect.width <= 0 && rect.height <= 0) return false;
      const style = window.getComputedStyle(el);
      if (!style) return true;
      if (style.visibility === "hidden" || style.display === "none" || style.opacity === "0") return false;
      return true;
    } catch (e) {
      return false;
    }
  };

  const textOf = (el) => {
    if (!el) return "";
    let value = "";
    if (el.tagName === "INPUT") {
      const type = (el.type || "").toLowerCase();
      if (type === "submit" || type === "button" || type === "reset") value = el.value || "";
    } else if (el.tagName === "SELECT") {
      value = "";
    } else if (el.tagName === "IMG") {
      value = el.alt || "";
    }
    if (!value) value = el.innerText || el.textContent || "";
    value = clean(value);
    if (value.length > 90) value = value.slice(0, 90);
    return value;
  };

  const implicitRole = (el) => {
    const tag = el.tagName.toLowerCase();
    const type = (el.getAttribute("type") || "").toLowerCase();
    const map = {
      a: el.hasAttribute("href") ? "link" : "",
      button: "button",
      select: el.multiple ? "listbox" : "combobox",
      textarea: "textbox",
      option: "option",
      img: "img",
      h1: "heading",
      h2: "heading",
      h3: "heading",
      nav: "navigation",
      ul: "list",
      li: "listitem",
      table: "table",
      form: "form",
      dialog: "dialog",
      summary: "button",
      label: "label",
      fieldset: "group",
      output: "status",
      progress: "progressbar",
      article: "article",
      aside: "complementary",
      footer: "contentinfo",
      header: "banner",
      main: "main",
      section: "region",
      p: "paragraph",
    };
    if (tag === "input") {
      if (type === "submit" || type === "button" || type === "image" || type === "reset") return "button";
      if (type === "checkbox") return "checkbox";
      if (type === "radio") return "radio";
      if (type === "search") return "searchbox";
      if (type === "range") return "slider";
      if (type === "number") return "spinbutton";
      if (type === "file") return "button";
      if (["text", "email", "tel", "url", "password", "date", "datetime-local", "month", "week", "time"].indexOf(type) >= 0)
        return "textbox";
      return "textbox";
    }
    return map[tag] || "";
  };

  const labelText = (el) => {
    try {
      const labels = el.labels;
      if (labels && labels.length) {
        const text = clean(Array.prototype.map.call(labels, (l) => l.innerText || l.textContent).join(" "));
        if (text) return text.slice(0, 80);
      }
      const aria = el.getAttribute && el.getAttribute("aria-label");
      if (aria) return clean(aria).slice(0, 80);
      const id = el.getAttribute && el.getAttribute("id");
      if (id) {
        const node = document.querySelector('label[for="' + escapeAttr(id) + '"]');
        if (node) {
          const text = clean(node.innerText || node.textContent);
          if (text) return text.slice(0, 80);
        }
      }
    } catch (e) {
      /* ignore */
    }
    return "";
  };

  const accessibleName = (el) => {
    const aria = clean(el.getAttribute && el.getAttribute("aria-label"));
    if (aria) return aria.slice(0, 80);
    const labelledby = el.getAttribute && el.getAttribute("aria-labelledby");
    if (labelledby) {
      try {
        const text = labelledby
          .split(/\s+/)
          .map((id) => {
            const node = document.getElementById(id);
            return node ? clean(node.innerText || node.textContent) : "";
          })
          .filter(Boolean)
          .join(" ");
        if (text) return text.slice(0, 80);
      } catch (e) {
        /* ignore */
      }
    }
    const label = labelText(el);
    if (label) return label;
    const text = textOf(el);
    if (text) return text.slice(0, 80);
    const placeholder = clean(el.getAttribute && el.getAttribute("placeholder"));
    if (placeholder) return placeholder.slice(0, 80);
    const title = clean(el.getAttribute && el.getAttribute("title"));
    if (title) return title.slice(0, 80);
    const alt = clean(el.getAttribute && el.getAttribute("alt"));
    if (alt) return alt.slice(0, 80);
    const value = clean(el.getAttribute && el.getAttribute("value"));
    if (value) return value.slice(0, 80);
    return "";
  };

  const cssPath = (el) => {
    const parts = [];
    let node = el;
    let depth = 0;
    while (node && node.nodeType === 1 && depth < 8) {
      let part = node.tagName.toLowerCase();
      const id = node.getAttribute("id");
      if (id && /^[A-Za-z][\w\-:.]*$/.test(id) && countCss("#" + escapeCssIdent(id)) === 1) {
        parts.unshift("#" + escapeCssIdent(id));
        break;
      }
      const classes = Array.prototype.slice
        .call(node.classList || [])
        .filter((name) => /^[A-Za-z_][\w\-]*$/.test(name))
        .slice(0, 2);
      if (classes.length) part += "." + classes.map(escapeCssIdent).join(".");
      const parent = node.parentElement;
      if (parent) {
        const sameTag = Array.prototype.filter.call(parent.children, (child) => child.tagName === node.tagName);
        if (sameTag.length > 1) {
          part += ":nth-of-type(" + (sameTag.indexOf(node) + 1) + ")";
        }
      }
      parts.unshift(part);
      const candidate = parts.join(" > ");
      if (countCss(candidate) === 1) return candidate;
      node = node.parentElement;
      depth += 1;
    }
    return parts.join(" > ");
  };

  const xpathOf = (el) => {
    const id = el.getAttribute && el.getAttribute("id");
    if (id && /^[A-Za-z][\w\-:.]*$/.test(id) && countCss("#" + escapeCssIdent(id)) === 1) {
      return '//*[@id="' + escapeAttr(id) + '"]';
    }
    const segments = [];
    let node = el;
    let depth = 0;
    while (node && node.nodeType === 1 && depth < 10) {
      const tag = node.tagName.toLowerCase();
      const parent = node.parentElement;
      if (!parent) {
        segments.unshift("/" + tag);
        break;
      }
      const sameTag = Array.prototype.filter.call(parent.children, (child) => child.tagName === node.tagName);
      const index = sameTag.indexOf(node) + 1;
      segments.unshift("/" + tag + (sameTag.length > 1 ? "[" + index + "]" : ""));
      node = parent;
      depth += 1;
    }
    return "/html" + segments.join("").replace(/^\/html/, "");
  };

  const attributeCandidate = (el, attribute, score) => {
    const value = el.getAttribute(attribute);
    if (!value) return null;
    const selector = "[" + attribute + '="' + escapeAttr(value) + '"]';
    const count = countCss(selector);
    if (count <= 0) return null;
    return {
      kind: "css",
      value: selector,
      score,
      index: count > 1 ? indexInCss(selector, el) : 0,
      label: attribute + "=" + value.slice(0, 40),
    };
  };

  const frameChain = () => {
    const chain = [];
    try {
      let win = window;
      let guard = 0;
      while (win && win !== window.top && guard < 6) {
        const frame = win.frameElement;
        if (!frame) break;
        chain.unshift(cssPath(frame));
        win = win.parent;
        guard += 1;
      }
    } catch (e) {
      return [];
    }
    return chain;
  };

  const describe = (el) => {
    const candidates = [];
    const tag = el.tagName ? el.tagName.toLowerCase() : "";
    const type = (el.getAttribute && el.getAttribute("type") || "").toLowerCase();

    // 1. test ids (most stable)
    for (const attr of ["data-testid", "data-test-id", "data-test", "data-qa", "data-cy", "data-automation-id"]) {
      const candidate = attributeCandidate(el, attr, 0.99);
      if (candidate) {
        candidates.push(candidate);
        break;
      }
    }
    // 2. element id
    const id = el.getAttribute && el.getAttribute("id");
    if (id && /^[A-Za-z][\w\-:.]*$/.test(id)) {
      const selector = "#" + escapeCssIdent(id);
      const count = countCss(selector);
      if (count === 1) candidates.push({ kind: "css", value: selector, score: 0.96, index: 0, label: "id=" + id });
      else if (count > 1) candidates.push({ kind: "css", value: selector, score: 0.9, index: indexInCss(selector, el), label: "id=" + id });
    }
    // 3. accessible label (aria-label / <label>)
    const label = labelText(el);
    if (label) candidates.push({ kind: "label", value: label, score: 0.88, index: 0, label: "label" });
    // 4. role + accessible name
    const role = implicitRole(el);
    const name = accessibleName(el);
    if (role && name) candidates.push({ kind: "role", value: role + '[name="' + escapeAttr(name) + '"]', score: 0.86, index: 0, label: "role" });
    // 5. form name attribute
    const nameAttr = el.getAttribute && el.getAttribute("name");
    if (nameAttr && tag !== "body") {
      const selector = tag + '[name="' + escapeAttr(nameAttr) + '"]';
      const count = countCss(selector);
      if (count >= 1) candidates.push({ kind: "css", value: selector, score: 0.82, index: count > 1 ? indexInCss(selector, el) : 0, label: "name=" + nameAttr });
    }
    // 6. placeholder / alt / title
    const placeholder = el.getAttribute && el.getAttribute("placeholder");
    if (placeholder) candidates.push({ kind: "placeholder", value: placeholder, score: 0.78, index: indexInCss("[placeholder]", el) || 0, label: "placeholder" });
    const alt = el.getAttribute && el.getAttribute("alt");
    if (alt) candidates.push({ kind: "alt", value: alt, score: 0.76, index: 0, label: "alt" });
    // 7. visible text (buttons and links)
    const text = textOf(el);
    if (text && text.length <= 70 && ["a", "button", "span", "div", "li", "summary", "label", "td"].indexOf(tag) >= 0) {
      candidates.push({ kind: "text", value: text, score: 0.72, index: 0, label: "text" });
    }
    // 8. unique short css path
    const path = cssPath(el);
    if (path) {
      const count = countCss(path);
      candidates.push({ kind: "css", value: path, score: count === 1 ? 0.6 : 0.5, index: count > 1 ? indexInCss(path, el) : 0, label: "css path" });
    }
    // 9. xpath (last resort)
    const xpath = xpathOf(el);
    if (xpath && countXPath(xpath) === 1) {
      candidates.push({ kind: "xpath", value: xpath, score: 0.35, index: 0, label: "xpath" });
    }

    candidates.sort((a, b) => b.score - a.score);
    const chain = frameChain();
    return {
      tag,
      type,
      id: id || "",
      name: nameAttr || "",
      text: text.slice(0, 120),
      role,
      accessible_name: name,
      candidates,
      frame: chain,
      href: (el.href && typeof el.href === "string" && el.href.indexOf("javascript:") !== 0) ? el.href : "",
      target: el.getAttribute ? el.getAttribute("target") || "" : "",
      value: "value" in el ? String(el.value || "").slice(0, 400) : "",
      contenteditable: el.isContentEditable === true,
    };
  };

  /* --------------------------------------------------------------- element */

  const IGNORED_TAGS = new Set(["HTML", "BODY", "HEAD", "SCRIPT", "STYLE", "META", "LINK", "NOSCRIPT"]);

  const clickableFrom = (target) => {
    let node = target;
    let depth = 0;
    while (node && node.nodeType === 1 && depth < 8) {
      if (IGNORED_TAGS.has(node.tagName)) break;
      const tag = node.tagName.toLowerCase();
      const role = node.getAttribute && node.getAttribute("role");
      if (
        ["a", "button", "input", "select", "textarea", "option", "label", "summary", "details"].indexOf(tag) >= 0 ||
        role === "button" || role === "link" || role === "menuitem" || role === "tab" || role === "option" ||
        role === "checkbox" || role === "radio" || role === "switch" ||
        (node.hasAttribute && (node.hasAttribute("onclick") || node.hasAttribute("data-testid") || node.hasAttribute("data-test-id")))
      ) {
        return node;
      }
      if (node.getAttribute && (node.getAttribute("tabindex") === "0" || node.getAttribute("tabindex") === "-1") && node.hasAttribute("role")) {
        return node;
      }
      node = node.parentElement;
      depth += 1;
    }
    return null;
  };

  const isOurNode = (el) => el && el.closest && el.closest("[data-clicks-auto-ui]");

  /* ---------------------------------------------------------------- events */

  const dedupe = (key, windowMs) => {
    const now = Date.now();
    const last = STATE.timers[key] || 0;
    if (now - last < (windowMs || 350)) return true;
    STATE.timers[key] = now;
    return false;
  };

  const onClick = (event) => {
    if (!STATE.enabled) return;
    const raw = event.composedPath ? event.composedPath()[0] : event.target;
    const el = clickableFrom(raw);
    if (!el || isOurNode(el)) return;
    if (el.tagName === "SELECT" || el.tagName === "OPTION") return; // handled by change
    if (el.tagName === "INPUT") {
      const type = (el.getAttribute("type") || "").toLowerCase();
      if (["checkbox", "radio", "file"].indexOf(type) >= 0) return;
      if (["submit", "button", "reset", "image"].indexOf(type) >= 0) {
        /* real button - record below */
      }
    }
    const info = describe(el);
    const popup = info.target === "_blank" || (event.metaKey || event.ctrlKey || event.button === 1);
    send({
      kind: "click",
      click_count: event.detail === 2 ? 2 : 1,
      button: event.button === 2 ? "right" : event.button === 1 ? "middle" : "left",
      expect_popup: !!popup,
      el: info,
      x: Math.round(event.clientX),
      y: Math.round(event.clientY),
    });
  };

  const onChange = (event) => {
    if (!STATE.enabled) return;
    const el = event.target;
    if (!el || el.nodeType !== 1) return;
    const tag = el.tagName.toLowerCase();
    const info = describe(el);
    if (tag === "select") {
      let label = "";
      let value = el.value;
      try {
        const option = el.options[el.selectedIndex];
        if (option) {
          label = clean(option.textContent || "").slice(0, 120);
          value = option.value !== undefined ? option.value : value;
        }
      } catch (e) {
        /* ignore */
      }
      send({ kind: "select", el: info, label, value: String(value), multiple: !!el.multiple });
      return;
    }
    if (tag === "input") {
      const type = (el.getAttribute("type") || "").toLowerCase();
      if (type === "checkbox" || type === "radio") {
        send({ kind: "check", el: info, checked: !!el.checked });
        return;
      }
      if (type === "file") {
        send({ kind: "upload", el: info, files: Array.prototype.map.call(el.files || [], (f) => f.name) });
        return;
      }
    }
    if (STATE.typing) {
      flushTyping(info, el);
    }
  };

  const flushTyping = (info, el) => {
    const value = STATE.pendingText && STATE.pendingText.value !== undefined ? STATE.pendingText.value : (el && "value" in el ? String(el.value || "") : "");
    if (!STATE.pendingText) return;
    const payload = {
      kind: "type",
      el: info || STATE.pendingText.el,
      value,
      is_contenteditable: !!STATE.pendingText.editable,
      mode: STATE.typingMode,
      typing_delay_ms: STATE.typingDelayMs,
    };
    STATE.pendingText = null;
    STATE.typing = false;
    if (value !== "" || payload.el.is_contenteditable) send(payload);
  };

  // Inputs that carry text we can replay with fill()/type().  Everything else
  // (checkboxes, radios, files, buttons, selects, range/colour sliders) fires
  // input/change events too, but recording them as typing produces steps like
  // "type 'on' into I agree to the terms" which cannot be replayed.
  const TEXT_INPUT_TYPES = ["", "text", "search", "email", "url", "tel", "password",
    "number", "date", "datetime-local", "month", "week", "time"];

  const isTextEntry = (el) => {
    if (!el || el.nodeType !== 1) return false;
    if (el.isContentEditable === true) return true;
    if (el.tagName === "TEXTAREA") return true;
    if (el.tagName !== "INPUT") return false;
    const type = (el.getAttribute("type") || "text").toLowerCase();
    return TEXT_INPUT_TYPES.indexOf(type) >= 0;
  };

  const onInput = (event) => {
    if (!STATE.enabled) return;
    const el = event.target;
    if (!isTextEntry(el)) return;
    const info = describe(el);
    const editable = `${el.isContentEditable}` === "true";
    const value = "value" in el && !editable ? String(el.value || "") : clean(el.innerText || el.textContent || "");
    STATE.typing = true;
    STATE.pendingText = { el: info, editable, node: el };
    if (STATE.typingMode === "keystrokes") {
      // Send incremental keystroke batches so playback reproduces real typing.
      send({ kind: "type_chunk", el: info, value, is_contenteditable: editable, typing_delay_ms: STATE.typingDelayMs });
      return;
    }
    clearTimeout(STATE.typingTimer);
    STATE.typingTimer = setTimeout(() => {
      flushTyping(info, el);
    }, 450);
  };

  const onBlur = (event) => {
    if (!STATE.enabled) return;
    const el = event.target;
    if (!el || el.nodeType !== 1 || !STATE.typing) return;
    // Only the field that is actually being typed into may flush the buffer -
    // tabbing away from a checkbox must not turn pending text into a step.
    if (!isTextEntry(el)) return;
    const pendingNode = STATE.pendingText && STATE.pendingText.node;
    if (pendingNode && pendingNode !== el) return;
    try {
      flushTyping(describe(el), el);
    } catch (e) {
      flushTyping(null, el);
    }
  };

  const SPECIAL_KEYS = ["Enter", "Tab", "Escape", "ArrowUp", "ArrowDown", "ArrowLeft", "ArrowRight", "PageUp", "PageDown", "Home", "End", "Backspace", "Delete"];

  const onKeyDown = (event) => {
    if (!STATE.enabled) return;
    const el = event.target;
    if (el && el.nodeType === 1 && (el.tagName === "SELECT" || el.tagName === "OPTION")) return;
    const isTextArea = el && el.tagName === "TEXTAREA";
    const hasModifier = event.ctrlKey || event.metaKey || event.altKey;
    const key = event.key;
    const isSpecial = SPECIAL_KEYS.indexOf(key) >= 0;
    if (!hasModifier && !isSpecial) return;               // part of normal typing
    if (key === "Enter" && isTextArea) return;            // newline, not submit
    if (key === "Backspace" || key === "Delete") return;  // covered by the value snapshot
    if (hasModifier && ["c", "v", "x", "a"].indexOf(String(key).toLowerCase()) >= 0) {
      const type = el && el.getAttribute ? (el.getAttribute("type") || "").toLowerCase() : "";
      if (["text", "search", "email", "url", "tel", "password", "textarea"].indexOf(type) >= 0 || (el && (el.tagName === "TEXTAREA" || el.isContentEditable))) {
        if (String(key).toLowerCase() !== "a") return; // clipboard ops are implied by typing
      }
    }
    if (key === "Enter" && STATE.typing) {
      // the click that follows a submit is recorded separately - keep typing info
    }
    let combo = "";
    if (event.ctrlKey) combo += "Control+";
    if (event.metaKey) combo += "Meta+";
    if (event.altKey) combo += "Alt+";
    if (event.shiftKey && key.length > 1) combo += "Shift+";
    combo += key;
    const target = el && el.nodeType === 1 && !IGNORED_TAGS.has(el.tagName) ? describe(el) : null;
    send({ kind: "key", key: combo, el: target, submits: key === "Enter" });
  };

  const onSubmit = (event) => {
    if (!STATE.enabled) return;
    const form = event.target;
    if (!form || form.nodeType !== 1) return;
    send({ kind: "submit", el: describe(form) });
  };

  const onScroll = (() => {
    let lastX = 0;
    let lastY = 0;
    let timer = null;
    let pending = null;
    return (event) => {
      if (!STATE.enabled || !STATE.recordScroll) return;
      const target = event.target === document ? document.scrollingElement || document.documentElement : event.target;
      const x = Math.round(target.scrollLeft || 0);
      const y = Math.round(target.scrollTop || 0);
      const dx = x - lastX;
      const dy = y - lastY;
      lastX = x;
      lastY = y;
      if (Math.abs(dx) < 30 && Math.abs(dy) < 30) return;
      pending = { kind: "scroll", dx, dy, x, y };
      clearTimeout(timer);
      timer = setTimeout(() => {
        if (pending) send(pending);
        pending = null;
      }, 350);
    };
  })();

  const onHover = (() => {
    let timer = null;
    let lastEl = null;
    return (event) => {
      if (!STATE.enabled || !STATE.recordHover) return;
      const el = clickableFrom(event.target);
      if (!el || el === lastEl || isOurNode(el)) return;
      lastEl = el;
      clearTimeout(timer);
      timer = setTimeout(() => {
        const info = describe(el);
        if (info.candidates && info.candidates.length) send({ kind: "hover", el: info });
      }, 420);
    };
  })();

  const onDialogTrigger = (event) => {
    if (!STATE.enabled) return;
    const el = clickableFrom(event.target);
    if (el && /alert|confirm|prompt/i.test(clean(el.getAttribute("onclick") || ""))) {
      send({ kind: "dialog_trigger", el: describe(el) });
    }
  };

  /* ------------------------------------------------------------ SPA routes */

  const wrap = (name) => {
    const original = window.history[name];
    if (!original) return;
    window.history[name] = function () {
      const result = original.apply(this, arguments);
      try {
        send({ kind: "navigation", url: String(window.location.href), spa: true });
      } catch (e) {
        /* ignore */
      }
      return result;
    };
  };

  /* ------------------------------------------------------------ bootstrap */

  const install = () => {
    document.addEventListener("click", (e) => {
      onDialogTrigger(e);
      onClick(e);
    }, true);
    document.addEventListener("auxclick", onClick, true);
    document.addEventListener("change", onChange, true);
    document.addEventListener("input", onInput, true);
    document.addEventListener("blur", onBlur, true);
    document.addEventListener("keydown", onKeyDown, true);
    document.addEventListener("submit", onSubmit, true);
    document.addEventListener("scroll", onScroll, true);
    document.addEventListener("mouseover", onHover, true);
    window.addEventListener("popstate", () => send({ kind: "navigation", url: String(window.location.href), spa: true }));
    window.addEventListener("hashchange", () => send({ kind: "navigation", url: String(window.location.href), spa: true }));
    wrap("pushState");
    wrap("replaceState");
  };

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", install, { once: true });
  } else {
    install();
  }

  window.__clicksAuto = {
    setOptions(options) {
      if (!options) return;
      if (typeof options.enabled === "boolean") STATE.enabled = options.enabled;
      if (typeof options.recordScroll === "boolean") STATE.recordScroll = options.recordScroll;
      if (typeof options.recordHover === "boolean") STATE.recordHover = options.recordHover;
      if (typeof options.typingMode === "string") STATE.typingMode = options.typingMode;
      if (typeof options.typingDelayMs === "number") STATE.typingDelayMs = options.typingDelayMs;
    },
    flush() {
      if (STATE.pendingText) {
        try {
          flushTyping(null, null);
        } catch (e) {
          STATE.pendingText = null;
        }
      }
    },
    ping() {
      return { ok: true, url: String(window.location.href) };
    },
  };

  send({ kind: "ready", url: String(window.location.href) });
})();
