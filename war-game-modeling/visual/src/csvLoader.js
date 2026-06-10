// CSV → scenario loader.
//
// Expected columns (header order is flexible, names are matched):
//   timestamp, team, agent_type, agent_id, x, y, z, yaw, alive, event, target
//
// `alive` carries the NATO 5-state kill classification:
//   alive    — fully operational
//   f_kill   — firepower kill (can move, can't shoot)
//   m_kill   — mobility kill (can shoot, can't move)
//   mf_kill  — mobility + firepower kill (crew alive, vehicle disabled)
//   k_kill   — catastrophic kill (unit destroyed)
// Legacy values are accepted for backwards compatibility:
//   operational / 1 / true   → alive
//   incapacitated            → mf_kill
//   destroyed  / 0 / false   → k_kill
// `timestamp` should be in ascending order; the loader sorts defensively
// per-agent in case input is not strictly ordered.
// `event` and `target` are optional. Rows with `event === 'fire'` are
// emitted into the events array as { t, shooter, target } in addition to
// being treated as ordinary track keyframes.

const REQUIRED = ['timestamp', 'team', 'agent_type', 'agent_id', 'x', 'y', 'z', 'alive'];

function parseCsvText(text) {
  const lines = text.split(/\r?\n/).filter(line => line.trim().length > 0);
  if (lines.length < 2) throw new Error('CSV is empty or has no data rows');

  const header = lines[0].split(',').map(s => s.trim());
  const idx = Object.fromEntries(header.map((h, i) => [h, i]));

  for (const col of REQUIRED) {
    if (!(col in idx)) throw new Error(`CSV missing required column: "${col}"`);
  }
  const hasYaw = 'yaw' in idx;
  const hasEvent = 'event' in idx;
  const hasTarget = 'target' in idx;
  const hasDamagedBy = 'damaged_by' in idx;

  // 5-state NATO kill classification with legacy 3-state / boolean fallback.
  // Downstream renderer collapses (f_kill, m_kill, mf_kill) into one visual
  // bucket; the raw value is preserved here for stats and the inspector.
  function parseStatus(raw) {
    const s = (raw ?? '').trim().toLowerCase();
    if (s === 'alive')   return 'alive';
    if (s === 'f_kill')  return 'f_kill';
    if (s === 'm_kill')  return 'm_kill';
    if (s === 'mf_kill') return 'mf_kill';
    if (s === 'k_kill')  return 'k_kill';
    // Legacy mappings:
    if (s === 'incapacitated')                           return 'mf_kill';
    if (s === 'destroyed' || s === '0' || s === 'false') return 'k_kill';
    // 'operational', '1', 'true', and unknown values all map to alive.
    return 'alive';
  }

  // CSV yaw is stored in math convention: yaw = atan2(Δz, Δx), so the unit's
  // forward vector is (cos yaw, sin yaw) with +x as reference. Our three.js
  // scene treats local +Z as the unit's forward, where mesh.rotation.y = θ
  // sends +Z to world (sin θ, cos θ). Converting once at load (π/2 − yaw_csv)
  // accounts for both the axis swap (+x↔+z) and the opposite rotation sense.
  const rows = new Array(lines.length - 1);
  for (let i = 1; i < lines.length; i++) {
    const f = lines[i].split(',');
    const status = parseStatus(f[idx.alive]);
    rows[i - 1] = {
      t:      parseFloat(f[idx.timestamp]),
      team:   f[idx.team].trim(),
      type:   f[idx.agent_type].trim(),
      id:     f[idx.agent_id].trim(),
      x:      parseFloat(f[idx.x]),
      y:      parseFloat(f[idx.y]),
      z:      parseFloat(f[idx.z]),
      yaw:    hasYaw ? (Math.PI / 2 - parseFloat(f[idx.yaw])) : 0,
      status,
      // `alive` is kept for downstream code that just needs "is the unit
      // still on the battlefield" — k_kill flips it false; every other
      // state (alive, f_kill, m_kill, mf_kill) keeps it true.
      alive:  status !== 'k_kill',
      event:  hasEvent  ? (f[idx.event]  ?? '').trim() : '',
      target: hasTarget ? (f[idx.target] ?? '').trim() : '',
      damagedBy: hasDamagedBy ? (f[idx.damaged_by] ?? '').trim() : '',
    };
  }
  return rows;
}

function rowsToScenario(rows) {
  const byId = new Map();
  const events = [];
  const killEvents = [];   // 킬로그용: damaged_by + 상태 변화가 있을 때 emit
  const lastStatusById = new Map();   // 상태 변화 감지용 (이전 상태)
  let duration = 0;
  let minX =  Infinity, maxX = -Infinity, minZ =  Infinity, maxZ = -Infinity;

  for (const r of rows) {
    if (!byId.has(r.id)) {
      byId.set(r.id, { id: r.id, team: r.team, type: r.type, track: [] });
    }
    byId.get(r.id).track.push({ t: r.t, x: r.x, y: r.y, z: r.z, yaw: r.yaw, alive: r.alive, status: r.status });
    if (r.event === 'fire' && r.target) {
      events.push({ t: r.t, shooter: r.id, target: r.target });
    }

    // 킬로그: damaged_by가 있고, 이전 상태와 달라졌을 때만 emit
    // (같은 공격자가 같은 victim을 연속해서 칠 때도 매 상태 전이마다 한 번씩 기록)
    if (r.damagedBy) {
      const prev = lastStatusById.get(r.id);
      if (prev !== r.status) {
        killEvents.push({
          t: r.t,
          attacker: r.damagedBy,
          victim: r.id,
          victimTeam: r.team,
          victimType: r.type,
          newStatus: r.status,   // 'alive' / 'm_kill' / 'f_kill' / 'mf_kill' / 'k_kill'
        });
      }
    }
    lastStatusById.set(r.id, r.status);

    if (r.t > duration) duration = r.t;
    if (r.x < minX) minX = r.x; if (r.x > maxX) maxX = r.x;
    if (r.z < minZ) minZ = r.z; if (r.z > maxZ) maxZ = r.z;
  }

  // Defensive: ensure each track is sorted by t ascending.
  const agents = [...byId.values()];
  for (const a of agents) a.track.sort((p, q) => p.t - q.t);
  events.sort((a, b) => a.t - b.t);
  killEvents.sort((a, b) => a.t - b.t);

  return {
    duration,
    bounds: { minX, maxX, minZ, maxZ },
    agents,
    events,
    killEvents,
  };
}

export async function loadScenarioFromCsv(url) {
  const res = await fetch(url);
  if (!res.ok) throw new Error(`failed to load ${url}: ${res.status} ${res.statusText}`);
  const text = await res.text();
  const rows = parseCsvText(text);
  return rowsToScenario(rows);
}
