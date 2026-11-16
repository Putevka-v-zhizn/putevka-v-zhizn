(() => {
 const ready = new WeakSet();
 function init(root) {
  const fields = [...root.querySelectorAll('select[multiple][data-multiselect]')];
  if(root.matches?.('select[multiple][data-multiselect]')) fields.push(root);
  for(const select of fields) {
   if(ready.has(select)) continue;
   ready.add(select);
   const box = document.createElement('fieldset');
   box.className='border rounded p-2 bg-white';
   const legend=document.createElement('legend'); legend.className='fs-6'; legend.textContent='Выберите профили'; box.append(legend);
   const search=document.createElement('input'); search.type='search'; search.placeholder='Поиск…'; search.className='form-control mb-2'; search.setAttribute('aria-label','Поиск профилей'); box.append(search);
   const list=document.createElement('div'); list.style.maxHeight='220px'; list.style.overflowY='auto'; box.append(list);
   for(const option of select.options) {
    const label=document.createElement('label'); label.className='d-flex gap-2 p-1';
    const check=document.createElement('input'); check.type='checkbox'; check.checked=option.selected; check.disabled=option.disabled||select.disabled; check.className='form-check-input flex-shrink-0';
    const text=document.createElement('span'); text.textContent=option.text; label.append(check,text); list.append(label);
    check.addEventListener('change',()=>{option.selected=check.checked; select.dispatchEvent(new Event('change',{bubbles:true}));});
   }
   search.addEventListener('input',()=>{for(const label of list.children) label.classList.toggle('d-none',!label.textContent.toLocaleLowerCase().includes(search.value.trim().toLocaleLowerCase()));});
   select.after(box); select.hidden=true;
  }
 }
 document.addEventListener('DOMContentLoaded',()=>init(document));
 document.addEventListener('htmx:load',e=>init(e.detail.elt));
})();
