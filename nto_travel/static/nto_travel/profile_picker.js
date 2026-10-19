(() => {
    const picker = document.getElementById('nto-profile-picker');
    if (!picker) return;
    const data = JSON.parse(document.getElementById('nto-profile-data').textContent);
    const profiles = new Map(data.profiles.map(profile => [profile.id, profile]));
    const selected = data.selected.slice();
    const editable = picker.dataset.editable === 'true';
    const input = picker.querySelector('input[name="profile_order"]');
    const search = document.getElementById('nto-profile-search');
    const results = document.getElementById('nto-profile-results');
    const list = document.getElementById('nto-profile-selected');
    const city = document.getElementById('nto-trip-city');
    const multipleCities = document.getElementById('nto-profile-multiple-cities');
    const announcement = document.getElementById('nto-profile-announcement');

    function element(tag, className, text) {
        const node = document.createElement(tag);
        node.className = className;
        if (text !== undefined) node.textContent = text;
        return node;
    }

    function renderResults() {
        if (!editable) return;
        const query = search.value.trim().toLocaleLowerCase('ru');
        const available = data.profiles.filter(profile => profile.active && !selected.includes(profile.id));
        const matches = available.filter(profile => `${profile.name} ${profile.city}`.toLocaleLowerCase('ru').includes(query));
        results.replaceChildren();
        for (const profile of matches.slice(0, 10)) {
            const button = element('button', 'list-group-item list-group-item-action nto-profile-result');
            button.type = 'button';
            button.setAttribute('aria-label', `Добавить: ${profile.name} — ${profile.city}`);
            button.append(element('span', 'd-block', profile.name), element('small', 'text-muted', profile.city));
            button.addEventListener('click', () => {
                selected.push(profile.id);
                search.value = '';
                renderSelected();
                renderResults();
                announcement.textContent = `Добавлен профиль «${profile.name}», приоритет ${selected.length}.`;
                search.focus();
            });
            results.append(button);
        }
        if (!matches.length) results.append(element('p', 'text-muted p-2 mb-0', available.length ? 'Ничего не найдено.' : (data.profiles.some(profile => profile.active) ? 'Все доступные профили добавлены.' : 'Профили пока недоступны.')));
        if (matches.length > 10) results.append(element('p', 'text-muted small p-2 mb-0', 'Уточни название или город, чтобы найти другие профили.'));
    }

    function renderSelected(focusId, focusAction) {
        const rows = [];
        let focusTarget;
        selected.forEach((id, index) => {
            const profile = profiles.get(id);
            const row = element('li', 'nto-profile-row border rounded p-3 mb-2');
            row.tabIndex = -1;
            row.append(element('span', 'badge bg-secondary rounded-pill mt-1', String(index + 1)));
            const info = element('div', 'nto-profile-info');
            info.append(element('strong', 'd-block', profile.name), element('small', 'text-muted', profile.city));
            if (!profile.active) info.append(element('small', 'd-block text-warning', 'Профиль больше недоступен для выбора.'));
            row.append(info);
            let focusButton;
            if (editable) {
                const controls = element('div', 'nto-profile-controls');
                for (const [action, label, text, disabled] of [
                    ['up', `Поднять: ${profile.name}`, '↑', index === 0],
                    ['down', `Опустить: ${profile.name}`, '↓', index === selected.length - 1],
                    ['remove', `Удалить: ${profile.name}`, 'Удалить', false],
                ]) {
                    const button = element('button', 'btn btn-sm btn-outline-secondary', text);
                    button.type = 'button';
                    button.disabled = disabled;
                    button.setAttribute('aria-label', label);
                    button.title = label;
                    if (focusId === id && focusAction === action && !disabled) focusButton = button;
                    button.addEventListener('click', () => {
                        if (action === 'remove') {
                            selected.splice(index, 1);
                            renderSelected();
                            renderResults();
                            announcement.textContent = `Профиль «${profile.name}» удалён.`;
                            search.focus();
                        } else {
                            const target = index + (action === 'up' ? -1 : 1);
                            [selected[index], selected[target]] = [selected[target], selected[index]];
                            renderSelected(id, action);
                            announcement.textContent = `Профиль «${profile.name}», приоритет ${target + 1}.`;
                        }
                    });
                    controls.append(button);
                }
                row.append(controls);
            }
            rows.push(row);
            if (focusId === id) focusTarget = focusButton || row;
        });
        if (!selected.length) rows.push(element('li', 'text-muted', 'Профили пока не выбраны.'));
        list.replaceChildren(...rows);
        input.value = JSON.stringify(selected);
        city.textContent = selected.length ? profiles.get(selected[0]).city : '—';
        multipleCities.hidden = new Set(selected.map(id => profiles.get(id).city)).size <= 1;
        if (focusTarget) focusTarget.focus({preventScroll: true});
    }

    if (editable) search.addEventListener('input', renderResults);
    renderSelected();
    renderResults();
})();
