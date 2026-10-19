/**
 * هندسه مسیر روی نقشه: منحنی نرم (Catmull-Rom → بزیه مکعبی) از میان شهرها، و تبدیل «کیلومتر پیموده‌شده» به نقطه روی منحنی.
 * پیشرفت بر حسب کیلومتر جاده‌ای است، پس طول هندسی هر قطعه جدا حساب می‌شود تا نقطه هرگز از شهرِ گزارش‌نشده رد نشود.
 */
export type Pt = [number, number];
type Seg = [Pt, Pt, Pt, Pt];

const add = (a: Pt, b: Pt): Pt => [a[0] + b[0], a[1] + b[1]];
const sub = (a: Pt, b: Pt): Pt => [a[0] - b[0], a[1] - b[1]];
const mul = (a: Pt, k: number): Pt => [a[0] * k, a[1] * k];
const lerp = (a: Pt, b: Pt, t: number): Pt => [a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t];

function segments(pts: Pt[]): Seg[] {
  if (pts.length < 2) return [];
  if (pts.length === 2) {
    // دو شهر: کمان (مثل خطوط پرواز) — نقطه کنترل عمود بر وتر
    const [a, b] = pts;
    const mid = lerp(a, b, 0.5);
    const d = sub(b, a);
    const q = add(mid, mul([d[1], -d[0]], 0.18));
    return [[a, lerp(a, q, 2 / 3), lerp(b, q, 2 / 3), b]];
  }
  const out: Seg[] = [];
  for (let i = 0; i < pts.length - 1; i++) {
    const p0 = pts[i - 1] ?? pts[i], p1 = pts[i], p2 = pts[i + 1], p3 = pts[i + 2] ?? pts[i + 1];
    out.push([p1, add(p1, mul(sub(p2, p0), 1 / 6)), sub(p2, mul(sub(p3, p1), 1 / 6)), p2]);
  }
  return out;
}

function at(s: Seg, t: number): Pt {
  const a = lerp(s[0], s[1], t), b = lerp(s[1], s[2], t), c = lerp(s[2], s[3], t);
  return lerp(lerp(a, b, t), lerp(b, c, t), t);
}

/** نیمه اول قطعه تا پارامتر t (الگوریتم دکاستلژو) */
function split(s: Seg, t: number): Seg {
  const a = lerp(s[0], s[1], t), b = lerp(s[1], s[2], t), c = lerp(s[2], s[3], t);
  const d = lerp(a, b, t), e = lerp(b, c, t);
  return [s[0], a, d, lerp(d, e, t)];
}

const SAMPLES = 32;
/** طول تجمعی نمونه‌ها برای تبدیل «سهم طول» به پارامتر t */
function lengthTable(s: Seg): number[] {
  const table = [0];
  let prev = s[0];
  for (let i = 1; i <= SAMPLES; i++) {
    const p = at(s, i / SAMPLES);
    table.push(table[i - 1] + Math.hypot(p[0] - prev[0], p[1] - prev[1]));
    prev = p;
  }
  return table;
}

function tForShare(table: number[], share: number): number {
  const target = share * table[SAMPLES];
  for (let i = 1; i <= SAMPLES; i++) {
    if (table[i] >= target) {
      const span = table[i] - table[i - 1] || 1;
      return (i - 1 + (target - table[i - 1]) / span) / SAMPLES;
    }
  }
  return 1;
}

const toD = (segs: Seg[]) => segs.length
  ? `M${segs[0][0][0].toFixed(1)},${segs[0][0][1].toFixed(1)}` + segs.map(s => `C${s[1].map(v => v.toFixed(1))} ${s[2].map(v => v.toFixed(1))} ${s[3].map(v => v.toFixed(1))}`).join("")
  : "";

export type RouteShape = { d: string; segs: Seg[]; tables: number[][]; kms: number[] };

export function routeShape(points: Pt[], kms: number[]): RouteShape {
  const segs = segments(points);
  return { d: toD(segs), segs, tables: segs.map(lengthTable), kms };
}

/** مسیر پیموده‌شده تا km و نقطه فعلی */
export function progressAt(shape: RouteShape, km: number): { d: string; point: Pt | null } {
  const { segs, tables, kms } = shape;
  if (!segs.length) return { d: "", point: null };
  if (km <= 0) return { d: "", point: segs[0][0] };
  const done: Seg[] = [];
  for (let i = 0; i < segs.length; i++) {
    const from = kms[i], to = kms[i + 1];
    if (km >= to) { done.push(segs[i]); continue; }
    const share = to > from ? (km - from) / (to - from) : 1;
    const t = tForShare(tables[i], Math.max(0, Math.min(1, share)));
    const part = split(segs[i], t);
    done.push(part);
    return { d: toD(done), point: part[3] };
  }
  return { d: toD(done), point: segs[segs.length - 1][3] };
}
