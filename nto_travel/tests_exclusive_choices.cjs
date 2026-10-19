const assert = require('node:assert/strict');
const test = require('node:test');
const vm = require('node:vm');
const fs = require('node:fs');
const path = require('node:path');
const source = fs.readFileSync(path.join(__dirname, 'static/nto_travel/exclusive_choices.js'), 'utf8');

test('exclusive choices clear other answers; regular answers clear only exclusive choices', () => {
    const groups = {
        previous_payers: ['region', 'parents', 'local', 'unknown'],
        possible_payers: ['region', 'parents', 'not_needed', 'unknown', 'none'],
        circumstances: ['low_income', 'large_family', 'none', 'declined'],
        preparation_methods: ['team', 'camps', 'none'],
    };
    const nodes = Object.fromEntries(Object.entries(groups).map(([name, values]) => [name, values.map(value => ({
        value, checked: false,
        addEventListener(type, handler) { this.change = handler; },
        select() { this.checked = true; this.change(); },
    }))]));
    vm.runInNewContext(source, {document: {querySelectorAll(selector) {
        return nodes[selector.match(/name="([^"]+)"/)[1]];
    }}});
    for (const group of Object.values(nodes)) {
        group[0].select();
        group[1].select();
        assert.equal(group.filter(node => node.checked).length, 2);
        for (const exclusive of group.slice(2)) {
            exclusive.select();
            assert.deepEqual(group.filter(node => node.checked), [exclusive]);
        }
        group[0].select();
        assert.deepEqual(group.filter(node => node.checked), [group[0]]);
        group[0].checked = false;
        group[0].change();
        assert.equal(group.filter(node => node.checked).length, 0);
    }
});
