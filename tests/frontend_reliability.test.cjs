// Runs the actual frontend controller in a minimal DOM harness; no browser or network.
const { test } = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const { webcrypto } = require("node:crypto");

class Element {
  constructor() {
    this.dataset = {};
    this.style = {};
    this.classList = { toggle() {}, add() {} };
    this.children = [];
    this.htmlWrites = [];
    this.value = "";
    this.textContent = "";
  }
  set innerHTML(value) { this.htmlWrites.push(value); this.textContent = ""; }
  get innerHTML() { return this.htmlWrites.at(-1) || ""; }
  appendChild(child) { this.children.push(child); }
  querySelectorAll() { return []; }
  querySelector() { return null; }
  focus() {}
}

function setup(fetch) {
  const node = { wrapper: new Element(), content: new Element() };
  const elements = new Map();
  const stored = new Map();
  const selected = new Map();
  const context = vm.createContext({
    fetch, node, Element, AbortController, TextDecoder, console,
    crypto: webcrypto,
    document: {
      querySelector: () => new Element(),
      getElementById(id) {
        if (!elements.has(id)) elements.set(id, new Element());
        return elements.get(id);
      },
      createElement: (tag) => Object.assign(new Element(), {tagName: tag.toUpperCase()}),
    },
    sessionStorage: {setItem:(k,v)=>selected.set(k,v), getItem:k=>selected.get(k) ?? null},
    localStorage: {
      setItem: (key, value) => stored.set(key, value),
      getItem: (key) => stored.get(key) || null,
    },
  });
  const source = fs.readFileSync(path.join(__dirname, "../web/js/app.js"), "utf8");
  // Skip only startup DOM event wiring. sendMessage/streamChat/error handling are unmodified.
  vm.runInContext(source.slice(0, source.lastIndexOf("\nloadState();")), context);
  vm.runInContext(`
    state.chats = [{id:'demo', title:'New chat', sessionId:null, messages:[]}];
    state.activeChatId = 'demo';
    createStreamingAssistantMessage = () => node;
    const renderMessageForTest = createMessageElement;
    createMessageElement = () => new Element();
    createActionBar = () => new Element();
    createSourcesPanel = () => new Element();
    scrollToBottom = () => {};
    autoResizeInput = () => {};
    renderRecent = () => {};
  `, context);
  return {
    node, stored, selected, elements,
    run: (code) => vm.runInContext(code, context),
    messages: () => JSON.parse(vm.runInContext("JSON.stringify(state.chats[0].messages)", context)),
  };
}

function response(events, options = {}) {
  const data = options.raw ?? events.map((event) => `data: ${JSON.stringify(event)}\n\n`).join("");
  const bytes = new TextEncoder().encode(data);
  const pieces = options.fragmented ? Array.from(bytes, (b) => Uint8Array.of(b)) : [bytes];
  return {
    ok: true,
    body: new ReadableStream({
      start(controller) {
        for (const piece of pieces) controller.enqueue(piece);
        controller.close();
      },
    }),
  };
}

test("main composer submits clarification answers with the same session", async () => {
  const calls = [];
  const app = setup(async (url, options) => {
    calls.push({url, body: JSON.parse(options.body)});
    const answer = calls.length === 1 ? "Which screen were you using?" : "Do you remember a message?";
    return response([
      {type:"session", session_id:"TEST_ONLY-clarification"},
      {type:"done", answer, session_id:"TEST_ONLY-clarification", complete:true, phase:"clarifying"},
    ]);
  });
  app.elements.get("query-input").value = "My goods receipt fails";
  await app.run("handleSubmit({preventDefault(){}})");
  assert.equal(app.messages().at(-1).phase, "clarifying");
  assert.equal(app.elements.get("query-input").disabled, false);
  assert.equal(app.node.wrapper.children.some(n => ["INPUT", "FORM", "TEXTAREA"].includes(n.tagName)), false);
  app.elements.get("query-input").value = "not sure";
  await app.run("handleSubmit({preventDefault(){}})");
  assert.equal(calls[1].url, "/chat/stream");
  assert.equal(calls[1].body.query, "not sure");
  assert.equal(calls[1].body.session_id, "TEST_ONLY-clarification");
  assert.equal(app.messages().at(-2).content, "not sure");
  assert.equal(app.messages().at(-1).content, "Do you remember a message?");
});

test("restored clarifying messages render questions without inline inputs or forms", () => {
  const app = setup(async () => response([]));
  const message = app.run("renderMessageForTest({role:'assistant',content:'Which screen were you using?',phase:'clarifying'})");
  const tags = [];
  function walk(node) { tags.push(node.tagName); node.children.forEach(walk); }
  walk(message);
  assert.equal(tags.some(tag => ["INPUT", "TEXTAREA", "FORM"].includes(tag)), false);
  assert.match(message.children[0].innerHTML, /Which screen were you using/);
});

test("blocked browser storage does not break sending or control recovery", async () => {
  const app = setup(async () => response([
    { type: "done", answer: "TEST_ONLY answer", session_id: "fixture-session", complete: true },
  ]));
  app.run("localStorage.setItem = () => { throw new Error('TEST_ONLY storage quota'); }");
  await app.run("sendMessage('TEST_ONLY question')");
  assert.equal(app.messages().at(-1).content, "TEST_ONLY answer");
  assert.equal(app.run("state.isStreaming"), false);
});

test("new chat cancels its request and starts without an inherited session", () => {
  const app = setup(async () => response([]));
  app.run("state.sessionId = 'original'; state.chats[0].sessionId = 'original'; state.activeRequest = {chat:state.chats[0],controller:new AbortController()}; setStreamingState(true); createNewChat();");
  assert.equal(app.run("state.sessionId"), null);
  assert.equal(app.run("state.activeChatId"), null);
  assert.equal(app.run("state.activeRequest"), null);
  assert.equal(app.messages().at(-1).phase, "error");
  assert.equal(app.run("ensureActiveChat().sessionId"), null);
  assert.equal(app.elements.get("new-chat-btn").disabled, false);
});

test("failed reset retains session and history with feedback, then permits retry", async () => {
  let fail = true;
  const app = setup(async () => ({ok: !fail, status: fail ? 500 : 200}));
  app.run("renderConversation = () => {}; state.sessionId = 'original'; state.chats[0].sessionId = 'original'; state.chats[0].messages = [{role:'user', content:'TEST_ONLY history'}]");
  await app.run("clearConversation()");
  assert.equal(app.run("state.sessionId"), "original");
  assert.equal(app.messages()[0].content, "TEST_ONLY history");
  assert.match(app.messages().at(-1).content, /could not be reset.*retained/);
  assert.equal(app.run("state.isResetting"), false);
  fail = false;
  await app.run("clearConversation()");
  assert.equal(app.run("state.sessionId"), null);
  assert.deepEqual(app.messages(), []);
});

test("provider error text is inert and controls recover", async () => {
  const malicious = '<img src=x onerror="globalThis.attacked=true">';
  const app = setup(async () => response([{ type: "error", message: malicious }]));
  await app.run("sendMessage('Explain ME21N')");
  assert.equal(app.node.content.textContent, malicious);
  assert.equal(app.node.content.htmlWrites.some((s) => s.includes("<img")), false);
  assert.equal(app.messages().at(-1).phase, "error");
  assert.equal(app.run("state.isStreaming"), false);
  assert.equal(app.elements.get("query-input").disabled, false);
});

test("EOF without done is incomplete, not a saved successful answer", async () => {
  const app = setup(async () => response([{ type: "token", content: "Partial answer" }]));
  await app.run("sendMessage('Explain ME21N')");
  assert.match(app.node.content.textContent, /before the answer was complete/);
  assert.equal(app.messages().at(-1).phase, "error");
  assert.equal(app.messages().some((m) => m.content === "Partial answer"), false);
});

test("completed fragmented UTF-8 SSE saves an answer and session", async () => {
  const app = setup(async () => response([
    { type: "session", session_id: "demo-session" },
    { type: "token", content: "Supported café" },
    { type: "done", answer: "Supported café", session_id: "demo-session", complete: true },
  ], { fragmented: true }));
  await app.run("sendMessage('Explain ME21N')");
  assert.equal(app.messages().at(-1).content, "Supported café");
  assert.equal(app.messages().at(-1).phase, "answering");
  assert.equal(app.run("state.sessionId"), "demo-session");
  assert.equal(JSON.parse(app.stored.get("sap-consultant-ui")).chats[0].sessionId, "demo-session");
});

for (const event of [
  { type: "done", answer: "Partial answer", complete: false },
  { type: "done", answer: "" },
]) {
  test(`invalid completion is rejected: ${JSON.stringify(event)}`, async () => {
    const app = setup(async () => response([event]));
    await app.run("sendMessage('Explain ME21N')");
    assert.equal(app.messages().at(-1).phase, "error");
    assert.match(app.node.content.textContent, /incomplete/);
  });
}

test("status feedback is shown as text while waiting for tokens", async () => {
  const app = setup(async () => response([{ type: "status", message: "Searching knowledge base..." }]));
  await assert.rejects(app.run("streamChat('Explain ME21N', node)"), /before the answer was complete/);
  assert.equal(app.node.content.textContent, "Searching knowledge base...");
});

test("HTTP 429 gets useful safe feedback without reflecting response HTML", async () => {
  const app = setup(async () => ({ ok: false, status: 429, body: null }));
  await app.run("sendMessage('Explain ME21N')");
  assert.match(app.node.content.textContent, /busy.*retry/);
  assert.equal(app.messages().at(-1).phase, "error");
});

test("malformed SSE does not leave controls stuck or save success", async () => {
  const app = setup(async () => response([], { raw: "data: not-json\n\n" }));
  await app.run("sendMessage('Explain ME21N')");
  assert.equal(app.messages().at(-1).phase, "error");
  assert.equal(app.run("state.isStreaming"), false);
  assert.match(app.node.content.textContent, /unreadable response.*retry/);
});

test("abort is explicitly incomplete and persisted as error", async () => {
  const app = setup(async () => { const e = new Error("Stopped"); e.name = "AbortError"; throw e; });
  await app.run("sendMessage('Explain ME21N')");
  assert.match(app.node.content.textContent, /Generation stopped.*incomplete/);
  assert.equal(app.messages().at(-1).phase, "error");
  assert.equal(app.run("state.isStreaming"), false);
});

test("network failure permits a successful retry in the same chat", async () => {
  let calls = 0;
  const app = setup(async () => {
    if (++calls === 1) throw new TypeError("Failed to fetch");
    return response([{ type: "done", answer: "Supported answer", session_id: "retry-session", complete: true }]);
  });
  await app.run("sendMessage('Explain ME21N')");
  assert.equal(app.messages().at(-1).phase, "error");
  assert.match(app.node.content.textContent, /connection.*retry/);
  await app.run("sendMessage('Explain ME21N')");
  assert.equal(app.messages().at(-1).content, "Supported answer");
  assert.equal(app.messages().at(-1).phase, "answering");
});

test("refresh restores only this tab's selected chat and ignores legacy global session", () => {
  const app = setup(async () => response([]));
  app.stored.set("sap-consultant-ui", JSON.stringify({
    activeChatId:"other", sessionId:"WRONG_GLOBAL",
    chats:[{id:"selected",title:"A",sessionId:"SESSION_A",messages:[]},
           {id:"other",title:"B",sessionId:"SESSION_B",messages:[]}],
  }));
  app.selected.set("sap-consultant-selected-chat", "selected");
  app.run("globalThis.performance = {getEntriesByType:()=>[{type:'reload'}]}; loadState()");
  assert.equal(app.run("state.activeChatId"), "selected");
  assert.equal(app.run("state.sessionId"), "SESSION_A");
  app.run("selectConversation('other')");
  assert.equal(app.run("state.sessionId"), "SESSION_B");
  app.run("loadState()");
  assert.equal(app.run("state.sessionId"), "SESSION_B");
});

test("a normal visit starts blank while retaining sidebar history", () => {
  const app = setup(async () => response([]));
  app.stored.set("sap-consultant-ui", JSON.stringify({
    activeChatId:"old",sessionId:"OLD",
    chats:[{id:"old",title:"Old history",sessionId:"OLD",messages:[{role:'user',content:'Old'}]}],
  }));
  app.selected.set("sap-consultant-selected-chat", "old");
  app.run("globalThis.performance = {getEntriesByType:()=>[{type:'navigate'}]}; loadState()");
  assert.equal(app.run("state.activeChatId"), null);
  assert.equal(app.run("state.sessionId"), null);
  assert.equal(app.run("state.chats.length"), 1);
  assert.equal(app.run("ensureActiveChat().sessionId"), null);
  assert.equal(app.selected.get("sap-consultant-selected-chat"), app.run("state.activeChatId"));
});

test("late response cannot change the new chat's session, history or controls", async () => {
  let finishOld, calls=0;
  const app = setup(async () => {
    if (++calls === 1) return new Promise(resolve => {finishOld=resolve;});
    return response([{type:'done',session_id:'NEW_SESSION',answer:'New answer',complete:true}]);
  });
  const old = app.run("sendMessage('Old question')");
  const oldId = app.run("state.activeChatId");
  app.run("createNewChat()");
  await app.run("sendMessage('New question')");
  const newId = app.run("state.activeChatId");
  finishOld(response([{type:'session',session_id:'OLD_SESSION'},
    {type:'done',session_id:'OLD_SESSION',answer:'Late old answer',complete:true}]));
  await old;
  assert.equal(app.run("state.activeChatId"), newId);
  assert.equal(app.run("state.sessionId"), 'NEW_SESSION');
  assert.equal(app.run("getActiveChat().messages.at(-1).content"), 'New answer');
  assert.equal(app.run("state.isStreaming"), false);
  assert.equal(app.run(`state.chats.find(c=>c.id===${JSON.stringify(oldId)}).messages.at(-1).phase`),'error');
  assert.equal(app.run("JSON.stringify(state.chats).includes('Late old answer')"), false);
});

test("switching mid-stream isolates late events from the selected chat", async () => {
  let controller;
  const app = setup(async () => ({ok:true,body:new ReadableStream({start(c){controller=c;}})}));
  app.run("state.chats.push({id:'other',title:'Other',sessionId:'OTHER',messages:[]})");
  const old = app.run("sendMessage('Old question')");
  await new Promise(resolve => setImmediate(resolve));
  app.run("selectConversation('other')");
  controller.enqueue(new TextEncoder().encode('data: {"type":"done","answer":"Late","session_id":"WRONG"}\n\n'));
  await old;
  assert.equal(app.run("state.sessionId"),'OTHER');
  assert.equal(app.run("getActiveChat().messages.length"),0);
});

test("successful deletion removes history and the selected session", async () => {
  const calls=[];
  const app = setup(async (url, options) => {calls.push({url,method:options.method});return {ok:true};});
  app.run("state.chats[0].sessionId='DELETE_ME'; state.sessionId='DELETE_ME'");
  await app.run("deleteConversation('demo')");
  assert.deepEqual(calls,[{url:'/sessions/DELETE_ME',method:'DELETE'}]);
  assert.equal(app.run("state.chats.length"),0);
  assert.equal(app.run("state.sessionId"),null);
  assert.deepEqual(JSON.parse(app.stored.get('sap-consultant-ui')).chats,[]);
});

test("failed deletion retains history/session and permits retry", async () => {
  let fail=true;
  const app=setup(async()=>({ok:!fail,status:fail?500:200}));
  app.run("createActionBar=()=>new Element(); state.chats[0].sessionId='S'; state.sessionId='S'");
  await app.run("deleteConversation('demo')");
  assert.equal(app.run("state.sessionId"),'S');
  assert.match(app.messages().at(-1).content,/could not be deleted.*retained/);
  fail=false; await app.run("deleteConversation('demo')");
  assert.equal(app.run("state.chats.length"),0);
});

test("deleting another conversation keeps the current selection and history", async () => {
  const app=setup(async()=>({ok:false,status:404}));
  app.run("state.sessionId='CURRENT'; state.chats[0].sessionId='CURRENT'; state.chats.push({id:'other',sessionId:'GONE',messages:[],title:'Other'})");
  await app.run("deleteConversation('other')");
  assert.equal(app.run("state.activeChatId"),'demo');
  assert.equal(app.run("state.sessionId"),'CURRENT');
  assert.equal(app.run("state.chats.length"),1);
});

test("legacy duplicate sessions are detached rather than shared between chats", () => {
  const app=setup(async()=>response([]));
  app.stored.set('sap-consultant-ui',JSON.stringify({chats:[
    {id:'a',title:'A',sessionId:'SHARED',messages:[]}, {id:'b',title:'B',sessionId:'SHARED',messages:[]},
  ]}));
  app.selected.set('sap-consultant-selected-chat','b');
  app.run("loadState()");
  assert.equal(app.run("getActiveChat().sessionId"),'SHARED');
  assert.equal(app.run("state.chats.find(c=>c.id==='a').sessionId"),null);
});

test("a new request allocates its own session before headers and ignores global fallback", async () => {
  let body;
  const app=setup(async (url, options)=>{
    body=JSON.parse(options.body);
    return response([{type:'done',session_id:body.session_id,answer:'Answer',complete:true}]);
  });
  app.run("state.sessionId='STALE_GLOBAL'");
  await app.run("sendMessage('Fresh question')");
  assert.ok(body.session_id && body.session_id !== 'STALE_GLOBAL');
  assert.equal(body.session_id,app.run("getActiveChat().sessionId"));
});
