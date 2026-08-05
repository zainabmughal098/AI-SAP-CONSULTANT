const STORAGE_KEY = "sap-consultant-ui";

const state = {
  sessionId: null,
  chats: [],
  activeChatId: null,
  isStreaming: false,
  abortController: null,
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
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) return;
    const saved = JSON.parse(raw);
    state.chats = saved.chats || [];
    state.activeChatId = saved.activeChatId || null;
    state.sessionId = saved.sessionId || null;
  } catch {
    state.chats = [];
  }
}

function saveState() {
  localStorage.setItem(
    STORAGE_KEY,
    JSON.stringify({
      chats: state.chats,
      activeChatId: state.activeChatId,
      sessionId: state.sessionId,
    }),
  );
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
    sessionId: state.sessionId,
    createdAt: Date.now(),
  };
  state.chats.unshift(chat);
  state.activeChatId = chat.id;
  saveState();
  renderRecent();
  return chat;
}

function createNewChat() {
  state.activeChatId = null;
  state.sessionId = null;
  renderConversation();
  renderRecent();
  saveState();
  setRandomGreeting();
  el.input.focus();
}

function setRandomGreeting() {
  el.welcomeTitle.textContent = greetings[Math.floor(Math.random() * greetings.length)];
}

function renderRecent() {
  el.recentList.innerHTML = "";
  state.chats.slice(0, 20).forEach((chat) => {
    const button = document.createElement("button");
    button.type = "button";
    button.className = `recent-item${chat.id === state.activeChatId ? " active" : ""}`;
    button.textContent = chat.title;
    button.title = chat.title;
    button.addEventListener("click", () => {
      state.activeChatId = chat.id;
      state.sessionId = chat.sessionId || null;
      renderConversation();
      renderRecent();
      saveState();
    });
    el.recentList.appendChild(button);
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

  chat.messages.forEach((message) => {
    el.messagesInner.appendChild(createMessageElement(message));
  });
  scrollToBottom();
}

function createMessageElement(message) {
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

  wrapper.appendChild(createActionBar(message.content || ""));
  return wrapper;
}

function createSourcesPanel(sources) {
  const panel = document.createElement("div");
  panel.className = "sources-panel";
  sources.slice(0, 4).forEach((source) => {
    const chip = document.createElement("span");
    chip.className = "source-chip";
    chip.textContent = `${source.document_type || "record"} · ${source.title || source.source_file || "Unknown"}`;
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
}

async function streamChat(query, assistantNode) {
  state.abortController = new AbortController();
  setStreamingState(true);

  const chat = ensureActiveChat();
  let assistantText = "";
  let sources = [];

  const response = await fetch("/chat/stream", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      query,
      session_id: state.sessionId,
    }),
    signal: state.abortController.signal,
  });

  if (!response.ok || !response.body) {
    throw new Error("Unable to stream response from server.");
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  while (true) {
    const { value, done } = await reader.read();
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
        assistantText = event.answer || assistantText;
        state.sessionId = event.session_id;
        chat.sessionId = event.session_id;
      }
    }
  }

  assistantNode.wrapper.dataset.streaming = "false";
  assistantNode.content.innerHTML = formatMarkdown(assistantText);

  if (sources.length) {
    assistantNode.wrapper.appendChild(createSourcesPanel(sources));
  }
  assistantNode.wrapper.appendChild(createActionBar(assistantText));

  chat.messages.push({ role: "assistant", content: assistantText, sources });
  if (chat.title === "New chat") {
    chat.title = query.slice(0, 42);
  }
  saveState();
  renderRecent();
}

async function handleSubmit(event) {
  event.preventDefault();
  const query = el.input.value.trim();
  if (!query || state.isStreaming) return;

  const chat = ensureActiveChat();
  el.welcome.hidden = true;
  el.messages.hidden = false;
  el.chatStage.classList.add("has-messages");

  chat.messages.push({ role: "user", content: query });
  el.messagesInner.appendChild(createMessageElement({ role: "user", content: query }));

  el.input.value = "";
  autoResizeInput();
  scrollToBottom();

  const assistantNode = createStreamingAssistantMessage();

  try {
    await streamChat(query, assistantNode);
  } catch (error) {
    if (error.name === "AbortError") {
      assistantNode.content.innerHTML = formatMarkdown(
        assistantNode.content.textContent || "Generation stopped.",
      );
      return;
    }
    assistantNode.content.innerHTML = `<p>${error.message || "Something went wrong."}</p>`;
  } finally {
    setStreamingState(false);
    state.abortController = null;
    el.input.focus();
  }
}

function autoResizeInput() {
  el.input.style.height = "auto";
  el.input.style.height = `${Math.min(el.input.scrollHeight, 160)}px`;
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

  el.clearChatBtn.addEventListener("click", async () => {
    if (state.sessionId) {
      await fetch(`/sessions/${state.sessionId}/reset`, { method: "POST" }).catch(() => {});
    }
    const chat = getActiveChat();
    if (chat) {
      chat.messages = [];
      chat.sessionId = null;
    }
    state.sessionId = null;
    saveState();
    renderConversation();
    setRandomGreeting();
  });

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
