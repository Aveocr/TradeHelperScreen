/* ═══════════════════════════════════════
   AI Trading Assistant — main.js
   ═══════════════════════════════════════ */

// ── Форматирование ─────────────────────────────────────────────────────────

function fmtPrice(val) {
  if (!val && val !== 0) return '—';
  const n = parseFloat(val);
  if (n >= 1000)      return n.toLocaleString('ru-RU', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  if (n >= 1)         return n.toFixed(4);
  if (n >= 0.0001)    return n.toFixed(6);
  return n.toExponential(4);
}

function fmtVol(val) {
  if (!val) return '—';
  const n = parseFloat(val);
  if (n >= 1e9) return (n / 1e9).toFixed(2) + 'B$';
  if (n >= 1e6) return (n / 1e6).toFixed(2) + 'M$';
  if (n >= 1e3) return (n / 1e3).toFixed(0) + 'K$';
  return n.toFixed(0) + '$';
}

// ── Проверка соединения (polling каждые 30с) ───────────────────────────────

let _connOk = false;

async function checkConnection() {
  const dot   = document.getElementById('conn-dot');
  const label = document.getElementById('conn-label');
  try {
    const r = await fetch('/api/market/stats', { signal: AbortSignal.timeout(5000) });
    if (!r.ok) throw new Error();
    const data = await r.json();

    if (dot)   { dot.className = 'status-dot ok'; }
    if (label) { label.textContent = 'Gate.io'; }
    _connOk = true;

    // Обновляем P&L в navbar если есть элементы
    updateStatsInPage(data);
  } catch {
    if (dot)   { dot.className = 'status-dot err'; }
    if (label) { label.textContent = 'Нет соединения'; }
    _connOk = false;
  }
}

function updateStatsInPage(data) {
  // Обновляет карточки на дашборде без перезагрузки страницы (если они есть)
  const pnlEl = document.getElementById('live-pnl');
  if (pnlEl) {
    const sign = data.realized_pnl >= 0 ? '+' : '';
    pnlEl.textContent = `${sign}${data.realized_pnl.toFixed(2)}$`;
    pnlEl.className = data.realized_pnl >= 0 ? 'val-green' : 'val-red';
  }
}

// ── Init ───────────────────────────────────────────────────────────────────

document.addEventListener('DOMContentLoaded', () => {
  checkConnection();
  setInterval(checkConnection, 30_000);
});
