// Clarivance Ltd website: mobile menu, contact form and the chat assistant.
(() => {
  const $ = (sel) => document.querySelector(sel);

  // The pages are served by GitHub Pages; the chat and contact form run as
  // Netlify functions, which keep the API key private.
  const API = /(^|\.)netlify\.app$|^localhost$|^127\.0\.0\.1$/.test(location.hostname)
    ? ""
    : "https://clarivance.netlify.app";

  // Footer year
  $("#year").textContent = new Date().getFullYear();

  // Mobile menu
  const menuBtn = $("#menuBtn");
  const nav = $("#nav");
  menuBtn.addEventListener("click", () => {
    const open = nav.classList.toggle("open");
    menuBtn.setAttribute("aria-expanded", String(open));
  });
  nav.addEventListener("click", (e) => {
    if (e.target.closest("a, button")) {
      nav.classList.remove("open");
      menuBtn.setAttribute("aria-expanded", "false");
    }
  });

  // "Ask about this track" links pre-select the contact form's interest.
  const interest = $("#cInterest");
  document.querySelectorAll("[data-interest]").forEach((link) => {
    link.addEventListener("click", () => { interest.value = link.dataset.interest; });
  });

  // Contact form (Netlify Forms). Submitted in the background so the page stays put.
  const form = $("#contactForm");
  const status = $("#cStatus");
  const submit = $("#cSubmit");
  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    status.className = "form-status";
    status.textContent = "Sending...";
    submit.disabled = true;
    try {
      const res = await fetch(API + "/api/contact", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(Object.fromEntries(new FormData(form))),
      });
      if (!res.ok) {
        let msg = "";
        try { msg = (await res.json()).error || ""; } catch (e) {}
        throw new Error(msg);
      }
      form.reset();
      status.className = "form-status ok";
      status.textContent = "Thanks, your message was sent. We will reply by email.";
    } catch (err) {
      status.className = "form-status err";
      status.textContent = err.message || "Your message didn't send. Check your connection and try again.";
    } finally {
      submit.disabled = false;
    }
  });

  // ---------------- Chat assistant ----------------
  const STORE = "clarivance-site-chat";
  const MAX_TURNS = 16;
  const panel = $("#chatPanel");
  const launch = $("#chatLaunch");
  const log = $("#chatLog");
  const chips = $("#chatChips");
  const chatForm = $("#chatForm");
  const box = $("#chatBox");
  const send = $("#chatSend");
  const greeting = log.innerHTML;
  let turns = [];
  let busy = null;

  try { turns = JSON.parse(sessionStorage.getItem(STORE) || "[]").filter((t) => t && t.content); } catch (e) {}
  const save = () => { try { sessionStorage.setItem(STORE, JSON.stringify(turns.slice(-MAX_TURNS))); } catch (e) {} };

  // Small, safe Markdown renderer: escape first, then format.
  const esc = (s) => s.replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
  const inline = (s) => esc(s)
    .replace(/`([^`]+)`/g, "<code>$1</code>")
    .replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>")
    .replace(/(^|[^*])\*([^*\s][^*]*)\*/g, "$1<em>$2</em>")
    .replace(/\[([^\]]+)\]\((https?:\/\/[^\s)]+)\)/g, '<a href="$2" target="_blank" rel="noopener">$1</a>');
  function markdown(src) {
    const out = [];
    const lines = src.replace(/\r/g, "").split("\n");
    const listItem = /^\s*([-*]|\d+[.)])\s/;
    let i = 0;
    while (i < lines.length) {
      const line = lines[i];
      if (/^```/.test(line)) {
        const code = [];
        i++;
        while (i < lines.length && !/^```/.test(lines[i])) code.push(lines[i++]);
        i++;
        out.push("<pre><code>" + esc(code.join("\n")) + "</code></pre>");
      } else if (/^#{1,6}\s/.test(line)) {
        out.push("<h4>" + inline(line.replace(/^#+\s/, "")) + "</h4>"); i++;
      } else if (listItem.test(line)) {
        const ordered = /^\s*\d/.test(line);
        const items = [];
        while (i < lines.length && listItem.test(lines[i])) items.push("<li>" + inline(lines[i++].replace(listItem, "")) + "</li>");
        out.push((ordered ? "<ol>" : "<ul>") + items.join("") + (ordered ? "</ol>" : "</ul>"));
      } else if (!line.trim()) {
        i++;
      } else {
        const para = [];
        while (i < lines.length && lines[i].trim() && !/^(```|#{1,6}\s)/.test(lines[i]) && !listItem.test(lines[i])) para.push(lines[i++]);
        out.push("<p>" + inline(para.join("\n")).replace(/\n/g, "<br>") + "</p>");
      }
    }
    return out.join("");
  }

  function bubble(role, content) {
    const wrap = document.createElement("div");
    wrap.className = "msg " + (role === "user" ? "user" : "bot");
    const body = document.createElement("div");
    body.className = "body";
    if (role === "user") body.textContent = content; else body.innerHTML = markdown(content);
    wrap.append(body);
    log.append(wrap);
    return body;
  }
  const scrollDown = () => { log.scrollTop = log.scrollHeight; };

  function renderHistory() {
    log.innerHTML = greeting;
    bindChips();
    if (turns.length) $("#chatChips").hidden = true;
    turns.forEach((t) => bubble(t.role, t.content));
    scrollDown();
  }
  function bindChips() {
    log.querySelectorAll("#chatChips button").forEach((b) => b.addEventListener("click", () => { box.value = b.textContent; ask(); }));
  }

  function openChat() {
    panel.hidden = false;
    document.body.classList.add("chat-open");
    launch.setAttribute("aria-expanded", "true");
    scrollDown();
    box.focus();
  }
  function closeChat() {
    panel.hidden = true;
    document.body.classList.remove("chat-open");
    launch.setAttribute("aria-expanded", "false");
    launch.focus();
  }
  document.querySelectorAll("[data-open-chat]").forEach((b) => b.addEventListener("click", openChat));
  $("#chatClose").addEventListener("click", closeChat);
  document.addEventListener("keydown", (e) => { if (e.key === "Escape" && !panel.hidden) closeChat(); });
  $("#chatReset").addEventListener("click", () => {
    if (busy) busy.abort();
    turns = [];
    save();
    renderHistory();
    box.focus();
  });

  function errorText(status, message) {
    if (status === 429) return "The assistant is busy right now. Please wait a minute and try again.";
    if (status === 503) return "The assistant isn't available at the moment. You can still reach us with the contact form.";
    if (status >= 500 || status === 0) return "The assistant couldn't answer just now. Please try again.";
    return message || "Something went wrong. Please try again.";
  }

  // Streams the answer from /api/chat (a Netlify function that holds the API key).
  async function complete(messages, signal, onText) {
    const res = await fetch(API + "/api/chat", {
      method: "POST",
      signal,
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ messages }),
    });
    if (!res.ok) {
      let msg = "";
      try { msg = (await res.json()).error || ""; } catch (e) {}
      throw { status: res.status, message: msg };
    }
    const reader = res.body.getReader();
    const decoder = new TextDecoder();
    let buf = "", text = "";
    for (;;) {
      const { value, done } = await reader.read();
      if (done) break;
      buf += decoder.decode(value, { stream: true });
      const lines = buf.split("\n");
      buf = lines.pop();
      for (const line of lines) {
        if (!line.startsWith("data:")) continue; // skips keep-alive comments
        const data = line.slice(5).trim();
        if (data === "[DONE]") continue;
        let chunk;
        try { chunk = JSON.parse(data); } catch (e) { continue; }
        if (chunk.error) throw { status: Number(chunk.error.code) || 500, message: "", text };
        const delta = chunk.choices && chunk.choices[0] && chunk.choices[0].delta && chunk.choices[0].delta.content;
        if (delta) { text += delta; onText(text); }
      }
    }
    if (!text.trim()) throw { status: 0, message: "", text };
    return text;
  }

  async function ask() {
    const text = box.value.trim();
    if (!text || busy) return;
    box.value = "";
    autosize();
    const chipRow = $("#chatChips");
    if (chipRow) chipRow.hidden = true;
    turns.push({ role: "user", content: text });
    bubble("user", text);
    const body = bubble("assistant", "");
    body.innerHTML = '<span class="thinking">Thinking...</span>';
    scrollDown();

    busy = new AbortController();
    send.textContent = "Stop";
    try {
      const answer = await complete(turns.slice(-MAX_TURNS), busy.signal, (t) => { body.innerHTML = markdown(t); scrollDown(); });
      turns.push({ role: "assistant", content: answer });
    } catch (e) {
      const cancelled = e && e.name === "AbortError";
      if (e && e.text) {
        body.innerHTML = markdown(e.text);
        turns.push({ role: "assistant", content: e.text });
      } else {
        body.innerHTML = "";
      }
      if (cancelled) {
        if (!e.text) body.innerHTML = '<p class="note">Stopped.</p>';
      } else {
        const p = document.createElement("p");
        p.className = "note";
        p.textContent = e && e.status !== undefined ? errorText(e.status, e.message) : "Couldn't reach the assistant. Check your connection and try again.";
        body.append(p);
        if (turns[turns.length - 1].role === "user" && !e.text) turns.pop(); // let the visitor resend
      }
    } finally {
      busy = null;
      send.textContent = "Send";
      save();
      scrollDown();
    }
  }

  function autosize() {
    box.style.height = "auto";
    box.style.height = Math.min(box.scrollHeight, 140) + "px";
  }
  chatForm.addEventListener("submit", (e) => { e.preventDefault(); if (busy) busy.abort(); else ask(); });
  box.addEventListener("input", autosize);
  box.addEventListener("keydown", (e) => {
    if (e.key === "Enter" && !e.shiftKey && !e.isComposing) { e.preventDefault(); if (!busy) ask(); }
  });

  renderHistory();
})();
