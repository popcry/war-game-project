// 전투량 / 금액 추이를 별도 브라우저 창에 2D 캔버스 라인차트로 렌더링.
//
// openBattleGraph(data)
//   data = {
//     duration: number,
//     currentTime: number,                // 클릭 시점 — 세로 마커로 표시
//     series: {
//       red:  { units: [{t, n}], cost: [{t, total}] },
//       blue: { units: [{t, n}], cost: [{t, total}] },
//     }
//   }
// units(전투량)는 시간이 갈수록 감소(하락), cost(금액)는 누적 소비 비용이라 상승.
// 외부 라이브러리 없이 팝업 문서에 자체 완결된 캔버스를 그린다.

const RED = '#ff5b5b';
const BLUE = '#4ea0ff';
const BG = '#0b1116';
const PANEL = '#11181f';
const TEXT = '#e6edf3';
const MUTED = '#8b9aa8';
const GRID = 'rgba(255,255,255,0.08)';

export function openBattleGraph(data) {
  const win = window.open('', 'battleGraph', 'width=920,height=760');
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
  // 레이아웃이 잡힌 다음 그리기
  win.requestAnimationFrame(redraw);
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
  ctx.clearRect(0, 0, cssW, cssH);
  ctx.fillStyle = BG;
  ctx.fillRect(0, 0, cssW, cssH);

  const pad = 16;
  const gap = 18;
  const panelH = (cssH - pad * 2 - gap) / 2;
  const panelW = cssW - pad * 2;

  drawChart(ctx, { x: pad, y: pad, w: panelW, h: panelH }, {
    title: '전투량 추이 (생존 유닛 수)',
    yLabel: '유닛 수',
    duration: data.duration,
    currentTime: data.currentTime,
    series: [
      { points: data.series.red.units, key: 'n', color: RED, label: 'RED' },
      { points: data.series.blue.units, key: 'n', color: BLUE, label: 'BLUE' },
    ],
    yFormat: v => String(Math.round(v)),
  });

  drawChart(ctx, { x: pad, y: pad + panelH + gap, w: panelW, h: panelH }, {
    title: '금액 추이 (누적 소비 비용)',
    yLabel: '비용 ($)',
    duration: data.duration,
    currentTime: data.currentTime,
    series: [
      { points: data.series.red.cost, key: 'total', color: RED, label: 'RED' },
      { points: data.series.blue.cost, key: 'total', color: BLUE, label: 'BLUE' },
    ],
    yFormat: v => '$' + Math.round(v).toLocaleString('en-US'),
  });
}

function drawChart(ctx, area, opt) {
  const mL = 70, mR = 16, mT = 30, mB = 34;
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

  // 스케일 계산
  const xMax = Math.max(opt.duration, 1e-6);
  let yMax = 0;
  for (const s of opt.series) {
    for (const p of s.points) yMax = Math.max(yMax, p[s.key] ?? 0);
  }
  if (yMax <= 0) yMax = 1;
  yMax = niceCeil(yMax);

  const xToPx = t => plot.x + (t / xMax) * plot.w;
  const yToPx = v => plot.y + plot.h - (v / yMax) * plot.h;

  // 그리드 + y축 눈금 (5분할)
  ctx.font = '11px -apple-system, "Segoe UI", "Noto Sans KR", sans-serif';
  ctx.fillStyle = MUTED;
  ctx.strokeStyle = GRID;
  ctx.lineWidth = 1;
  const yTicks = 5;
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
    const px = xToPx(t);
    ctx.fillText(t.toFixed(0) + 's', px, plot.y + plot.h + 6);
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
      const py = yToPx(p[s.key] ?? 0);
      if (!started) { ctx.moveTo(px, py); started = true; }
      else ctx.lineTo(px, py);
    }
    ctx.stroke();
  }

  // 범례
  ctx.textAlign = 'left';
  ctx.textBaseline = 'middle';
  ctx.font = '12px -apple-system, "Segoe UI", "Noto Sans KR", sans-serif';
  let lx = plot.x + plot.w - 120;
  const ly = area.y + 20;
  for (const s of opt.series) {
    ctx.fillStyle = s.color;
    ctx.fillRect(lx, ly - 5, 18, 3);
    ctx.fillStyle = TEXT;
    ctx.fillText(s.label, lx + 24, ly);
    lx += 60;
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
