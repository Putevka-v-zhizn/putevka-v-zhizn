(() => {
    const cost = document.getElementById('id_ticket_cost');
    if (!cost) return;
    for (const button of document.querySelectorAll('[data-ticket-delta]')) {
        button.addEventListener('click', () => {
            const value = Number(cost.value.replace(/\s/g, '').replace(',', '.'));
            if (!Number.isFinite(value)) return;
            cost.value = Math.min(10000000, Math.max(0, Math.round(value) + Number(button.dataset.ticketDelta)));
            cost.dispatchEvent(new Event('input', {bubbles: true}));
        });
    }
})();
