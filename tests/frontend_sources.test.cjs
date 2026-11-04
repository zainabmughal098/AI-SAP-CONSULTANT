// Actual source-chip renderer, synthetic fixtures, no browser/network.
const { test } = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");
const path = require("node:path");

function renderer() {
  const source = fs.readFileSync(path.join(__dirname, "../web/js/app.js"), "utf8");
  const start = source.indexOf("function createSourcesPanel(");
  const end = source.indexOf("\nfunction createActionBar(", start);
  const context = vm.createContext({ document: { createElement() {
    return { children: [], appendChild(child) { this.children.push(child); } };
  } } });
  vm.runInContext(source.slice(start, end), context);
  return context.createSourcesPanel;
}

test("all citation handles remain visible, including the fifth source", () => {
  const sources = Array.from({ length: 5 }, (_, i) => ({
    id: `DEMO-${i}`, citation_handle: `SRC-demo${i}`, title: "DEMO reference",
    source_file: "DEMO.csv", metadata: { row: i, page: 0 }, authority: "DEMO / SIMULATED", source_kind: "synthetic",
  }));
  const panel = renderer()(sources);
  assert.equal(panel.children.length, 5);
  for (const [index, chip] of panel.children.entries()) {
    assert.match(chip.textContent, new RegExp(`\\[SRC-demo${index}\\]`));
    assert.match(chip.textContent, /DEMO \/ SIMULATED/);
    const locator = JSON.parse(chip.title);
    assert.equal(locator.id, `DEMO-${index}`);
    assert.equal(locator.metadata.row, index);
    assert.equal(locator.metadata.page, 0);
  }
});

test("source titles and locators remain inert text", () => {
  const text = '<img src=x onerror="attack()">';
  const chip = renderer()([{ title: text, citation_handle: "SRC-demo", metadata: { row: text } }]).children[0];
  assert.ok(chip.textContent.includes(text));
  assert.equal(chip.innerHTML, undefined);
  assert.equal(JSON.parse(chip.title).metadata.row, text);
});
