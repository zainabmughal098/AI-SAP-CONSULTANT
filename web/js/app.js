const STORAGE_KEY = "sap-consultant-ui";
const SELECTION_KEY = "sap-consultant-selected-chat";

const state = {
  sessionId: null,
  chats: [],
  activeChatId: null,
  isStreaming: false,
  isResetting: false,
  abortController: null,
  activeRequest: null,
};

const el = {
  shell: document.querySelector(".app-shell"),
  sidebar: document.getElementById("sidebar"),
  sidebarToggle: document.getElementById("sidebar-toggle"),
  newChatBtn: document.getElementById("new-chat-btn"),
  composerNew: document.getElementById("composer-new"),
  clearChatBtn: document.getElementById("clear-chat-btn"),
  recentList: document.getElementById("recent-list"),
  welcome: document.getElementById("welcome"),
  welcomeTitle: document.getElementById("welcome-title"),
  messages: document.getElementById("messages"),
  messagesInner: document.getElementById("messages-inner"),
  chatStage: document.getElementById("chat-stage"),
  form: document.getElementById("composer-form"),
  input: document.getElementById("query-input"),
  sendBtn: document.getElementById("send-btn"),
  stopBtn: document.getElementById("stop-btn"),
};

const greetings = [
  "Any new ideas to explore?",
  "Let's jump in",
  "Hey! How can I help you today?",
  "What SAP process can I help with?",
];

function uid() {
  return crypto.randomUUID();
}

function loadState() {
  state.chats = [];
  state.activeChatId = null;
  state.sessionId = null;
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) return;
    const saved = JSON.parse(raw);
    const ids = new Set();
    state.chats = (Array.isArray(saved.chats) ? saved.chats : []).filter((chat) => {
      if (!chat || typeof chat.id !== "string" || ids.has(chat.id) || !Array.isArray(chat.messages)) return false;
      ids.add(chat.id);
      chat.title = typeof chat.title === "string" ? chat.title : "New chat";
      chat.messages = chat.messages.filter((message) => message && ["user", "assistant"].includes(message.role) && typeof message.content === "string");
      return true;
    });
    // Selection belongs to this tab, not the shared history. A normal visit
    // starts blank; refresh/back retains only this tab's explicitly selected chat.
    const navigation = typeof performance !== "undefined" ? performance.getEntriesByType?.("navigation")[0]?.type : null;
    const selected = navigation === "navigate" ? null : sessionStorage.getItem(SELECTION_KEY);
    state.activeChatId = state.chats.some((chat) => chat.id === selected) ? selected : null;
    const sessions = new Set();
    // Repair legacy shared-session history without replaying browser messages
    // into backend memory. Give the selected conversation ownership if possible.
    const ownerFirst = [...state.chats].sort((a, b) => Number(b.id === state.activeChatId) - Number(a.id === state.activeChatId));
    ownerFirst.forEach((chat) => {
      if (typeof chat.sessionId !== "string" || sessions.has(chat.sessionId)) chat.sessionId = null;
      if (chat.sessionId) sessions.add(chat.sessionId);
    });
    state.sessionId = getActiveChat()?.sessionId || null;
    sessionStorage.setItem(SELECTION_KEY, state.activeChatId || "");
  } catch {
    // Keep valid sidebar history even if tab storage is unavailable.
    state.activeChatId = null;
    state.sessionId = null;
  }
}

function saveState() {
  try {
    localStorage.setItem(
    STORAGE_KEY,
    JSON.stringify({
      chats: state.chats,
    }),
    );
  } catch {
    // Storage can be disabled or full. The current in-memory chat still works.
    console.warn("Chat history could not be saved in this browser.");
  }
  try {
    sessionStorage.setItem(SELECTION_KEY, state.activeChatId || "");
  } catch {
    console.warn("The selected conversation could not be saved in this tab.");
  }
}

function getActiveChat() {
  return state.chats.find((chat) => chat.id === state.activeChatId) || null;
}

function ensureActiveChat() {
  if (getActiveChat()) return getActiveChat();

  const chat = {
    id: uid(),
    title: "New chat",
    messages: [],
    sessionId: null,
    createdAt: Date.now(),
  };
  state.chats.unshift(chat);
  state.activeChatId = chat.id;
  state.sessionId = null;
  saveState();
  renderRecent();
  return chat;
}

function createNewChat() {
  if (state.isResetting) return;
  cancelActiveRequest();
  state.activeChatId = null;
  state.sessionId = null;
  renderConversation();
  renderRecent();
  saveState();
  setRandomGreeting();
  el.input.focus();
}

function cancelActiveRequest() {
  const request = state.activeRequest;
  if (!request) return;
  state.activeRequest = null;
  request.controller.abort();
  if (state.chats.includes(request.chat)) {
    request.chat.messages.push({role: "assistant", phase: "error", sources: [],
      content: "Generation stopped. This response is incomplete. You can send your question again."});
  }
  state.abortController = null;
  setStreamingState(false);
  saveState();
}

function selectConversation(chatId) {
  if (state.isResetting) return;
  const chat = state.chats.find((item) => item.id === chatId);
  if (!chat || chat.id === state.activeChatId) return;
  cancelActiveRequest();
  state.activeChatId = chat.id;
  state.sessionId = chat.sessionId || null;
  renderConversation();
  renderRecent();
  saveState();
}

function setRandomGreeting() {
  el.welcomeTitle.textContent = greetings[Math.floor(Math.random() * greetings.length)];
}

function renderRecent() {
  el.recentList.innerHTML = "";
  state.chats.forEach((chat) => {
    const row = document.createElement("div");
    row.style.display = "flex";
    row.style.alignItems = "center";
    const button = document.createElement("button");
    button.type = "button";
    button.className = `recent-item${chat.id === state.activeChatId ? " active" : ""}`;
    button.dataset.chatId = chat.id;
    button.textContent = chat.title;
    button.title = chat.title;
    button.style.flex = "1";
    button.style.minWidth = "0";
    button.addEventListener("click", () => selectConversation(chat.id));
    const remove = document.createElement("button");
    remove.type = "button";
    remove.className = "icon-btn";
    remove.title = "Delete conversation";
    remove.dataset.deleteChat = chat.id;
    remove.setAttribute("aria-label", `Delete conversation: ${chat.title}`);
    remove.textContent = "×";
    remove.disabled = state.isResetting || (state.isStreaming && state.activeRequest?.chat !== chat);
    remove.addEventListener("click", () => deleteConversation(chat.id));
    row.appendChild(button);
    row.appendChild(remove);
    el.recentList.appendChild(row);
  });
}

function formatMarkdown(text) {
  const escaped = text
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;");

  return escaped
    .replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>")
    .replace(/^- (.+)$/gm, "<li>$1</li>")
    .replace(/(<li>.*<\/li>\n?)+/g, (match) => `<ul>${match}</ul>`)
    .replace(/\n{2,}/g, "</p><p>")
    .replace(/\n/g, "<br>")
    .replace(/^/, "<p>")
    .concat("</p>")
    .replace(/<p><\/p>/g, "");
}

function scrollToBottom() {
  el.chatStage.scrollTop = el.chatStage.scrollHeight;
}

function renderConversation() {
  const chat = getActiveChat();
  const hasMessages = Boolean(chat && chat.messages.length);

  el.welcome.hidden = hasMessages;
  el.messages.hidden = !hasMessages;
  el.chatStage.classList.toggle("has-messages", hasMessages);
  el.messagesInner.innerHTML = "";

  if (!chat) return;

  chat.messages.forEach((message, index) => {
    el.messagesInner.appendChild(createMessageElement(message, index, chat.messages));
  });
  scrollToBottom();
}

function isPendingClarification(message, index, messages) {
  if (message.role !== "assistant" || message.phase !== "clarifying") return false;
  // Only the latest unanswered clarifying turn shows an inline reply box
  const later = messages.slice(index + 1);
  if (later.some((m) => m.role === "user")) return false;
  const laterClarify = later.some((m) => m.role === "assistant" && m.phase === "clarifying");
  return !laterClarify;
}

function createMessageElement(message, index = 0, messages = []) {
  const wrapper = document.createElement("article");
  wrapper.className = `message ${message.role}`;

  if (message.role === "user") {
    const bubble = document.createElement("div");
    bubble.className = "user-bubble";
    bubble.textContent = message.content;
    wrapper.appendChild(bubble);
    return wrapper;
  }

  const content = document.createElement("div");
  content.className = "assistant-content";
  content.innerHTML = formatMarkdown(message.content || "");
  wrapper.appendChild(content);

  if (message.sources?.length) {
    wrapper.appendChild(createSourcesPanel(message.sources));
  }

  if (isPendingClarification(message, index, messages)) {
    wrapper.appendChild(createInlineReplyForm());
  }

  wrapper.appendChild(createActionBar(message.content || ""));
  return wrapper;
}

function createInlineReplyForm() {
  const form = document.createElement("form");
  form.className = "inline-reply";
  form.addEventListener("submit", (event) => {
    event.preventDefault();
    const input = form.querySelector("input");
    const value = input?.value.trim();
    if (!value || state.isStreaming) return;
    form.querySelector("button")?.setAttribute("disabled", "true");
    input.disabled = true;
    sendMessage(value);
  });

  const label = document.createElement("label");
  label.className = "inline-reply-label";
  label.textContent = "Your answer";

  const row = document.createElement("div");
  row.className = "inline-reply-row";

  const input = document.createElement("input");
  input.type = "text";
  input.className = "inline-reply-input";
  input.placeholder = "Type your answer here…";
  input.autocomplete = "off";
  input.setAttribute("aria-label", "Answer clarifying question");

  const button = document.createElement("button");
  button.type = "submit";
  button.className = "inline-reply-send";
  button.setAttribute("aria-label", "Send answer");
  button.innerHTML = `<svg viewBox="0 0 24 24" width="16" height="16" fill="currentColor"><path d="M3.4 20.6 21 12 3.4 3.4l2.8 7.2L17 12l-10.8 1.4-2.8 7.2z"/></svg>`;

  row.appendChild(input);
  row.appendChild(button);
  form.appendChild(label);
  form.appendChild(row);

  // Focus after paint so the clarifying question feels interactive in-place
  requestAnimationFrame(() => input.focus());
  return form;
}

function createSourcesPanel(sources) {
  const panel = document.createElement("div");
  panel.className = "sources-panel";
  sources.forEach((source) => {
    const chip = document.createElement("span");
    chip.className = "source-chip";
    chip.title = JSON.stringify({
      id: source.id, source: source.source_file, metadata: source.metadata,
      authority: source.authority, url: source.source_url,
    });
    chip.textContent = `${source.document_type || "record"} · ${source.title || source.source_file || "Unknown"}`;
    chip.textContent = `${source.citation_handle ? `[${source.citation_handle}] ` : ""}${source.source_kind === "synthetic" ? "DEMO / SIMULATED · " : ""}${chip.textContent}`;
    panel.appendChild(chip);
  });
  return panel;
}

function createActionBar(text) {
  const bar = document.createElement("div");
  bar.className = "message-actions";

  const copyBtn = document.createElement("button");
  copyBtn.type = "button";
  copyBtn.className = "action-btn";
  copyBtn.title = "Copy";
  copyBtn.innerHTML = copyIcon();
  copyBtn.addEventListener("click", async () => {
    await navigator.clipboard.writeText(text);
    copyBtn.title = "Copied";
    setTimeout(() => {
      copyBtn.title = "Copy";
    }, 1200);
  });

  bar.appendChild(copyBtn);
  return bar;
}

function copyIcon() {
  return `<svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="1.8"><rect x="9" y="9" width="11" height="11" rx="2"/><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"/></svg>`;
}

function createStreamingAssistantMessage() {
  const wrapper = document.createElement("article");
  wrapper.className = "message assistant";
  wrapper.dataset.streaming = "true";

  const content = document.createElement("div");
  content.className = "assistant-content";
  content.innerHTML = `<div class="typing-indicator"><span></span><span></span><span></span></div>`;
  wrapper.appendChild(content);

  el.messagesInner.appendChild(wrapper);
  scrollToBottom();
  return { wrapper, content };
}

function setStreamingState(isStreaming) {
  state.isStreaming = isStreaming;
  el.sendBtn.classList.toggle("hidden", isStreaming);
  el.stopBtn.classList.toggle("hidden", !isStreaming);
  el.input.disabled = isStreaming;
  el.newChatBtn.disabled = state.isResetting;
  el.composerNew.disabled = state.isResetting;
  el.clearChatBtn.disabled = isStreaming;
  el.messagesInner.querySelectorAll(".inline-reply-input, .inline-reply-send").forEach((node) => {
    node.disabled = isStreaming;
  });
  renderRecent();
}

async function streamChat(query, assistantNode, request = null) {
  request = request || { chat: ensureActiveChat(), controller: new AbortController() };
  state.activeRequest = request;
  state.abortController = request.controller;
  setStreamingState(true);

  const chat = request.chat;
  // Allocate a per-chat ID before the first network event. Cancellation or
  // deletion before headers arrive can still identify the backend session.
  if (!chat.sessionId) chat.sessionId = uid();
  state.sessionId = chat.sessionId;
  saveState();
  const requireOwner = () => {
    if (state.activeRequest !== request || request.controller.signal.aborted) {
      const error = new Error("Conversation request cancelled");
      error.name = "AbortError";
      throw error;
    }
  };
  let assistantText = "";
  let sources = [];
  let phase = "answering";
  let intent = null;
  let completed = false;

  const response = await fetch("/chat/stream", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      query,
      session_id: chat.sessionId || null,
    }),
    signal: request.controller.signal,
  });
  if (state.activeRequest !== request || request.controller.signal.aborted) {
    try { await response.body?.cancel(); } catch { /* The abort may have closed it already. */ }
  }
  requireOwner();

  if (!response.ok || !response.body) {
    const messages = {
      400: "Please enter a valid SAP question.",
      422: "The request was not valid. Please check your question and try again.",
      429: "The service is busy. Please wait a moment and retry.",
      502: "The answer could not be completed. Please retry.",
      503: "A required service is temporarily unavailable. Please retry later.",
      504: "The service took too long to respond. Please retry.",
    };
    throw new Error(messages[response.status] || "Unable to connect to the answer service. Please retry.");
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  try {
    while (!completed) {
      const { value, done } = await reader.read();
      requireOwner();
      if (done) break;

      buffer += decoder.decode(value, { stream: true });
      const chunks = buffer.split("\n\n");
      buffer = chunks.pop() || "";

      for (const chunk of chunks) {
        const line = chunk.trim();
        if (!line.startsWith("data: ")) continue;

        const event = JSON.parse(line.slice(6));

        if (event.type === "session") {
          state.sessionId = event.session_id;
          chat.sessionId = event.session_id;
          saveState();
        }

        if (event.type === "status" && !assistantText) {
          assistantNode.content.textContent = event.message || "Working...";
        }

        if (event.type === "token") {
          assistantText += event.content;
          assistantNode.content.innerHTML = formatMarkdown(assistantText);
          scrollToBottom();
        }

        if (event.type === "sources") {
          sources = event.sources || [];
        }

        if (event.type === "error") {
          throw new Error(event.message || "Generation failed.");
        }

        if (event.type === "done") {
          if (event.complete === false || event.error || typeof event.answer !== "string" || !event.answer.trim()) {
            throw new Error("The answer was incomplete. Please retry, or ask a shorter question.");
          }
          completed = true;
          assistantText = event.answer;
          state.sessionId = event.session_id;
          chat.sessionId = event.session_id;
          phase = event.phase || "answering";
          intent = event.intent || null;
          break;
        }
      }
    }
    if (!completed) {
      throw new Error("The connection ended before the answer was complete. Please retry.");
    }
  } finally {
    // Release the response even when JSON parsing, a provider error or cancellation fails.
    try { await reader.cancel(); } catch { /* Connection may already be closed. */ }
    reader.releaseLock();
  }

  requireOwner();

  assistantNode.wrapper.dataset.streaming = "false";
  assistantNode.content.innerHTML = formatMarkdown(assistantText);

  if (sources.length) {
    assistantNode.wrapper.appendChild(createSourcesPanel(sources));
  }

  const assistantMessage = {
    role: "assistant",
    content: assistantText,
    sources,
    phase,
    intent,
  };

  if (phase === "clarifying") {
    assistantNode.wrapper.appendChild(createInlineReplyForm());
  }

  assistantNode.wrapper.appendChild(createActionBar(assistantText));

  chat.messages.push(assistantMessage);
  if (chat.title === "New chat") {
    chat.title = query.slice(0, 42);
  }
  saveState();
  renderRecent();
}

async function sendMessage(query) {
  if (!query || state.isStreaming || state.isResetting) return;

  const chat = ensureActiveChat();
  el.welcome.hidden = true;
  el.messages.hidden = false;
  el.chatStage.classList.add("has-messages");

  // Drop any open inline reply boxes before appending the next turn
  el.messagesInner.querySelectorAll(".inline-reply").forEach((node) => node.remove());

  chat.messages.push({ role: "user", content: query });
  if (chat.title === "New chat") chat.title = query.slice(0, 42);
  saveState();
  el.messagesInner.appendChild(createMessageElement({ role: "user", content: query }));

  el.input.value = "";
  autoResizeInput();
  scrollToBottom();

  const assistantNode = createStreamingAssistantMessage();
  const request = {chat, controller: new AbortController()};

  try {
    await streamChat(query, assistantNode, request);
  } catch (error) {
    if (state.activeRequest !== request) return;
    const message = error.name === "AbortError"
      ? "Generation stopped. This response is incomplete. You can send your question again."
      : error.name === "TypeError"
      ? "The connection to the answer service failed. Please check your connection and retry."
      : error.name === "SyntaxError"
      ? "The server returned an unreadable response. Please retry."
      : error.message || "The answer could not be completed. Please retry.";
    // Error strings can originate upstream. Never interpret them as HTML.
    assistantNode.content.textContent = message;
    assistantNode.wrapper.dataset.streaming = "false";
    chat.messages.push({ role: "assistant", content: message, phase: "error", sources: [] });
    saveState();
  } finally {
    if (state.activeRequest === request) {
      state.activeRequest = null;
      setStreamingState(false);
      state.abortController = null;
      const inlineInput = el.messagesInner.querySelector(".inline-reply-input");
      if (inlineInput) inlineInput.focus();
      else el.input.focus();
    }
  }
}

async function handleSubmit(event) {
  event.preventDefault();
  const query = el.input.value.trim();
  await sendMessage(query);
}

function autoResizeInput() {
  el.input.style.height = "auto";
  el.input.style.height = `${Math.min(el.input.scrollHeight, 160)}px`;
}

async function deleteConversation(chatId) {
  if (state.isResetting) return;
  const chat = state.chats.find((item) => item.id === chatId);
  if (!chat || (state.isStreaming && state.activeRequest?.chat !== chat)) return;
  if (state.activeRequest?.chat === chat) cancelActiveRequest();
  state.isResetting = true;
  const controls = [el.input, el.sendBtn, el.newChatBtn, el.composerNew, el.clearChatBtn];
  controls.forEach((control) => { control.disabled = true; });
  try {
    if (chat.sessionId) {
      const response = await fetch(`/sessions/${encodeURIComponent(chat.sessionId)}`, {method: "DELETE"});
      if (!response.ok && response.status !== 404) throw new Error("Delete failed");
    }
    state.chats = state.chats.filter((item) => item !== chat);
    if (state.activeChatId === chat.id) {
      state.activeChatId = null;
      state.sessionId = null;
    }
  } catch {
    chat.messages.push({role: "assistant", phase: "error", sources: [],
      content: "The conversation could not be deleted. History was retained. Please retry."});
  } finally {
    state.isResetting = false;
    controls.forEach((control) => { control.disabled = false; });
    saveState();
    renderRecent();
    renderConversation();
    el.input.focus();
  }
}

async function clearConversation() {
  if (state.isStreaming || state.isResetting) return;
  const chat = getActiveChat();
  state.isResetting = true;
  const controls = [el.input, el.sendBtn, el.newChatBtn, el.composerNew, el.clearChatBtn];
  controls.forEach((control) => { control.disabled = true; });
  try {
    if (state.sessionId) {
      const response = await fetch(`/sessions/${state.sessionId}/reset`, { method: "POST" });
      if (!response.ok) throw new Error("Reset failed");
    }
    if (chat) {
      chat.messages = [];
      chat.sessionId = null;
    }
    state.sessionId = null;
    saveState();
    renderConversation();
    setRandomGreeting();
  } catch {
    // Do not claim the backend was cleared when the request failed.
    if (chat) {
      chat.messages.push({ role: "assistant", phase: "error", sources: [],
        content: "The conversation could not be reset. History was retained. Please retry Clear conversation." });
      saveState();
      renderConversation();
    }
  } finally {
    state.isResetting = false;
    controls.forEach((control) => { control.disabled = false; });
    el.input.focus();
  }
}

function bindEvents() {
  el.form.addEventListener("submit", handleSubmit);
  el.input.addEventListener("input", autoResizeInput);
  el.input.addEventListener("keydown", (event) => {
    if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault();
      el.form.requestSubmit();
    }
  });

  el.stopBtn.addEventListener("click", () => {
    state.abortController?.abort();
  });

  el.newChatBtn.addEventListener("click", createNewChat);
  el.composerNew.addEventListener("click", createNewChat);

  el.clearChatBtn.addEventListener("click", clearConversation);

  el.sidebarToggle.addEventListener("click", () => {
    el.shell.classList.toggle("sidebar-collapsed");
  });

  syncSidebarForViewport();
  window.addEventListener("resize", syncSidebarForViewport);
}

function syncSidebarForViewport() {
  const isMobile = window.matchMedia("(max-width: 768px)").matches;
  if (isMobile) {
    el.shell.classList.add("sidebar-collapsed");
  } else {
    el.shell.classList.remove("sidebar-collapsed");
  }
}

loadState();
setRandomGreeting();
bindEvents();
renderRecent();
renderConversation();
autoResizeInput();
el.input.focus();
