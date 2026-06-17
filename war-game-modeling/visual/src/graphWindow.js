// 전투량 / 금액 추이를 별도 브라우저 창에 2D 캔버스 라인차트로 렌더링.
//
// openBattleGraph(data)
//   data = {
//     duration: number,
//     currentTime: number,          // 클릭 시점 — 세로 마커로 표시
//     charts: [                      // 위에서부터 세로로 쌓아 그림
//       {
//         title: string,
//         yLabel: string,            // (현재 축 옆 라벨은 생략, 제목으로 대체)
//         yFormat: (v) => string,    // y축 눈금 포맷
//         series: [ { points: [{t, v}], color, label } ],
//       }, ...
//     ]
//   }
// 외부 라이브러리 없이 팝업 문서에 자체 완결된 캔버스를 그린다.

const BG = '#ffffff';
const PANEL = '#ffffff';
const TEXT = '#17202a';
const MUTED = '#667085';
const GRID = 'rgba(0,0,0,0.10)';

export function openBattleGraph(data) {
  const win = window.open('', 'battleGraphWhite20260614', 'width=960,height=860');
  if (!win) {
    alert('팝업이 차단되었습니다. 브라우저에서 이 사이트의 팝업을 허용한 뒤 다시 시도하세요.');
    return;
  }
  const doc = win.document;
  doc.title = '전투량 / 금액 추이';
  doc.body.style.cssText = 'margin:0;background:' + BG + ';overflow:hidden;';
  doc.body.innerHTML = '<canvas id="g" style="display:block"></canvas>';
  const canvas = doc.getElementById('g');

  const redraw = () => drawAll(win, canvas, data);
  win.requestAnimationFrame(redraw);  // 레이아웃이 잡힌 뒤 그리기
  win.addEventListener('resize', redraw);
}

function drawAll(win, canvas, data) {
  const dpr = win.devicePixelRatio || 1;
  const cssW = win.innerWidth;
  const cssH = win.innerHeight;
  canvas.width = Math.max(1, Math.round(cssW * dpr));
  canvas.height = Math.max(1, Math.round(cssH * dpr));
  canvas.style.width = cssW + 'px';
  canvas.style.height = cssH + 'px';

  const ctx = canvas.getContext('2d');
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  ctx.fillStyle = BG;
  ctx.fillRect(0, 0, cssW, cssH);

  const charts = data.charts || [];
  const n = charts.length;
  if (n === 0) return;

  const pad = 16;
  const gap = 16;
  const panelH = (cssH - pad * 2 - gap * (n - 1)) / n;
  const panelW = cssW - pad * 2;

  for (let i = 0; i < n; i++) {
    drawChart(ctx, { x: pad, y: pad + i * (panelH + gap), w: panelW, h: panelH }, {
      ...charts[i],
      duration: data.duration,
      currentTime: data.currentTime,
    });
  }
}

function drawChart(ctx, area, opt) {
  const mL = 72, mR = 16, mT = 30, mB = 30;
  const plot = {
    x: area.x + mL,
    y: area.y + mT,
    w: Math.max(1, area.w - mL - mR),
    h: Math.max(1, area.h - mT - mB),
  };

  // 패널 배경
  ctx.fillStyle = PANEL;
  roundRect(ctx, area.x, area.y, area.w, area.h, 8);
  ctx.fill();

  // 제목
  ctx.fillStyle = TEXT;
  ctx.font = '600 14px -apple-system, "Segoe UI", "Noto Sans KR", sans-serif';
  ctx.textAlign = 'left';
  ctx.textBaseline = 'alphabetic';
  ctx.fillText(opt.title, area.x + 12, area.y + 20);
  const titleW = ctx.measureText(opt.title).width;

  // 스케일 계산
  const xMax = Math.max(opt.duration, 1e-6);
  let yMax = 0;
  for (const s of opt.series) {
    for (const p of s.points) yMax = Math.max(yMax, p.v ?? 0);
  }
  if (yMax <= 0) yMax = 1;
  yMax = niceCeil(yMax);

  const xToPx = t => plot.x + (t / xMax) * plot.w;
  const yToPx = v => plot.y + plot.h - (v / yMax) * plot.h;

  // 그리드 + y축 눈금 (5분할)
  ctx.font = '11px -apple-system, "Segoe UI", "Noto Sans KR", sans-serif';
  ctx.strokeStyle = GRID;
  ctx.lineWidth = 1;
  const yTicks = 5;
  ctx.fillStyle = MUTED;
  ctx.textAlign = 'right';
  ctx.textBaseline = 'middle';
  for (let i = 0; i <= yTicks; i++) {
    const v = (yMax / yTicks) * i;
    const py = yToPx(v);
    ctx.beginPath();
    ctx.moveTo(plot.x, py);
    ctx.lineTo(plot.x + plot.w, py);
    ctx.stroke();
    ctx.fillText(opt.yFormat(v), plot.x - 8, py);
  }

  // x축 눈금
  const xTicks = 6;
  ctx.textAlign = 'center';
  ctx.textBaseline = 'top';
  for (let i = 0; i <= xTicks; i++) {
    const t = (xMax / xTicks) * i;
    ctx.fillText(t.toFixed(0) + 's', xToPx(t), plot.y + plot.h + 6);
  }

  // 현재 시점 마커
  if (typeof opt.currentTime === 'number' && opt.currentTime >= 0 && opt.currentTime <= xMax) {
    const px = xToPx(opt.currentTime);
    ctx.strokeStyle = 'rgba(255,209,102,0.7)';
    ctx.setLineDash([4, 4]);
    ctx.beginPath();
    ctx.moveTo(px, plot.y);
    ctx.lineTo(px, plot.y + plot.h);
    ctx.stroke();
    ctx.setLineDash([]);
  }

  // 데이터 라인
  ctx.lineWidth = 2;
  for (const s of opt.series) {
    if (!s.points || s.points.length === 0) continue;
    ctx.strokeStyle = s.color;
    ctx.beginPath();
    let started = false;
    for (const p of s.points) {
      const px = xToPx(p.t);
      const py = yToPx(p.v ?? 0);
      if (!started) { ctx.moveTo(px, py); started = true; }
      else ctx.lineTo(px, py);
    }
    ctx.stroke();
  }

  // 범례 — 제목 우측, 측정 너비로 우측 정렬 한 줄 배치
  ctx.font = '12px -apple-system, "Segoe UI", "Noto Sans KR", sans-serif';
  ctx.textBaseline = 'middle';
  const SW = 16, GAPSW = 6, GAPITEM = 14;
  const items = opt.series.map(s => ({ s, w: SW + GAPSW + ctx.measureText(s.label).width + GAPITEM }));
  const totalW = items.reduce((a, b) => a + b.w, 0);
  const minX = area.x + 12 + titleW + 16;
  let lx = Math.max(minX, area.x + area.w - 12 - totalW);
  const ly = area.y + 14;
  ctx.textAlign = 'left';
  for (const it of items) {
    ctx.strokeStyle = it.s.color;
    ctx.lineWidth = 3;
    ctx.beginPath();
    ctx.moveTo(lx, ly);
    ctx.lineTo(lx + SW, ly);
    ctx.stroke();
    ctx.fillStyle = TEXT;
    ctx.fillText(it.s.label, lx + SW + GAPSW, ly);
    lx += it.w;
  }
}

function niceCeil(v) {
  // 축 상한을 보기 좋은 값으로 올림 (1·2·5 × 10^n)
  const exp = Math.floor(Math.log10(v));
  const base = Math.pow(10, exp);
  const f = v / base;
  let nice;
  if (f <= 1) nice = 1;
  else if (f <= 2) nice = 2;
  else if (f <= 5) nice = 5;
  else nice = 10;
  return nice * base;
}

function roundRect(ctx, x, y, w, h, r) {
  ctx.beginPath();
  ctx.moveTo(x + r, y);
  ctx.arcTo(x + w, y, x + w, y + h, r);
  ctx.arcTo(x + w, y + h, x, y + h, r);
  ctx.arcTo(x, y + h, x, y, r);
  ctx.arcTo(x, y, x + w, y, r);
  ctx.closePath();
}
