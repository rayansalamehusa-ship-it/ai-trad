'use strict';
/* ================= أساسيات ================= */
const $ = s => document.querySelector(s), $$ = s => [...document.querySelectorAll(s)];
const api = (u, b) => fetch(u, b ? {method: 'POST', headers: {'Content-Type': 'application/json', 'X-App': '1'}, body: JSON.stringify(b)} : {}).then(r => r.json());
const esc = s => String(s ?? '').replace(/[&<>"]/g, c => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;'}[c]));
const N = v => `<span class="num">${esc(v)}</span>`;
const fp = v => v == null ? '' : (Math.abs(v) >= 100 ? Number(v).toFixed(2) : Math.abs(v) >= 1 ? Number(v).toFixed(4) : Number(v).toPrecision(4));
const NAMES = {price: 'مراقب الأسعار', news: 'محلل الأخبار', context: 'فاهم السياق', strategist: 'باحث الاستراتيجيات', hunter: 'صياد الفرص', simulator: 'مهندس المحاكاة', risk: 'مدير المخاطر', ceo: 'المدير التنفيذي'};
const PHASES = [{name: 'فهم السياق', keys: ['price', 'news', 'context']}, {name: 'البحث عن الصفقة', keys: ['strategist', 'hunter', 'simulator']}, {name: 'القرار', keys: ['risk', 'ceo']}];
const STYLE_NOTE = {swing: 'يقرأ السياق على 1 يوم / 4 س / 1 س ويدخل على 4 س — صفقات تدوم ساعات إلى أيام.', scalp: 'يقرأ السياق على 1 س / 15 د / 5 د ويدخل على 15 د — صفقات قصيرة؛ السبريد والتنفيذ حاسمان.'};
const QUICK = ['BTC/USDT', 'ETH/USDT', 'XAU/USD', 'EUR/USD', 'USD/JPY', 'GBP/USD'];
let mode = 'local', style = 'swing', STEPS = [], timer = null, scanTimer = null, opened = new Set(), lastAlert = 0;
let JOB = null, R = null, CHTF = null, shownCtx = false, deepHtml = '', ofHtml = '';

/* ================= التنقل ================= */
function goTab(p) {
  $$('#nav button').forEach(b => b.classList.toggle('on', b.dataset.p === p));
  $$('.page').forEach(s => s.classList.toggle('on', s.id === 'p-' + p));
  window.scrollTo(0, 0);
  if (p === 'acct') loadPaper();
  if (p === 'lab') loadLab();
  if (p === 'set') loadStatus();
}
$$('#nav button').forEach(b => b.onclick = () => goTab(b.dataset.p));
function bindTabs(bar, ids, onShow) {
  $$(bar + ' button').forEach(b => b.onclick = () => {
    $$(bar + ' button').forEach(x => x.classList.toggle('on', x === b));
    ids.forEach(i => $('#t-' + i).hidden = i !== b.dataset.t);
    onShow && onShow(b.dataset.t);
  });
}
bindTabs('#acctTabs', ['paper', 'mt5', 'hist'], t => t === 'paper' ? loadPaper() : t === 'mt5' ? loadMt5() : loadHist());
bindTabs('#labTabs', ['brain', 'strat'], () => {});
document.addEventListener('click', e => {                       // صفوف قابلة للطي
  const li = e.target.closest('.li.tap');
  if (li && !e.target.closest('button')) li.classList.toggle('open');
});

/* ================= أدوات التحكم ================= */
function setStyle(s) {
  style = s;
  $$('#styleSeg button,#radarSeg button').forEach(x => x.classList.toggle('on', x.dataset.s === s));
  $('#styleNote').textContent = STYLE_NOTE[s];
}
$$('#styleSeg button,#radarSeg button').forEach(b => b.onclick = () => setStyle(b.dataset.s));
setStyle('swing');
$$('#modeSeg button').forEach(b => b.onclick = () => {
  mode = b.dataset.m;
  $$('#modeSeg button').forEach(x => x.classList.toggle('on', x === b));
});
function buildQuick(groups) {
  $('#quick').innerHTML = QUICK.map(q => `<button data-q="${q}">${q}</button>`).join('') +
    `<select id="pick" aria-label="أصول أخرى"><option value="">أصول أخرى…</option>${groups.map(g => `<optgroup label="${esc(g.label)}">${g.items.map(i => `<option value="${i.symbol}">${esc(i.name)} — ${i.symbol}</option>`).join('')}</optgroup>`).join('')}</select>`;
  $$('#quick button').forEach(b => b.onclick = () => pickSym(b.dataset.q));
  $('#pick').onchange = e => { if (e.target.value) pickSym(e.target.value); e.target.value = ''; };
}
function pickSym(s) {
  $('#symbol').value = s;
  $$('#quick button').forEach(b => b.classList.toggle('on', b.dataset.q === s));
}
$('#symbol').addEventListener('input', () => $$('#quick button').forEach(b => b.classList.toggle('on', b.dataset.q === $('#symbol').value.toUpperCase())));
$('#symbol').addEventListener('keydown', e => { if (e.key === 'Enter') $('#go').click(); });

/* ================= رسم الشارت ================= */
function chart(ch, p, lv) {
  if (!ch || !ch.c.length) return '<div class="hint">لا بيانات للرسم</div>';
  const c = ch.c, W = 760, H = 330, pr = 78, pt = 10, pb = 12, cw = W - pr;
  let hi = Math.max(...c.map(x => x[1])), lo = Math.min(...c.map(x => x[2]));
  if (p) { const l = [p.take_profit2, p.take_profit, p.stop_loss, p.entry]; hi = Math.max(hi, ...l); lo = Math.min(lo, ...l); }
  const pad = (hi - lo) * .05 || 1; hi += pad; lo -= pad;
  const y = v => pt + (hi - v) / (hi - lo) * (H - pt - pb), bw = cw / c.length, X = i => i * bw + bw / 2;
  let s = '';
  for (let i = 0; i <= 4; i++) {
    const v = lo + (hi - lo) * i / 4;
    s += `<line x1="0" x2="${cw}" y1="${y(v)}" y2="${y(v)}" stroke="var(--line)"/><text x="${W - 6}" y="${y(v) + 4}" font-size="11" fill="var(--faint)" text-anchor="end">${fp(v)}</text>`;
  }
  if (p) {
    const e = y(p.entry), t = y(p.take_profit), sl = y(p.stop_loss);
    s += `<rect x="0" width="${cw}" y="${Math.min(e, t)}" height="${Math.abs(e - t)}" fill="var(--buy)" opacity=".10"/><rect x="0" width="${cw}" y="${Math.min(e, sl)}" height="${Math.abs(e - sl)}" fill="var(--sell)" opacity=".10"/>`;
  }
  if (lv) [['resistance', 'مقاومة'], ['support', 'دعم']].forEach(([k, t]) => {
    const v = lv[k]; if (v && v < hi && v > lo) s += `<line x1="0" x2="${cw}" y1="${y(v)}" y2="${y(v)}" stroke="var(--faint)" stroke-dasharray="2 5"/><text x="6" y="${y(v) - 4}" font-size="11" fill="var(--faint)">${t} ${fp(v)}</text>`;
  });
  s += c.map((x, i) => {
    const [o, h, l, cl] = x, col = cl >= o ? 'var(--buy)' : 'var(--sell)';
    return `<line x1="${X(i)}" x2="${X(i)}" y1="${y(h)}" y2="${y(l)}" stroke="${col}"/><rect x="${X(i) - bw * .34}" y="${y(Math.max(o, cl))}" width="${bw * .68}" height="${Math.max(1, Math.abs(y(o) - y(cl)))}" fill="${col}"/>`;
  }).join('');
  const line = (a, col) => `<polyline fill="none" stroke="${col}" stroke-width="1.4" opacity=".9" points="${a.map((v, i) => X(i) + ',' + y(v)).join(' ')}"/>`;
  s += line(ch.e20, 'var(--brass)') + line(ch.e50, 'var(--blue)');
  if (p) [['take_profit2', 'var(--buy)', 'TP2'], ['take_profit', 'var(--buy)', 'TP1'], ['entry', 'var(--text)', 'دخول'], ['stop_loss', 'var(--sell)', 'SL']].forEach(([k, col, t]) => {
    if (!p[k]) return;
    s += `<line x1="0" x2="${cw}" y1="${y(p[k])}" y2="${y(p[k])}" stroke="${col}" stroke-width="1.3" stroke-dasharray="6 4"/><rect x="${cw + 2}" y="${y(p[k]) - 9}" width="${pr - 4}" height="18" rx="4" fill="${col}"/><text x="${cw + 2 + (pr - 4) / 2}" y="${y(p[k]) + 4}" font-size="11" font-weight="700" fill="var(--bg)" text-anchor="middle">${t}</text>`;
  });
  return `<svg viewBox="0 0 ${W} ${H}" style="direction:ltr" role="img" aria-label="شارت الشموع">${s}</svg>`;
}
function drawChart() {
  const box = $('#chartBox'); if (!box || !R) return;
  const tfs = Object.keys(R.charts);
  box.innerHTML = `<div class="seg sm" style="margin-bottom:8px">${tfs.map(t => `<button data-tf="${t}" class="${t === CHTF ? 'on' : ''}">${t}${t === R.entry_tf ? ' (الدخول)' : ''}</button>`).join('')}</div>${chart(R.charts[CHTF], R.plan, R.context && R.context.levels)}
   <div class="cap"><span><b style="background:var(--brass)"></b>EMA 20</span><span><b style="background:var(--blue)"></b>EMA 50</span><span>آخر ${R.charts[CHTF].c.length} شمعة على ${CHTF}</span></div>`;
  box.querySelectorAll('.seg button').forEach(b => b.onclick = () => { CHTF = b.dataset.tf; drawChart(); });
}

/* ================= المرحلة 1: السياق ================= */
const GATE = {
  long: '<div class="s">بيع</div><div class="b on">شراء</div>', short: '<div class="s on">بيع</div><div class="b">شراء</div>',
  selective: '<div class="s half">بيع</div><div class="b half">شراء</div>', wait: '<div class="s">بيع</div><div class="b">شراء</div>'};
const ARROW = {up: ['▲', 'up', 'صاعد'], down: ['▼', 'down', 'هابط'], flat: ['◆', 'mut', 'جانبي']};
function ctxPanel(c, r) {
  const d = c.direction_score, pos = (d + 100) / 2, left = d >= 0 ? 50 : pos, w = Math.abs(d) / 2;
  const head = r
    ? `<b>${esc(r.symbol)}</b><span class="pr">${N(r.price)}</span><span class="${r.change >= 0 ? 'up' : 'down'}">${N((r.change > 0 ? '+' : '') + r.change + '%')}</span>`
    : `<b>${esc($('#symbol').value.toUpperCase())}</b><span class="mut">جارٍ إكمال التحليل…</span>`;
  const frames = c.frames.map(f => {
    const [a, cl, t] = ARROW[f.trend];
    return `<div class="fr"><span class="tf">${f.tf}</span><span class="ar ${cl}">${a}</span><div>${t}${f.regime ? ' · ' + esc(f.regime) : ''}<small>ADX ${f.adx} · RSI ${f.rsi}</small></div></div>`;
  }).join('');
  const lock = c.permission === 'wait' ? ' 🔒' : '';
  return `<div class="stage-h">المرحلة 1 — فهم السياق</div>
  <div class="panel"><div class="ctxbox">
   <div>
    <div class="sym">${head}<span class="pill brass">${esc(c.state_label)}</span></div>
    <div class="bias-word ${c.bias}">${esc(c.bias_label)}</div>
    <p class="bias-cap">قوة الاتجاه ${N(c.strength + ' / 100')} · الفريمات ${c.aligned ? 'متوافقة' : 'غير متوافقة'}</p>
    <div class="meter"><i style="left:${left}%;width:${w}%;background:${d >= 0 ? 'var(--buy)' : 'var(--sell)'}"></i><span class="mid"></span><span class="pin" style="left:${pos}%"></span></div>
    <div class="mlab"><span>بيع</span><span>محايد</span><span>شراء</span></div>
    <p class="headline">${esc(c.headline)}</p>
   </div>
   <div class="gatebox">
    <p class="cap">ما المسموح البحث عنه في الخطوة التالية</p>
    <div class="gate">${GATE[c.permission]}</div>
    <p class="perm">${esc(c.permission_label)}${lock}</p>
    <p class="risk">${c.permission === 'wait' ? 'لن يبحث الفريق عن صفقات ولن يختبر استراتيجيات.' : c.risk_factor < 1 ? 'المخاطرة مخفضة 50% لأن السياق ليس قوياً أو متوافقاً بما يكفي.' : 'المخاطرة عادية.'}</p>
   </div>
   <div class="frames">${frames}</div>
   <div class="ctx-more">
    <details><summary>الأدلة وراء هذا الحكم (${c.notes.length})</summary><ul class="ev">${c.notes.map(n => `<li>${esc(n)}</li>`).join('')}</ul></details>
    <details><summary>أدوات متقدمة للسياق</summary>
     <div class="acts" style="margin-top:6px"><button class="btn sm" id="deepGo">تحليل تفصيلي 1س / 15د / 5د</button><button class="btn sm" id="ofGo">تدفق الأوامر والسيولة</button></div>
     <div id="deepOut">${deepHtml}</div><div id="ofOut">${ofHtml}</div>
    </details>
   </div>
  </div></div>`;
}
function bindCtx() {
  const g = $('#deepGo'); if (g) g.onclick = deepCtx;
  const o = $('#ofGo'); if (o) o.onclick = orderFlow;
}
async function deepCtx() {
  const b = $('#deepGo'); b.disabled = true; $('#deepOut').innerHTML = '<p class="hint">جارٍ التحليل…</p>';
  try {
    const d = await api('/api/intelligence', {symbol: (R && R.symbol) || $('#symbol').value});
    if (d.error) deepHtml = `<div class="err">${esc(d.error)}</div>`;
    else {
      const bl = {bullish: 'صاعد', bearish: 'هابط', neutral: 'محايد'};
      deepHtml = `<div class="lst">${Object.entries(d.frames).map(([tf, x]) => `<div class="li"><div class="t"><b class="num">${tf}</b> · ${esc(x.regime_label)} · ADX ${x.adx}<small>${bl[x.bias] || ''} — ميل صاعد ${x.bull_bias_score}% / هابط ${x.bear_bias_score}%
سيولة: ${x.liquidity.sweep_low ? 'سحب قاع' : x.liquidity.sweep_high ? 'سحب قمة' : 'لا سحب'} · هيكل: ${x.structure.bos_up ? 'BOS صاعد' : x.structure.bos_down ? 'BOS هابط' : 'لا كسر'} · FVG: ${x.fvg.bullish ? 'صاعدة' : x.fvg.bearish ? 'هابطة' : 'لا'}</small></div></div>`).join('')}</div><p class="hint">${esc(d.disclaimer || '')}</p>`;
    }
  } catch (e) { deepHtml = '<div class="err">تعذر الاتصال بالتطبيق</div>'; }
  $('#deepOut').innerHTML = deepHtml; b.disabled = false;
}
async function orderFlow() {
  const b = $('#ofGo'); b.disabled = true; $('#ofOut').innerHTML = '<p class="hint">جارٍ جلب الصفقات ودفتر الأوامر…</p>';
  const r = await api('/api/orderflow', {symbol: (R && R.symbol) || $('#symbol').value});
  if (!r.available) ofHtml = `<div class="card2 mini">${esc(r.error || r.reason || 'البيانات غير متاحة')}</div>`;
  else {
    const n = v => v == null ? 'غير متاح' : Number(v).toLocaleString('en-US', {maximumFractionDigits: 4});
    ofHtml = `<div class="card2"><b>تدفق الصفقات — ${esc(r.venue)}</b><div class="mini">
     CVD صافي ${N(n(r.cvd_notional))} · انحياز ${N(n(r.cvd_ratio * 100) + '%')} · ${N(n(r.trade_count))} صفقة بالعينة<br>
     شراء منفذ ${N(n(r.buy_notional))} · بيع منفذ ${N(n(r.sell_notional))}<br>
     عمق الشراء ${N(n(r.bid_depth_notional))} · عمق البيع ${N(n(r.ask_depth_notional))} · اختلال ${N(n(r.book_imbalance * 100) + '%')} · سبريد ${N(n(r.spread_bps))} نقطة أساس<br>
     Funding ${N(n(r.funding_rate))} · Open Interest ${N(n(r.open_interest))}<br>
     ${r.liquidations ? `تصفيات ${N(n(r.liquidations.count))} بقيمة ${N(n(r.liquidations.notional))}` : 'بيانات التصفية غير متاحة من هذه المنصة'}<br>
     الامتصاص المحتمل: ${r.absorption_possible === null ? 'غير كافٍ' : r.absorption_possible ? 'اشتباه امتصاص — تحقق من السياق' : 'لم يُرصد'}<br>
     <small>${(r.warnings || []).map(esc).join(' · ')}</small></div></div>`;
  }
  $('#ofOut').innerHTML = ofHtml; b.disabled = false;
}

/* ================= المرحلة 2: الصفقة ================= */
function gaugeHtml(r) {
  const h = r.side_hist || {BUY: {n: 0}, SELL: {n: 0}}, f = x => x.n ? `${x.win_rate}% من ${x.n} صفقة` : 'لا بيانات';
  return `<div class="gauge"><div class="bar"><i class="gs" style="width:${r.sell_pct}%"></i><i class="gb" style="width:${r.buy_pct}%"></i></div>
   <div class="gl"><span class="down">بيع ${N(r.sell_pct + '%')}</span><span class="up">شراء ${N(r.buy_pct + '%')}</span></div>
   <div class="mini" style="margin-top:6px">نجاح تاريخي حديث للاستراتيجيات الناجحة — شراء: ${f(h.BUY)} · بيع: ${f(h.SELL)}${r.plan && r.plan.win_rate_est != null ? `<br><b>النجاح المقدّر لهذه الصفقة ${r.plan.win_rate_est}%</b> (مُقلَّص نحو الحياد لصغر العينة، وليس ضماناً)` : ''}</div></div>`;
}
function tradeHtml(r) {
  const c = r.context, p = r.plan;
  if (r.stand_aside) return `<div class="stage-h">المرحلة 2 — الصفقة</div><div class="panel"><h2>لم يُبحث عن صفقات</h2>
   <p class="sub" style="margin:0">${esc(c.headline)}</p><p class="hint" style="margin-top:8px">لم تُختبر أي استراتيجية لأن السياق لا يسمح بالدخول. أعد التحليل لاحقاً أو جرّب أصلاً آخر.</p></div>`;
  let side;
  if (p) {
    const b = p.action === 'BUY';
    side = `<div class="verd ${b ? 'buy' : 'sell'}">${b ? 'شراء BUY' : 'بيع SELL'}</div>
     <div class="vsub">${esc(r.grade_label)} · الدرجة ${r.grade} (${r.setup_score}/100) · ${esc(r.mode_label)}</div>
     <div class="plan"><div><span>دخول سوقي فوري</span><strong>${N(p.entry)}</strong></div><div class="sl"><span>وقف الخسارة</span><strong>${N(p.stop_loss)}</strong></div>
      <div class="tp"><span>الهدف 1 (1:${p.rr})</span><strong>${N(p.take_profit)}</strong></div><div class="tp"><span>الهدف 2</span><strong>${N(p.take_profit2)}</strong></div>
      <div><span>حجم الصفقة</span><strong>${N('$' + p.size_usd)}</strong></div><div><span>أقصى خسارة (${p.risk_pct}%)</span><strong>${N('$' + p.risk_usd)}</strong></div></div>
     ${p.leverage > 1 ? `<p class="hint" style="margin-top:8px">الحجم يتطلب رافعة ≈ ${p.leverage}× (فوركس / ذهب / بيع على المكشوف).</p>` : ''}
     ${r.context.risk_factor < 1 ? '<p class="hint" style="margin-top:6px">المخاطرة مخفضة 50% بسبب ضعف السياق.</p>' : ''}`;
  } else if (r.blocked_by_context) {
    side = `<div class="verd wait">ممنوعة بالسياق</div><div class="blockmsg">${esc(r.blocked_by_context)}</div>`;
  } else {
    side = `<div class="verd wait">انتظار</div><div class="vsub">لا توجد فرصة واضحة داخل ما يسمح به السياق.</div>`;
  }
  const strat = (r.strategies || []).length ? `<details style="margin-top:14px"><summary>الاستراتيجيات المختبرة (${r.strategies.length}) — على ${r.bars} شمعة ${r.entry_tf}</summary><div class="lst">${r.strategies.map(s =>
    `<div class="li"><div class="t">${esc(s.name)}<small>${s.signal === 'BUY' ? 'شراء الآن · ' : s.signal === 'SELL' ? 'بيع الآن · ' : ''}${s.origin === 'builtin' ? '' : 'مولّدة · '}صفقات ${s.stats.n} · نجاح ${s.stats.win_rate}% · ${s.stats.avg_r}R · PF ${s.stats.pf}</small></div><span class="pill ${s.passed ? 'buy' : ''}">${s.passed ? 'اجتازت' : 'لم تجتز'}</span></div>`).join('')}</div>
   <p class="hint" style="margin-top:6px">الاختبار يشمل الاتجاهين بوقف وهدف بالـATR وتكلفة تنفيذ؛ قلة الصفقات تعني أن النتائج تقديرية.</p></details>` : '';
  const tfs = (r.tfs || []).length ? `<details><summary>الفريمات المختبرة</summary><div class="lst">${r.tfs.map(t => `<div class="li"><div class="t"><b class="num">${t.tf}</b> — ${esc(t.trend_label)} · RSI ${t.rsi} · ${esc(t.regime)}<small>شراء ${t.buy} · بيع ${t.sell}${t.active.length ? ' — ' + t.active.map(a => (a.signal === 'BUY' ? 'شراء: ' : 'بيع: ') + esc(a.name)).join('، ') : ''}</small></div></div>`).join('')}</div></details>` : '';
  return `<div class="stage-h">المرحلة 2 — الصفقة داخل المسموح</div><div class="panel"><div class="tradebox"><div class="chartbox" id="chartBox"></div><div>${side}${gaugeHtml(r)}</div></div>${strat}${tfs}</div>`;
}

/* ================= المرحلة 3: القرار ================= */
function mmCard(mm) {
  if (!mm || !mm.available) return '';
  const ml = mm.ml || {}, f = (v, d = 2) => v == null ? 'غير متاح' : Number(v).toFixed(d);
  const st = {bullish: 'صاعدة', bearish: 'هابطة', mixed: 'مختلطة'}, rg = {trending: 'اتجاهي', ranging: 'عرضي', transition: 'انتقالي'};
  return `<div class="card2"><b>خوارزميات فهم السوق</b><div class="mini">الحالة: ${rg[mm.regime] || mm.regime} · البنية: ${st[mm.structure] || mm.structure} · جودة السياق ${mm.quality_score}/100<br>
   CHOP ${f(mm.choppiness)} · ER ${f(mm.efficiency_ratio, 3)} · ATR ${mm.volatility} (${f(mm.atr_percentile, 1)} percentile) · انحراف VWAP ${f(mm.vwap_gap_pct, 3)}% · ضغط حجم تقريبي ${f(mm.flow_imbalance_proxy, 3)}<br>
   ${ml.available ? `نموذج ML تجريبي: ميل صاعد ${f(ml.prob_up_experimental * 100, 1)}% خلال ${ml.horizon_bars} شموع · خارج العينة ${f(ml.oos_accuracy, 1)}% على ${ml.oos_samples} عينة · ${ml.beats_baseline ? 'أفضل من baseline' : 'لم يتفوق على baseline'}` : 'نموذج ML: بيانات غير كافية'}
   <br><small>ضغط الحجم تقدير من OHLCV وليس CVD حقيقياً، ونموذج ML تجريبي وليس احتمال ربح معايراً.</small></div></div>`;
}
function grokCard(r) {
  const g = r.grok; if (!g || (!g.pulse && !g.review)) return '';
  const SM = {'-2': 'سلبي جداً', '-1': 'سلبي', '0': 'محايد', '1': 'إيجابي', '2': 'إيجابي جداً'}, VR = {agree: ['يوافق', 'up'], caution: ['يوصي بالحذر', 'mut'], disagree: ['يعارض', 'down']};
  let h = '<div class="card2"><b>Grok — منصة X</b>';
  if (g.pulse && g.pulse.sentiment !== undefined) h += `<div class="mini"><b style="display:inline">المزاج: ${SM[g.pulse.sentiment]}</b> (ثقة ${g.pulse.confidence})<br>${esc(g.pulse.summary)}${g.pulse.posts.map(p => `<br>• ${esc(p.handle)}: ${esc(p.gist)}`).join('')}${g.pulse.risks.map(x => `<br>تنبيه: ${esc(x)}`).join('')}</div>`;
  else if (g.pulse && g.pulse.error) h += `<div class="mini">تعذر جلب نبض X: ${esc(g.pulse.error)}</div>`;
  if (g.review && g.review.verdict) { const [t, c] = VR[g.review.verdict]; h += `<div class="mini"><b class="${c}" style="display:inline">رأي Grok المستقل: ${t}</b>${g.review.points.map(x => `<br>• ${esc(x)}`).join('')}<br><i>استشاري — لا يغيّر الأرقام.</i></div>`; }
  return h + '</div>';
}
function decisionHtml(r) {
  const D = {APPROVED: ['ok', 'موافق عليها'], REJECTED: ['no', 'مرفوضة'], UNKNOWN: ['un', 'قرار غير واضح']}[r.decision] || ['un', r.decision];
  const p = r.plan, first = (r.report || '').split('\n')[0];
  const mt = r.mt5_execution ? `<div class="card2"><b>MetaTrader 5 Demo</b><div class="mini">${r.mt5_execution.ok
    ? `<span class="up">تم إرسال أمر Demo</span><br>${esc(r.mt5_execution.symbol)} · ${r.mt5_execution.side} · حجم ${r.mt5_execution.volume} · السعر ${r.mt5_execution.requested_price} · SL ${r.mt5_execution.stop_loss} · TP ${r.mt5_execution.take_profit}<br>المخاطرة المقدرة ${r.mt5_execution.risk_cash_estimate} ${esc(r.mt5_execution.message || '')}`
    : esc(r.mt5_execution.error || r.mt5_execution.reason || 'لم يتم تنفيذ أمر Demo')}</div></div>` : '';
  return `<div class="stage-h">المرحلة 3 — القرار</div><div class="panel">
   <div class="decide"><span class="dbadge ${D[0]}">${D[1]}</span><div class="dtxt">${esc(first)}</div></div>
   ${p ? `<div class="acts"><button class="btn main-a" id="tgSend">أرسل الصفقة إلى Telegram</button><button class="btn" id="paperFromPlan">افتح مركزاً تجريبياً بهذه الخطة</button><span class="hint" id="actMsg"></span></div>` : ''}
   ${mt}
   <details style="margin-top:12px"><summary>التقرير الكامل ولماذا</summary><div class="pre">${esc(r.report)}</div></details>
   ${mmCard(r.market_model) || grokCard(r) ? `<details><summary>معلومات إضافية (خوارزميات السوق وGrok)</summary>${mmCard(r.market_model)}${grokCard(r)}</details>` : ''}
  </div>`;
}
async function sendTg() {
  $('#actMsg').textContent = 'جارٍ الإرسال…';
  const r = await api('/api/telegram/send', {job: JOB});
  $('#actMsg').textContent = r.ok ? 'وصلت الصفقة إلى Telegram' : 'فشل الإرسال: ' + (r.error || '');
}
async function paperFromPlan() {
  const p = R.plan; $('#actMsg').textContent = 'جارٍ الفتح…';
  const r = await api('/api/paper/open', {symbol: R.symbol, side: p.action === 'BUY' ? 'LONG' : 'SHORT', entry: p.entry, stop: p.stop_loss, target: p.take_profit, risk_pct: 0.5});
  $('#actMsg').textContent = r.error || 'فُتح مركز تجريبي بمخاطرة 0.5% — تجده في «الحساب».';
}

/* ================= تشغيل التحليل ================= */
function renderFlow(j) {
  const st = k => (j.steps[k] || {}).state || 'wait';
  $('#flow').hidden = false;
  $('#flow').innerHTML = PHASES.map((ph, i) => {
    const s = ph.keys.map(st); let cls = '', sub = 'بانتظار';
    if (s.every(x => x === 'skipped')) { cls = 'skip'; sub = 'تم التخطي'; }
    else if (s.every(x => x === 'done' || x === 'skipped')) { cls = 'done'; sub = 'اكتملت'; }
    else if (s.some(x => x === 'running')) { cls = 'run'; sub = 'يعمل: ' + NAMES[ph.keys[s.indexOf('running')]]; }
    else if (s.some(x => x === 'done')) { cls = 'run'; sub = 'جارٍ…'; }
    return `<div class="ph3 ${cls}"><span class="dot"><span>${cls === 'done' ? '✓' : i + 1}</span></span><div class="t">${ph.name}<small>${sub}</small></div></div>`;
  }).join('');
}
function renderSteps(j) {
  $('#teamBox').hidden = false;
  $('#steps').innerHTML = STEPS.map(s => {
    const st = j.steps[s.key] || {state: 'wait', text: ''}, tap = st.state === 'done' || st.state === 'skipped';
    const mark = st.state === 'running' ? 'جارٍ…' : st.state === 'done' ? '<span class="up">✓</span>' : st.state === 'skipped' ? 'تم التخطي' : '';
    return `<div class="li ${tap ? 'tap' : ''} ${opened.has(s.key) ? 'open' : ''}" data-k="${s.key}"><div class="t">${s.name}<small>${s.en}</small></div><span class="mut">${mark}</span></div><div class="li-out">${esc(st.text)}</div>`;
  }).join('');
  $$('#steps .li.tap').forEach(el => el.addEventListener('click', () => setTimeout(() => { el.classList.contains('open') ? opened.add(el.dataset.k) : opened.delete(el.dataset.k); }, 0)));
}
function fail(m) {
  clearInterval(timer); reset();
  const dep = /No module named|pip install|yfinance|ccxt/i.test(m);
  $('#err').innerHTML = `<div class="err">${esc(m)}${dep ? '<button class="btn sm main-a" id="fixDeps">ثبّت المكتبة الناقصة تلقائياً</button>' : ''}</div>`;
  const b = $('#fixDeps'); if (b) b.onclick = async () => { b.disabled = true; b.textContent = 'جارٍ التثبيت…'; const r = await api('/api/deps/install', {}); $('#err').innerHTML = r.ok ? '<div class="note">تم التثبيت. اضغط «ابدأ التحليل» من جديد.</div>' : `<div class="err">تعذر التثبيت التلقائي. نفّذ في الطرفية:<br><span class="num">${esc(r.fix || r.error)}</span></div>`; checkDeps(); };
}
function reset() { $('#go').disabled = false; $('#go').textContent = 'ابدأ التحليل'; }
$('#go').onclick = async () => {
  clearInterval(timer); opened.clear(); shownCtx = false; deepHtml = ofHtml = ''; R = null;
  ['#err', '#stage1', '#stage2', '#stage3'].forEach(s => $(s).innerHTML = '');
  $('#deskEmpty').hidden = true; $('#go').disabled = true; $('#go').textContent = 'الفريق يعمل…';
  const r = await api('/api/run', {symbol: $('#symbol').value, capital: $('#capital').value, mode, style});
  if (r.error) { fail(r.error); return; }
  JOB = r.id; let busy = false;
  timer = setInterval(async () => {
    if (busy) return; busy = true;
    try {
      const j = await api('/api/job/' + r.id);
      renderFlow(j); renderSteps(j);
      if (j.context && !shownCtx) { shownCtx = true; $('#stage1').innerHTML = ctxPanel(j.context, null); bindCtx(); }   // السياق يظهر فور اكتماله
      if (j.status === 'done') {
        clearInterval(timer); reset(); R = j.result; CHTF = R.entry_tf || Object.keys(R.charts)[0];
        $('#stage1').innerHTML = ctxPanel(R.context, R); $('#stage2').innerHTML = tradeHtml(R); $('#stage3').innerHTML = decisionHtml(R);
        bindCtx(); drawChart();
        const t = $('#tgSend'); if (t) t.onclick = sendTg;
        const pp = $('#paperFromPlan'); if (pp) pp.onclick = paperFromPlan;
      }
      if (j.status === 'error') fail(j.error);
    } catch (e) { /* يعاد المحاولة في الدورة التالية */ }
    busy = false;
  }, 700);
};

/* ================= الرادار ================= */
function radRow(x) {
  const c = x.ctx, p = x.plan, ac = x.action === 'BUY' ? ['شراء', 'buy'] : x.action === 'SELL' ? ['بيع', 'sell'] : ['انتظار', ''];
  const bc = c.bias === 'bullish' ? 'buy' : c.bias === 'bearish' ? 'sell' : '';
  return `<div class="rad" data-sym="${esc(x.symbol)}">
   <div class="s"><b>${esc(x.symbol)}</b><small>${N(x.price)} · <span class="${x.change >= 0 ? 'up' : 'down'}">${N((x.change > 0 ? '+' : '') + x.change + '%')}</span></small></div>
   <div><span class="pill ${bc}">${esc(c.bias_label)} · ${esc(c.state_label)}</span><small>${esc(c.permission_label)}</small></div>
   <div><div class="mb"><i style="width:${x.buy_pct}%"></i></div><small style="margin-top:3px">شراء ${x.buy_pct}% · بيع ${x.sell_pct}%</small></div>
   <div style="text-align:end"><span class="pill ${ac[1]}">${x.decision === 'APPROVED' ? '✓ ' : ''}${ac[0]}${p ? ' · ' + x.grade : ''}</span>${p ? `<small>دخول ${N(p.entry)} · وقف ${N(p.stop_loss)} · هدف ${N(p.take_profit)}</small>` : ''}</div></div>`;
}
function drawScan(j) {
  $('#scanProg').textContent = j.status === 'done' ? `اكتمل المسح (${j.done} أصل)` : `جارٍ المسح… ${j.done}/${j.total}`;
  const rows = [...j.results].sort((a, b) => b.score - a.score), ok = rows.filter(x => !x.error);
  const grp = (t, a) => a.length ? `<div class="grp-h">${t} <span class="pill">${a.length}</span></div><div class="lst" style="margin-top:0">${a.map(radRow).join('')}</div>` : '';
  const errs = rows.filter(x => x.error);
  $('#scanList').innerHTML = grp('جاهزة للتنفيذ — اجتازت الفلتر الصارم', ok.filter(x => x.plan && x.decision === 'APPROVED')) +
    grp('مضاربة — خطة لم تجتز الفلتر', ok.filter(x => x.plan && x.decision !== 'APPROVED')) +
    grp('لا صفقة الآن (السياق لا يسمح أو لا فرصة)', ok.filter(x => !x.plan)) +
    (errs.length ? `<div class="grp-h">تعذر فحصها <span class="pill">${errs.length}</span></div><div class="lst" style="margin-top:0">${errs.map(x => `<div class="li"><div class="t">${esc(x.symbol)}<small>${esc(x.error)}</small></div></div>`).join('')}</div>` : '') +
    (rows.length ? '<p class="hint" style="margin-top:12px">الدرجات: A قوية · B متوسطة · C ضعيفة (مضاربة). الدرجات ليست ضماناً.</p>' : '');
}
$('#scanList').addEventListener('click', e => { const r = e.target.closest('.rad'); if (r) openAnalysis(r.dataset.sym); });
$('#scanGo').onclick = async () => {
  $('#scanGo').disabled = true; $('#scanList').innerHTML = ''; $('#scanProg').textContent = 'جارٍ المسح…';
  const r = await api('/api/scan', {capital: $('#capital').value, style});
  clearInterval(scanTimer);
  scanTimer = setInterval(async () => { const j = await api('/api/job/' + r.id); drawScan(j); if (j.status === 'done') { clearInterval(scanTimer); $('#scanGo').disabled = false; } }, 1200);
};
function openAnalysis(sym) { pickSym(sym); goTab('desk'); $('#go').click(); }

/* ================= الحساب: محفظة تجريبية ================= */
const pct = v => Number(v || 0).toFixed(1) + '%';
async function loadPaper() { drawPaper(await api('/api/paper?refresh=1')); }
function drawPaper(d) {
  $('#paperStats').innerHTML = `<div class="stats"><div class="stat"><b>${N(Number(d.equity).toFixed(2))}</b><span>قيمة المحفظة (USDT)</span></div><div class="stat"><b class="${d.realized_pnl >= 0 ? 'up' : 'down'}">${N(Number(d.realized_pnl).toFixed(2))}</b><span>ربح محقق</span></div><div class="stat"><b>${N(Number(d.unrealized_pnl).toFixed(2))}</b><span>ربح عائم</span></div><div class="stat"><b>${N(Number(d.cash).toFixed(2))}</b><span>رصيد نقدي</span></div></div>`;
  $('#paperPositions').innerHTML = d.positions.length ? `<div class="lst" style="margin-top:6px">${d.positions.map(p => `<div class="li"><div class="t"><b>${esc(p.symbol)}</b> · ${p.side === 'LONG' ? 'شراء' : 'بيع'}<small>دخول ${p.entry} · السعر ${p.mark_price} · وقف ${p.stop} · هدف ${p.target}
كمية ${Number(p.qty).toFixed(6)} · عائم ${Number(p.unrealized_pnl).toFixed(2)}</small></div><button class="btn sm danger" data-close="${p.id}">إغلاق</button></div>`).join('')}</div>` : '<p class="hint">لا توجد مراكز مفتوحة.</p>';
}
$('#paperPositions').addEventListener('click', async e => {
  const b = e.target.closest('[data-close]'); if (!b) return;
  const r = await api('/api/paper/close', {id: b.dataset.close}); $('#paperMsg').textContent = r.error || 'تم إغلاق المركز'; loadPaper();
});
$('#paperOpen').onclick = async () => {
  const r = await api('/api/paper/open', {symbol: $('#paperSymbol').value, side: $('#paperSide').value, entry: $('#paperEntry').value, stop: $('#paperStop').value, target: $('#paperTarget').value, risk_pct: $('#paperRisk').value});
  $('#paperMsg').textContent = r.error || 'تم فتح المركز';
  if (r.ok) { $('#paperEntry').value = $('#paperStop').value = $('#paperTarget').value = ''; loadPaper(); }
};

/* ================= الحساب: MetaTrader 5 ================= */
async function loadMt5() {
  const box = $('#mt5Status'); box.textContent = 'جارٍ فحص MetaTrader 5…';
  try {
    const d = await api('/api/mt5/status');
    $('#mt5Auto').checked = !!(d.settings && d.settings.auto_trade); $('#mt5Risk').value = d.settings?.risk_pct ?? 0.5;
    box.textContent = d.connected && d.demo ? `متصل بحساب Demo · ${d.server} · الرصيد ${Number(d.balance).toFixed(2)} ${d.currency} · Equity ${Number(d.equity).toFixed(2)}` : (d.error || 'غير متصل بحساب Demo');
    if (d.connected && d.demo) {
      const perf = await api('/api/mt5/performance');
      $('#mt5Performance').innerHTML = perf.available ? `<div class="stats"><div class="stat"><b>${perf.trades}</b><span>صفقات مغلقة (90 يوماً)</span></div><div class="stat"><b>${perf.win_rate == null ? '—' : perf.win_rate + '%'}</b><span>نسبة النجاح</span></div><div class="stat"><b>${N(Number(perf.net_pnl).toFixed(2) + ' ' + perf.currency)}</b><span>صافي الربح</span></div></div><p class="hint">رابحة ${perf.wins} · خاسرة ${perf.losses} · متوسط الربح ${perf.avg_win ?? '—'} · متوسط الخسارة ${perf.avg_loss ?? '—'} · مراكز مفتوحة ${perf.open_positions.length}<br>${esc(perf.scope)}</p>` : `<p class="hint">${esc(perf.error || 'بيانات الأداء غير متاحة')}</p>`;
    } else $('#mt5Performance').innerHTML = '';
  } catch (e) { box.textContent = 'تعذر فحص MT5'; }
}
$('#mt5Connect').onclick = async () => { const b = $('#mt5Connect'); b.disabled = true; b.textContent = 'جارٍ الاتصال…'; await loadMt5(); b.disabled = false; b.textContent = 'اتصال وفحص الحساب'; };
$('#mt5Save').onclick = async () => {
  const en = $('#mt5Auto').checked, r = await api('/api/mt5/auto', {enabled: en, risk_pct: $('#mt5Risk').value});
  $('#mt5Status').textContent = r.error || (en ? 'تم تفعيل التداول التلقائي على Demo فقط' : 'تم إيقاف التداول التلقائي');
  if (r.ok) loadMt5(); else $('#mt5Auto').checked = false;
};

/* ================= الحساب: سجل القرارات ================= */
function badge(x) {
  if (x.status === 'open') return ['مفتوحة', 'brass']; if (x.status === 'tp') return ['حققت الهدف', 'buy'];
  if (x.status === 'sl') return ['ضُرب الوقف', 'sell']; if (x.status === 'expired') return ['منتهية', ''];
  return x.decision === 'REJECTED' ? ['مرفوض', ''] : ['—', ''];
}
function drawHist(d) {
  const h = d.items, s = d.stats; $('#clr').hidden = !h.length;
  $('#hstats').innerHTML = s.approved ? `<div class="stats"><div class="stat"><b>${s.approved}</b><span>صفقات مقترحة</span></div><div class="stat"><b class="up">${s.tp}</b><span>حققت الهدف</span></div><div class="stat"><b class="down">${s.sl}</b><span>ضُرب الوقف</span></div><div class="stat"><b>${s.win_rate === null ? '—' : s.win_rate + '%'}</b><span>نسبة النجاح الفعلية</span></div><div class="stat"><b>${s.avg_r === null ? '—' : s.avg_r}</b><span>متوسط R</span></div><div class="stat"><b>${s.open}</b><span>مفتوحة</span></div></div><p class="hint">${s.tp + s.sl < 30 ? 'النتائج المحسومة أقل من 30 صفقة — لا تبنِ عليها قراراً بعد. ' : ''}R: الربح بوحدات المخاطرة (الوقف = -1).</p>` : '';
  $('#hist').innerHTML = h.length ? `<div class="lst">${h.map(x => {
    const [t, c] = badge(x), ac = x.plan ? (x.plan.action === 'SELL' ? 'بيع' : 'شراء') + ' · ' : '';
    return `<div class="li tap"><div class="t"><b>${esc(x.symbol)}</b><small>${ac}${x.time.replace('T', ' ')} · ${x.style === 'scalp' ? 'سكالبينج' : 'صفقات'} · ${x.mode === 'ai' ? 'ذكاء اصطناعي' : x.mode === 'auto' ? 'مسح تلقائي' : 'محلي'}${x.r != null ? ' · R ' + x.r : ''}</small></div><span class="pill ${c}">${t}</span></div><div class="li-out">${esc(x.report)}</div>`;
  }).join('')}</div>` : '<div class="empty"><h3>لا توجد قرارات بعد</h3><div>شغّل أول تحليل من «المكتب» وسيظهر هنا مع نتيجته الفعلية.</div></div>';
}
async function loadHist() {
  drawHist(await api('/api/history')); $('#hupd').textContent = 'جارٍ تحديث نتائج الصفقات المفتوحة…';
  await api('/api/tracker/refresh', {}); drawHist(await api('/api/history')); $('#hupd').textContent = '';
}
$('#clr').onclick = async () => { await api('/api/history/clear', {}); loadHist(); };

/* ================= المختبر ================= */
const ORG = {builtin: ['مدمجة', ''], generated: ['مولّدة بالبحث', 'brass'], llm: ['اقتراح ذكاء اصطناعي', 'buy']};
function drawLab(d) {
  const s = d.summary;
  $('#labStats').innerHTML = `<div class="stats"><div class="stat"><b>${s.total}</b><span>في المخزون</span></div><div class="stat"><b class="up">${s.active}</b><span>نشطة</span></div><div class="stat"><b>${s.generated}</b><span>مولّدة</span></div><div class="stat"><b>${s.tested || 0}</b><span>فكرة اختُبرت</span></div></div><p class="hint">آخر بحث: ${s.last_run ? s.last_run.replace('T', ' ') : 'لم يُجرَ بعد'}</p>`;
  const items = [...d.items].sort((a, b) => (a.status === 'active' ? 0 : 1) - (b.status === 'active' ? 0 : 1));
  $('#labList').innerHTML = `<div class="lst">${items.map(it => {
    const v = it.stats && it.stats.val, te = it.stats && it.stats.test, [ol, oc] = ORG[it.origin] || ORG.builtin;
    return `<div class="li tap"><div class="t">${esc(it.name)}<small>${v ? `تحقق: ${v.n} صفقة · نجاح ${v.win_rate}% · PF ${v.pf} · ${v.avg_r}R\nاختبار أخير: ${te.n} صفقة · ${te.avg_r}R · اتساق ${Math.round((it.stats.consistency || 0) * 100)}%` : 'لم تُختبر بعد — شغّل البحث'}</small></div><span class="pill ${it.status === 'active' ? oc : ''}">${it.status === 'active' ? ol : 'موقوفة'}</span></div>
     <div class="li-out">وقف ${it.exits.sl_atr}×ATR · هدف 1:${it.exits.rr} · خروج زمني ${it.exits.hold} شمعة${it.note ? '\nالمصدر: ' + esc(it.note) : ''}<div class="acts"><button class="btn sm" data-lt="${it.id}">${it.status === 'active' ? 'إيقاف' : 'تفعيل'}</button>${it.origin !== 'builtin' ? `<button class="btn sm danger" data-ld="${it.id}">حذف</button>` : ''}</div></div>`;
  }).join('')}</div><p class="hint" style="margin-top:8px">«تحقق» و«اختبار أخير» على عدة أصول وفريمات مقسّمة زمنياً (60% تدريب · 20% تحقق · 20% اختبار أخير لم يُستعمل في الاختيار). الاستراتيجية النشطة تدخل التحليل فقط إن اجتازت اختباراً على الأصل نفسه.</p>`;
}
$('#labList').addEventListener('click', async e => {
  const t = e.target.closest('[data-lt]'), d = e.target.closest('[data-ld]');
  if (t) { await api('/api/lab/toggle', {id: t.dataset.lt}); loadLab(); }
  if (d) { await api('/api/lab/delete', {id: d.dataset.ld}); loadLab(); }
});
function drawBrain(d) {
  const s = d.summary, c = s.calibration;
  $('#brStats').innerHTML = `<div class="stats"><div class="stat"><b>${s.cycles}</b><span>دورات تعلم</span></div><div class="stat"><b>${s.relations}</b><span>علاقات مقبولة</span></div><div class="stat"><b class="up">${s.lab.active}</b><span>استراتيجيات نشطة</span></div></div><p class="hint" style="margin-bottom:10px">آخر دورة: ${s.last_cycle ? s.last_cycle.replace('T', ' ') : 'لم تبدأ بعد'}<br>${c ? `معايرة من صفقاتك الحية (${c.n} صفقة): المتوقع ${c.est}% مقابل الفعلي ${c.actual}% ← عامل ${c.factor}` : 'المعايرة من الصفقات الحية تبدأ بعد 20 صفقة محسومة.'}</p>`;
  $('#brRel').innerHTML = d.relations.length ? `<div class="lst" style="margin-top:6px">${d.relations.slice(0, 15).map(r => `<div class="li"><div class="t">${esc(r.text)}</div><span class="pill ${r.kind === 'leadlag' ? 'brass' : ''}">${r.kind === 'leadlag' ? 'تقدّم/تأخّر' : 'ارتباط'}</span></div>`).join('')}</div>` : '<p class="hint">لم تُكتشف علاقات بعد — شغّل دورة تعلم. الحد الصارم قد يعني أن النتيجة صفر، وهذا طبيعي.</p>';
  $('#brLog').innerHTML = d.log.length ? `<div class="lst" style="margin-top:6px">${d.log.slice(0, 8).map(e => `<div class="li tap"><div class="t">${e.time.replace('T', ' ')}<small>اختُبر ${e.strategies_tested} استراتيجية و${e.rel_tests} علاقة · أُضيف ${e.strategies_added.length} · أُوقف ${e.strategies_retired.length + e.live_retired.length}</small></div></div><div class="li-out">${e.strategies_added.length ? 'استراتيجيات مضافة: ' + e.strategies_added.map(esc).join('، ') + '\n' : ''}${e.relations_added.length ? 'علاقات:\n' + e.relations_added.map(esc).join('\n') + '\n' : ''}${e.live_retired.length ? 'أوقفتها نتائجك الحية: ' + e.live_retired.map(esc).join('، ') + '\n' : ''}${e.strategies_retired.length ? 'أُوقفت بعد فحص جديد: ' + e.strategies_retired.map(esc).join('، ') : ''}${!e.strategies_added.length && !e.relations_added.length ? 'لم يجد شيئاً يستحق القبول — البوابة صارمة عمداً.' : ''}</div>`).join('')}</div>` : '<p class="hint">لا سجل بعد.</p>';
}
async function loadBrain() { drawBrain(await api('/api/brain')); }
async function loadLab() { loadBrain(); drawLab(await api('/api/lab')); }
function track(btn, bar, prog, start, done) {
  btn.forEach(b => b.disabled = true); bar.hidden = false;
  start().then(r => {
    if (r.error) { prog.textContent = r.error; btn.forEach(b => b.disabled = false); bar.hidden = true; return; }
    const t = setInterval(async () => {
      const j = await api('/api/job/' + r.id); prog.textContent = j.msg; bar.firstElementChild.style.width = j.pct + '%';
      if (j.status !== 'running') { clearInterval(t); btn.forEach(b => b.disabled = false); bar.hidden = true; prog.textContent = j.status === 'done' ? done(j.result) : 'خطأ: ' + j.error; loadLab(); }
    }, 1200);
  });
}
$('#brGo').onclick = () => track([$('#brGo')], $('#brBar'), $('#brProg'), () => api('/api/brain/cycle', {llm: false}), () => 'اكتملت الدورة');
const startLab = llm => track([$('#labGo'), $('#labAi')], $('#labBar'), $('#labProg'), () => api('/api/lab/discover', {llm, n: 60}),
  r => `اختُبرت ${r.tested} فكرة في ${r.seconds}ث — أُضيف: ${r.added.length ? r.added.join('، ') : 'لا شيء (البوابة صارمة)'}${r.retired.length ? ' · أُوقف: ' + r.retired.join('، ') : ''}`);
$('#labGo').onclick = () => startLab(false); $('#labAi').onclick = () => startLab(true);

/* ================= الإعدادات والحالة ================= */
async function loadStatus() {
  const s = await api('/api/status');
  $('#s-py').textContent = s.deps.python; $('#s-deps').innerHTML = s.deps.missing.length ? `<span class="down">ناقص: ${esc(s.deps.missing.join(', '))}</span>` : '<span class="up">مكتملة</span>';
  $('#s-ai').textContent = s.ai_installed ? 'مثبتة' : 'غير مثبتة'; $('#s-key').textContent = s.key_set ? 'موجود' : 'غير موجود'; $('#s-xai').textContent = s.xai_set ? 'موجود' : 'غير موجود';
  $('#s-tg').textContent = s.tg_set ? 'مضبوط' : 'غير مضبوط'; $('#s-auto').textContent = s.auto_min ? `كل ${s.auto_min} دقيقة` : 'مطفأ';
  $('#grok_model').value = s.grok_model; $('#grok_review').value = s.grok_review ? '1' : '0'; $('#worker').value = s.worker; $('#ceo').value = s.ceo;
  $('#watchlist').value = s.watchlist; $('#auto_min').value = s.auto_min; $('#s_capital').value = s.capital; $('#tg_chat').value = s.tg_chat; $('#auto_mode').value = s.auto_mode; $('#lab_hours').value = s.lab_hours || '';
}
$('#save').onclick = async () => {
  const f = ['key', 'worker', 'ceo', 'watchlist', 'auto_min', 'tg_token', 'tg_chat', 'auto_mode', 'lab_hours', 'xai_key', 'grok_model', 'grok_review'], b = {capital: $('#s_capital').value};
  f.forEach(k => b[k] = $('#' + k).value);
  const r = await api('/api/settings', b); $('#setMsg').textContent = r.error || 'تم الحفظ';
  if (!r.error) ['key', 'tg_token', 'xai_key'].forEach(k => $('#' + k).value = '');
  loadStatus(); setTimeout(() => $('#setMsg').textContent = '', 2500);
};
$('#tgTest').onclick = async () => { $('#setMsg').textContent = 'جارٍ الإرسال…'; const r = await api('/api/notify/test', {}); $('#setMsg').textContent = r.ok ? 'وصل التنبيه التجريبي' : 'فشل: ' + (r.error || ''); };

/* ================= المكتبات الناقصة + الإشعارات + البدء ================= */
async function checkDeps() {
  const s = await api('/api/status'), d = s.deps, bar = $('#depsBar');
  if (!d.missing.length) { bar.innerHTML = ''; return; }
  bar.innerHTML = `<div class="note"><span>مكتبات ناقصة: <b class="num">${esc(d.missing.join(', '))}</b> — بعض الأصول (الذهب والفوركس والأسهم) لن تعمل بدونها.</span><button class="btn sm main-a" id="depsFix">ثبّت تلقائياً</button></div>`;
  $('#depsFix').onclick = async e => { e.target.disabled = true; e.target.textContent = 'جارٍ التثبيت…'; const r = await api('/api/deps/install', {}); bar.innerHTML = r.ok ? '<div class="note">تم تثبيت المكتبات. أعد التحليل.</div>' : `<div class="err">تعذر التثبيت التلقائي. نفّذ في الطرفية:<br><span class="num">${esc(r.fix || r.error)}</span></div>`; };
}
function toast(a) {
  const l = a.text.split('\n'); $('#toastT').textContent = l[0]; $('#toastB').textContent = l.slice(2, 6).join('\n');
  const t = $('#toast'); t.classList.add('show'); t.onclick = () => { t.classList.remove('show'); goTab('acct'); $('#acctTabs [data-t=hist]').click(); };
  setTimeout(() => t.classList.remove('show'), 9000);
}
setInterval(async () => { try { (await api('/api/alerts?after=' + lastAlert)).forEach(a => { lastAlert = a.id; toast(a); }); } catch (e) { } }, 20000);
api('/api/status').then(s => {
  STEPS = s.steps; lastAlert = s.alert_id;
  $('#pairs').innerHTML = s.assets.flatMap(g => g.items).map(i => `<option value="${i.symbol}">${esc(i.name)}</option>`).join('');
  buildQuick(s.assets); pickSym($('#symbol').value);
  if (s.deps.missing.length) checkDeps();
});
