// Optional cost preview; the server validates dates and fixes the actual rate.
(() => {
  const quote = document.querySelector('[data-rental-quote]');
  if (!quote) return;
  const count = document.getElementById('id_count');
  const start = document.getElementById('id_start');
  const end = document.getElementById('id_end');
  const total = quote.querySelector('[data-rental-total]');
  const rate = Number(quote.dataset.rate);
  function update() {
    const people = Number(count.value);
    const begin = Date.parse(`${start.value}T00:00:00Z`);
    const finish = Date.parse(`${end.value}T00:00:00Z`);
    const days = (finish - begin) / 86400000 + 1;
    if (!Number.isInteger(people) || people < 1 || !Number.isInteger(days) || days < 1) {
      total.textContent = 'выберите даты и количество';
      return;
    }
    total.textContent = new Intl.NumberFormat('ru-RU', {style: 'currency', currency: 'RUB'}).format(rate * people * days);
  }
  [count, start, end].forEach(field => field.addEventListener('input', update));
  update();
})();
