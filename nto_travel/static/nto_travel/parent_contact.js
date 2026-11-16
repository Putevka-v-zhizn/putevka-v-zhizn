(() => {
    for (const adult of document.querySelectorAll('select[name="is_adult"], select[name="personal-is_adult"]')) {
        const prefix = adult.name.slice(0, -'is_adult'.length);
        const fields = ['parent_name', 'parent_phone'].map(name => document.getElementById(`id_${prefix}${name}`));
        const update = () => {
            for (const field of fields) {
                if (!field) continue;
                field.closest('.mb-3').hidden = adult.value === 'yes';
            }
        };
        adult.addEventListener('change', update);
        update();
    }
})();
