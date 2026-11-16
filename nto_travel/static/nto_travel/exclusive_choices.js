(() => {
    const groups = {
        previous_payers: ['local', 'unknown'],
        possible_payers: ['not_needed', 'unknown', 'none'],
        circumstances: ['none', 'declined'],
        preparation_methods: ['none'],
    };
    for (const [name, exclusive] of Object.entries(groups)) {
        const checkboxes = [...document.querySelectorAll(`input[type="checkbox"][name="${name}"]`)];
        for (const checkbox of checkboxes) {
            checkbox.addEventListener('change', () => {
                if (!checkbox.checked) return;
                for (const other of checkboxes) {
                    if (other !== checkbox && (exclusive.includes(checkbox.value) || exclusive.includes(other.value))) {
                        other.checked = false;
                    }
                }
            });
        }
    }
})();
