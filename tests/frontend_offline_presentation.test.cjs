// Actual offline-only renderer; no browser, provider or network.
const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');

function renderer() {
  const context = vm.createContext({
    OFFLINE_CITATION_TITLES: {'SRC-testfixture': 'Goods receipt'},
    document: {createElement() {return {
      dataset:{}, children:[], appendChild(child) {this.children.push(child);},
      set innerHTML(value) {throw new Error('Unsafe HTML insertion');},
    };}},
  });
  vm.runInContext(fs.readFileSync(path.join(__dirname,'../offline_demo/presentation.js'),'utf8'),context);
  return context;
}

test('readable inline references preserve original text and unknown handles', () => {
  const context = renderer();
  const original = 'Example [SRC-testfixture] and [SRC-other]';
  assert.equal(context.readableReferences(original),'Example [Goods receipt] and [SRC-other]');
  assert.equal(original,'Example [SRC-testfixture] and [SRC-other]');
});

test('short inert source title retains exact citation ID and source locator', () => {
  const context = renderer();
  const panel = context.createSourcesPanel([{
    id:'TEST_ONLY-receipt', title:'<img src=x onerror=attack()>',
    citation_handle:'SRC-testfixture', source_file:'offline_demo/fixtures.py', metadata:{},
  }]);
  const chip = panel.children[0];
  assert.equal(chip.textContent,'<img src=x onerror=attack()>');
  assert.equal(chip.dataset.citationHandle,'SRC-testfixture');
  assert.equal(JSON.parse(chip.title).id,'TEST_ONLY-receipt');
  assert.equal(JSON.parse(chip.title).citation_handle,'SRC-testfixture');
});
