// Shared UI components for Auto Analytics KZ
const { useState, useEffect, useRef, useMemo } = React;

// ── Formatting ───────────────────────────────
const fmt = {
  int: (n) => (n ?? 0).toLocaleString('ru-RU'),
  price: (n) => {
    if (n == null) return '—';
    if (n >= 1_000_000) return `${(n/1_000_000).toFixed(1)} млн`;
    if (n >= 1_000) return `${(n/1_000).toFixed(0)}К`;
    return n.toString();
  },
  priceFull: (n) => (n ?? 0).toLocaleString('ru-RU'),
  pct: (n, digits=1) => `${n > 0 ? '+' : ''}${n.toFixed(digits)}%`,
  km: (n) => `${n} тыс км`,
};

// ── Sparkline ────────────────────────────────
function Sparkline({ data, width = 72, height = 32, color, fill = true, strokeWidth = 1.5 }) {
  if (!data || data.length === 0) return null;
  const min = Math.min(...data.map(d => d.value));
  const max = Math.max(...data.map(d => d.value));
  const range = max - min || 1;
  const stepX = width / (data.length - 1);
  const points = data.map((d, i) => {
    const x = i * stepX;
    const y = height - ((d.value - min) / range) * height;
    return [x, y];
  });
  const linePath = points.map((p, i) => (i === 0 ? `M${p[0]},${p[1]}` : `L${p[0]},${p[1]}`)).join(' ');
  const fillPath = `${linePath} L${width},${height} L0,${height} Z`;
  const c = color || 'var(--info)';
  return (
    <svg className="sparkline" width={width} height={height} viewBox={`0 0 ${width} ${height}`}>
      {fill && <path className="fill" d={fillPath} fill={c} />}
      <path className="line" d={linePath} stroke={c} strokeWidth={strokeWidth} />
    </svg>
  );
}

// ── KPI Tile ─────────────────────────────────
function KPI({ label, value, unit, delta, foot, sparkData, sparkColor, inverted }) {
  const isUp = delta != null && delta >= 0;
  // For inverted metrics (like liquidity days), down is good
  const good = inverted ? !isUp : isUp;
  return (
    <div className="kpi">
      <div className="kpi-label">{label}</div>
      <div className="kpi-value tnum">
        {value}
        {unit && <span className="unit">{unit}</span>}
      </div>
      {delta != null && (
        <div className={`kpi-delta ${good ? 'up' : 'down'}`}>
          <span className="kpi-arrow">{isUp ? '▲' : '▼'}</span>
          {fmt.pct(Math.abs(delta))}
          <span className="dim" style={{ marginLeft: 4 }}>за 30 дн</span>
        </div>
      )}
      <div className="kpi-foot">{foot}</div>
      {sparkData && (
        <div className="kpi-spark">
          <Sparkline data={sparkData} color={sparkColor} />
        </div>
      )}
    </div>
  );
}

// ── Topbar ───────────────────────────────────
function Topbar({ activePage, onNav }) {
  const lastIndex = PRICE_INDEX[PRICE_INDEX.length - 1].value;
  const prevIndex = PRICE_INDEX[PRICE_INDEX.length - 30].value;
  const indexDelta = ((lastIndex - prevIndex) / prevIndex) * 100;

  const lastUsd = USDKZT[USDKZT.length - 1].value;
  const prevUsd = USDKZT[USDKZT.length - 2].value;
  const usdDelta = ((lastUsd - prevUsd) / prevUsd) * 100;

  const total = SOURCES.reduce((s, x) => s + x.count, 0);

  return (
    <header className="topbar">
      <a href="Dashboard.html" className="brand">
        <span className="brand-dot" />
        <span>
          <div>Авто Аналитика</div>
          <div className="brand-meta">KZ · V1</div>
        </span>
      </a>
      <nav className="nav">
        <a href="Dashboard.html" className={activePage === 'dashboard' ? 'active' : ''}>Дашборд</a>
        <a href="Model.html" className={activePage === 'model' ? 'active' : ''}>Марки</a>
        <a href="#" onClick={e => { e.preventDefault(); }}>Рентабельность</a>
        <a href="#" onClick={e => { e.preventDefault(); }}>Прогноз</a>
      </nav>
      <div className="topbar-spacer" />
      <div className="ticker">
        <span className="ticker-item">
          <span className="live-dot" />
          <span className="ticker-label">LIVE</span>
          <span className="mono tnum">{fmt.int(total)}</span>
          <span className="ticker-label">объявл.</span>
        </span>
        <span className="ticker-item">
          <span className="ticker-label">INDEX</span>
          <span className="mono tnum">{lastIndex.toFixed(1)}</span>
          <span className={`mono ${indexDelta >= 0 ? 'up' : 'down'}`}>
            {indexDelta >= 0 ? '▲' : '▼'} {Math.abs(indexDelta).toFixed(2)}%
          </span>
        </span>
        <span className="ticker-item">
          <span className="ticker-label">USD/KZT</span>
          <span className="mono tnum">{lastUsd.toFixed(2)}</span>
          <span className={`mono ${usdDelta >= 0 ? 'up' : 'down'}`}>
            {usdDelta >= 0 ? '▲' : '▼'} {Math.abs(usdDelta).toFixed(2)}%
          </span>
        </span>
      </div>
      <button className="topbar-btn"><span>⌕</span><span>Поиск</span><span className="kbd">⌘K</span></button>
      <button className="topbar-btn" id="tweaks-trigger"><span>⚙</span></button>
    </header>
  );
}

// ── Filter bar ───────────────────────────────
function FilterBar({ filters, setFilters }) {
  const periods = [
    { id: 7, label: '7Д' }, { id: 30, label: '1М' }, { id: 90, label: '3М' },
    { id: 180, label: '6М' }, { id: 365, label: '1Г' }, { id: 'all', label: 'Все' }
  ];
  const chips = [
    { key: 'brand', label: 'Марка', val: filters.brand || 'Все' },
    { key: 'model', label: 'Модель', val: filters.model || 'Все' },
    { key: 'city',  label: 'Город',  val: filters.city || 'Все' },
    { key: 'year',  label: 'Год',    val: filters.year || 'Любой' },
    { key: 'price', label: 'Цена',   val: filters.price || 'Любая' },
    { key: 'mileage', label: 'Пробег', val: filters.mileage || 'Любой' },
  ];

  return (
    <div className="filterbar">
      <span className="uppercase" style={{ marginRight: 4 }}>фильтры</span>
      {chips.map(c => (
        <button key={c.key} className={`chip ${c.val !== 'Все' && c.val !== 'Любой' && c.val !== 'Любая' ? 'active' : ''}`}>
          <span className="chip-label">{c.label}:</span>
          <span className="chip-val">{c.val}</span>
          <span className="chip-x">+</span>
        </button>
      ))}
      <div className="filterbar-sep" />
      <div className="period-group">
        {periods.map(p => (
          <button key={p.id}
            className={`period-btn ${filters.period === p.id ? 'active' : ''}`}
            onClick={() => setFilters({ ...filters, period: p.id })}>
            {p.label}
          </button>
        ))}
      </div>
      <div className="filterbar-sep" />
      <span className="uppercase dim" style={{ fontFamily: 'var(--mono)' }}>
        обновлено {new Date().toLocaleString('ru-RU', { hour: '2-digit', minute: '2-digit' })}
      </span>
    </div>
  );
}

// ── Tweaks panel ─────────────────────────────
function Tweaks({ theme, setTheme, density, setDensity }) {
  const [open, setOpen] = useState(false);
  const [available, setAvailable] = useState(false);

  useEffect(() => {
    function handler(e) {
      if (e.data?.type === '__activate_edit_mode') setOpen(true);
      if (e.data?.type === '__deactivate_edit_mode') setOpen(false);
    }
    window.addEventListener('message', handler);
    window.parent.postMessage({ type: '__edit_mode_available' }, '*');
    setAvailable(true);
    return () => window.removeEventListener('message', handler);
  }, []);

  function set(key, val) {
    if (key === 'theme') setTheme(val);
    if (key === 'density') setDensity(val);
    window.parent.postMessage({
      type: '__edit_mode_set_keys',
      edits: { [key]: val }
    }, '*');
  }

  return (
    <div className={`tweaks ${open ? 'open' : ''}`}>
      <div className="tweaks-h">
        <span>Tweaks</span>
        <span className="tweaks-close" onClick={() => setOpen(false)}>×</span>
      </div>
      <div className="tweak-row">
        <div className="tweak-label">Тема</div>
        <div className="tweak-seg">
          <button className={theme === 'dark' ? 'active' : ''} onClick={() => set('theme', 'dark')}>Тёмная</button>
          <button className={theme === 'light' ? 'active' : ''} onClick={() => set('theme', 'light')}>Светлая</button>
        </div>
      </div>
      <div className="tweak-row">
        <div className="tweak-label">Плотность</div>
        <div className="tweak-seg">
          <button className={density === 'compact' ? 'active' : ''} onClick={() => set('density', 'compact')}>Плотно</button>
          <button className={density === 'normal' ? 'active' : ''} onClick={() => set('density', 'normal')}>Обычно</button>
        </div>
      </div>
    </div>
  );
}

Object.assign(window, { fmt, Sparkline, KPI, Topbar, FilterBar, Tweaks });
