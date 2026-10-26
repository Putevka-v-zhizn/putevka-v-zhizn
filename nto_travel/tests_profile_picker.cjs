const assert = require('node:assert/strict');
const test = require('node:test');
const vm = require('node:vm');
const fs = require('node:fs');
const path = require('node:path');
const source = fs.readFileSync(path.join(__dirname, 'static/nto_travel/profile_picker.js'), 'utf8');

// Minimal DOM doubles exercise the real event handlers without a browser or dependencies.
function setup(editable, selected = []) {
    let focused;
    const focusCalls = [];
    class Element {
        constructor(tag) { this.tag = tag; this.children = []; this.events = {}; this.attributes = {}; this.value = ''; }
        append(...nodes) { this.children.push(...nodes); }
        replaceChildren(...nodes) { this.children = nodes; }
        setAttribute(key, value) { this.attributes[key] = value; }
        addEventListener(type, handler) { this.events[type] = handler; }
        focus(options) {
            focused = this;
            focusCalls.push({options, rowCount: ids['nto-profile-selected'].children.length});
        }
        click() { if (!this.disabled) this.events.click(); }
    }
    const profiles = [
        {id: '1', name: 'Анализ данных', city: 'Казань', active: true},
        {id: '2', name: 'Искусственный интеллект', city: 'Москва', active: true},
        {id: '3', name: 'Робототехника', city: 'Томск', active: false},
    ];
    const ids = Object.fromEntries(['nto-profile-picker', 'nto-profile-data', 'nto-profile-search', 'nto-profile-results', 'nto-profile-selected', 'nto-trip-city', 'nto-profile-multiple-cities', 'nto-profile-announcement'].map(id => [id, new Element('div')]));
    ids['nto-profile-picker'].dataset = {editable: String(editable)};
    const hidden = new Element('input');
    ids['nto-profile-picker'].querySelector = () => hidden;
    ids['nto-profile-data'].textContent = JSON.stringify({profiles, selected});
    vm.runInNewContext(source, {document: {getElementById: id => ids[id], createElement: tag => new Element(tag)}});
    const list = ids['nto-profile-selected'];
    const results = ids['nto-profile-results'];
    const search = ids['nto-profile-search'];
    function find(nodes, label) {
        for (const node of nodes) {
            if (node.attributes['aria-label'] === label) return node;
            const child = find(node.children, label);
            if (child) return child;
        }
    }
    return {ids, hidden, list, results, search, focusCalls, focused: () => focused, click: label => {
        const button = find([...list.children, ...results.children], label);
        assert.ok(button, `Missing button: ${label}`);
        button.click();
    }};
}

test('search, add, reorder and remove keep priorities and destination in sync', () => {
    const ui = setup(true);
    ui.search.value = 'казань';
    ui.search.events.input();
    assert.equal(ui.results.children.length, 1);
    ui.click('Добавить: Анализ данных — Казань');
    assert.equal(ui.hidden.value, '["1"]');
    assert.equal(ui.ids['nto-trip-city'].textContent, 'Казань');
    ui.click('Добавить: Искусственный интеллект — Москва');
    assert.equal(ui.hidden.value, '["1","2"]');
    assert.equal(ui.ids['nto-profile-multiple-cities'].hidden, false);
    ui.click('Поднять: Искусственный интеллект');
    assert.equal(ui.hidden.value, '["2","1"]');
    assert.equal(ui.ids['nto-trip-city'].textContent, 'Москва');
    assert.equal(ui.list.children[0].children[0].textContent, '1');
    assert.equal(ui.list.children[1].children[0].textContent, '2');
    ui.click('Опустить: Искусственный интеллект');
    assert.equal(ui.hidden.value, '["1","2"]');
    ui.click('Удалить: Анализ данных');
    assert.equal(ui.hidden.value, '["2"]');
    assert.equal(ui.ids['nto-trip-city'].textContent, 'Москва');
    assert.equal(ui.focused(), ui.search);
    ui.click('Удалить: Искусственный интеллект');
    assert.equal(ui.hidden.value, '[]');
    assert.equal(ui.ids['nto-trip-city'].textContent, '—');
    assert.equal(ui.results.children.length, 2); // inactive profiles are never offered
    ui.search.value = 'нет такого профиля';
    ui.search.events.input();
    assert.equal(ui.results.children[0].textContent, 'Ничего не найдено.');
});

test('read-only picker preserves order and offers no editing controls', () => {
    const ui = setup(false, ['2', '1']);
    assert.equal(ui.hidden.value, '["2","1"]');
    assert.equal(ui.ids['nto-trip-city'].textContent, 'Москва');
    assert.equal(ui.list.children[0].children.length, 2);
    assert.equal(ui.results.children.length, 0);
});

test('reordering restores focus without scrolling after the whole list is rendered', () => {
    const ui = setup(true, ['1', '2', '3']);
    for (const label of ['Поднять: Искусственный интеллект', 'Опустить: Искусственный интеллект']) {
        ui.click(label);
        const call = ui.focusCalls.at(-1);
        assert.equal(call.options.preventScroll, true);
        assert.equal(call.rowCount, 3);
    }
    assert.equal(ui.focusCalls.length, 2);
});
