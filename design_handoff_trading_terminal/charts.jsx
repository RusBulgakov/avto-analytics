// Charts for Auto Analytics KZ

function LineChart({ series, height = 260, color = 'var(--info)', showArea = true, yFormat = v => v, annotations = [] }) {
  const ref = React.useRef(null);
  const [w, setW] = React.useState(600);
  React.useEffect(() => {
    if (!ref.current) return;
    const ro = new ResizeObserver(es => setW(es[0].contentRect.width));
    ro.observe(ref.current);
    return () => ro.disconnect();
  }, []);

  const padL = 50, padR = 14, padT = 14, padB = 28;
  const plotW = Math.max(1, w - padL - padR);
  const plotH = height - padT - padB;

  const flat = series.flatMap(s => s.data.map(d => d.value));
  const min = Math.min(...flat);
  const max = Math.max(...flat);
  const range = max - min || 1;
  const pad = range * 0.1;
  const yMin = min - pad;
  const yMax = max + pad;
  const yRange = yMax - yMin;

  const n = series[0].data.length;
  const sx = i => padL + (i / (n - 1)) * plotW;
  const sy = v => padT + (1 - (v - yMin) / yRange) * plotH;

  // y ticks
  const yTicks = Array.from({length: 5}, (_, i) => yMin + (yRange * i / 4));

  return (
    <div ref={ref} style={{ width: '100%' }}>
      <svg width={w} height={height} style={{ display: 'block' }}>
        {/* y grid */}
        {yTicks.map((t, i) => (
          <g key={i}>
            <line x1={padL} x2={w - padR} y1={sy(t)} y2={sy(t)} stroke="var(--grid-line)" />
            <text x={padL - 8} y={sy(t) + 3} fontSize="10" fontFamily="var(--mono)" fill="var(--text-muted)" textAnchor="end">{yFormat(t)}</text>
          </g>
        ))}
        {/* x labels */}
        {[0, Math.floor(n/4), Math.floor(n/2), Math.floor(3*n/4), n-1].map((i, k) => (
          <text key={k} x={sx(i)} y={height - 8} fontSize="10" fontFamily="var(--mono)" fill="var(--text-muted)" textAnchor="middle">
            {`-${n - 1 - i}д`}
          </text>
        ))}
        {/* Series */}
        {series.map((s, si) => {
          const linePath = s.data.map((d, i) => (i === 0 ? `M${sx(i)},${sy(d.value)}` : `L${sx(i)},${sy(d.value)}`)).join(' ');
          const areaPath = `${linePath} L${sx(n-1)},${padT + plotH} L${sx(0)},${padT + plotH} Z`;
          const c = s.color || color;
          return (
            <g key={si}>
              {showArea && s.area !== false && (
                <path d={areaPath} fill={c} opacity="0.08" />
              )}
              <path d={linePath} fill="none" stroke={c} strokeWidth={s.strokeWidth || 1.8} strokeDasharray={s.dashed ? '4 3' : undefined} />
              {/* last point dot */}
              <circle cx={sx(n-1)} cy={sy(s.data[n-1].value)} r="3" fill={c} />
            </g>
          );
        })}
        {annotations.map((a, i) => (
          <g key={i}>
            <line x1={sx(a.i)} x2={sx(a.i)} y1={padT} y2={padT + plotH} stroke="var(--accent)" strokeDasharray="3 3" opacity="0.6" />
            <text x={sx(a.i)} y={padT - 3} fontSize="9" fontFamily="var(--mono)" fill="var(--accent)" textAnchor="middle">{a.label}</text>
          </g>
        ))}
      </svg>
    </div>
  );
}

// ── Heatmap: Year × Mileage × Price
function Heatmap({ brand = 'Все марки' }) {
  const [mode, setMode] = React.useState('price'); // 'price' | 'volume'
  const [hover, setHover] = React.useState(null);

  const cells = YEARS.map(y => MILEAGE_BUCKETS.map((_, m) => ({
    y, m,
    price: heatmapPrice(y, m),
    volume: heatmapVolume(y, m),
  })));

  const flat = cells.flat();
  const values = flat.map(c => mode === 'price' ? c.price : c.volume);
  const vMin = Math.min(...values);
  const vMax = Math.max(...values);

  function color(v) {
    const t = (v - vMin) / (vMax - vMin || 1);
    // For price: brighter = more expensive (green/yellow scale)
    if (mode === 'price') {
      // interpolate surface-2 → accent → up
      if (t < 0.5) {
        // dark → accent
        const k = t * 2;
        return `color-mix(in oklch, var(--surface-2) ${100 - k*100}%, var(--accent) ${k*100}%)`;
      } else {
        const k = (t - 0.5) * 2;
        return `color-mix(in oklch, var(--accent) ${100 - k*100}%, var(--up) ${k*100}%)`;
      }
    } else {
      // volume: dark → info
      return `color-mix(in oklch, var(--surface-2) ${100 - t*100}%, var(--info) ${t*100}%)`;
    }
  }

  const hm = hover ? cells[hover.r][hover.c] : null;

  return (
    <div>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 12 }}>
        <div style={{ fontSize: 12, color: 'var(--text-muted)' }}>
          {hm ? (
            <span className="mono tnum">
              <strong style={{ color: 'var(--text)' }}>{hm.y}</strong> · пробег <strong style={{ color: 'var(--text)' }}>{MILEAGE_BUCKETS[hm.m]} тыс</strong> · 
              {' '}ср. цена <strong style={{ color: 'var(--up)' }}>{hm.price} млн ₸</strong> · 
              {' '}<span>{hm.volume} объявл.</span>
            </span>
          ) : (
            <span>Наведите на ячейку · цвет = {mode === 'price' ? 'средняя цена' : 'число объявлений'}</span>
          )}
        </div>
        <div className="tweak-seg" style={{ margin: 0 }}>
          <button className={mode === 'price' ? 'active' : ''} onClick={() => setMode('price')}>Цена</button>
          <button className={mode === 'volume' ? 'active' : ''} onClick={() => setMode('volume')}>Объём</button>
        </div>
      </div>
      <div style={{ display: 'grid', gridTemplateColumns: `36px repeat(${MILEAGE_BUCKETS.length}, 1fr)`, gap: 2 }}>
        <div />
        {MILEAGE_BUCKETS.map(b => <div key={b} className="hm-col-label">{b}</div>)}
        {cells.map((row, r) => (
          <React.Fragment key={r}>
            <div className="hm-label">{YEARS[r]}</div>
            {row.map((cell, c) => {
              const v = mode === 'price' ? cell.price : cell.volume;
              return (
                <div key={c} className="hm-cell"
                  style={{ background: color(v) }}
                  onMouseEnter={() => setHover({ r, c })}
                  onMouseLeave={() => setHover(null)}>
                  {mode === 'price' ? cell.price.toFixed(1) : cell.volume}
                </div>
              );
            })}
          </React.Fragment>
        ))}
      </div>
      <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginTop: 14, fontSize: 10.5, fontFamily: 'var(--mono)', color: 'var(--text-muted)' }}>
        <span>НИЖЕ</span>
        <div style={{
          flex: 1, height: 6, borderRadius: 3,
          background: mode === 'price'
            ? 'linear-gradient(to right, var(--surface-2), var(--accent), var(--up))'
            : 'linear-gradient(to right, var(--surface-2), var(--info))'
        }} />
        <span>ВЫШЕ</span>
        <span style={{ marginLeft: 12 }}>X: ПРОБЕГ (тыс км) · Y: ГОД</span>
      </div>
    </div>
  );
}

// ── KZ Map ──────────────────────────────
function KZMap() {
  const [hover, setHover] = React.useState(null);
  const maxL = Math.max(...CITIES.map(c => c.listings));

  return (
    <div>
      <div className="map-wrap">
        <svg className="map-svg" viewBox="0 0 100 50" preserveAspectRatio="none">
          {/* Simplified KZ silhouette */}
          <path className="map-region" d="
            M 5,22 L 9,18 L 14,16 L 18,13 L 24,11 L 30,9 L 38,8 L 46,7 L 54,7 L 62,8 L 68,10 L 74,12 L 80,14 L 86,17 L 90,20 L 93,24 L 95,28 L 94,32 L 92,35 L 88,37 L 84,39 L 80,41 L 74,42 L 68,43 L 62,44 L 56,44 L 50,45 L 44,45 L 38,44 L 32,43 L 26,42 L 20,41 L 14,39 L 10,37 L 7,34 L 5,30 L 4,26 Z
          " />
          {/* Caspian notch */}
          <path fill="var(--bg-2)" d="M 0,28 L 8,26 L 12,32 L 10,40 L 5,44 L 0,44 Z" />
          {/* Balkhash lake hint */}
          <ellipse cx="68" cy="34" rx="8" ry="2" fill="var(--bg)" opacity="0.6" />
        </svg>

        {CITIES.map((c, i) => {
          const size = 6 + (c.listings / maxL) * 22;
          const isHover = hover === i;
          return (
            <div key={c.name} className="city-pin"
              style={{ left: `${c.x}%`, top: `${c.y}%` }}
              onMouseEnter={() => setHover(i)}
              onMouseLeave={() => setHover(null)}>
              <div className="city-dot" style={{ width: size, height: size, opacity: isHover ? 1 : 0.85 }} />
              {(isHover || c.listings > 30000) && (
                <>
                  <div className="city-label">{c.name}</div>
                  {isHover && <div className="city-price mono">{(c.avg/1_000_000).toFixed(1)} млн ₸</div>}
                </>
              )}
            </div>
          );
        })}
      </div>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginTop: 10, fontSize: 11, fontFamily: 'var(--mono)', color: 'var(--text-muted)' }}>
        <span>● РАЗМЕР = ОБЪЁМ РЫНКА</span>
        <span>{hover != null ? CITIES[hover].listings.toLocaleString('ru-RU') + ' активных объявлений' : `${CITIES.length} городов · ${CITIES.reduce((s,c)=>s+c.listings,0).toLocaleString('ru-RU')} объявл.`}</span>
      </div>
    </div>
  );
}

// ── Funnel ──────────────────────────────
function Funnel() {
  const max = Math.max(...FUNNEL.map(f => f.count));
  const total = FUNNEL.reduce((s, f) => s + f.count, 0);
  return (
    <div>
      {FUNNEL.map((f, i) => {
        const w = (f.count / max) * 100;
        const pct = (f.count / total) * 100;
        return (
          <div key={i} className="funnel-row">
            <div className="funnel-label mono">{f.label}</div>
            <div className="funnel-bar-wrap">
              <div className="funnel-bar" style={{ width: `${w}%`, background: f.color }} />
            </div>
            <div className="funnel-count tnum">{f.count.toLocaleString('ru-RU')}</div>
            <div className="funnel-pct">{pct.toFixed(1)}%</div>
          </div>
        );
      })}
      <div style={{ display: 'flex', justifyContent: 'space-between', marginTop: 12, fontSize: 11, color: 'var(--text-muted)' }}>
        <span>Медиана времени продажи: <span className="mono" style={{ color: 'var(--text)' }}>18 дней</span></span>
        <span>50% уходят за <span className="mono up">≤ 14 дней</span></span>
      </div>
    </div>
  );
}

Object.assign(window, { LineChart, Heatmap, KZMap, Funnel });
