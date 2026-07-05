"use client";
import { useRef, useState } from "react";

// Grafana-style dark dashboard primitives. Colors are the dataviz reference
// palette's validated dark steps (surface #1a1a19 on canvas #0d0d0d).
export const C = {
  canvas: "#0d0d0d",
  panel: "#1a1a19",
  border: "rgba(255,255,255,0.08)",
  grid: "#2c2c2a",
  base: "#383835",
  ink: "#e8e8e6",
  sec: "#b9b8ae",
  muted: "#898781",
  blue: "#3987e5",
  aqua: "#199e70",
  good: "#0ca30c",
  warn: "#fab219",
  crit: "#d03b3b",
};

export function Panel({ title, right, children }: {
  title: string; right?: React.ReactNode; children: React.ReactNode;
}) {
  return (
    <div className="rounded-md" style={{ background: C.panel, border: `1px solid ${C.border}` }}>
      <div className="flex items-center justify-between px-3 py-2"
           style={{ borderBottom: `1px solid ${C.border}` }}>
        <span className="text-xs font-medium" style={{ color: C.sec }}>{title}</span>
        <div className="text-[10px]" style={{ color: C.muted }}>{right}</div>
      </div>
      <div className="p-3">{children}</div>
    </div>
  );
}

// Big-number stat panel (label + value, optional colored value + unit).
export function Stat({ label, value, color = C.ink, unit }: {
  label: string; value: string | number; color?: string; unit?: string;
}) {
  return (
    <div className="rounded-md px-3 py-3" style={{ background: C.panel, border: `1px solid ${C.border}` }}>
      <div className="text-[10px] uppercase tracking-wide" style={{ color: C.muted }}>{label}</div>
      <div className="mt-1 flex items-baseline gap-1">
        <span className="text-3xl font-semibold leading-none" style={{ color }}>{value}</span>
        {unit && <span className="text-xs" style={{ color: C.muted }}>{unit}</span>}
      </div>
    </div>
  );
}

export interface Series { name: string; color: string; points: (number | null)[] }

function runs(points: (number | null)[]): number[][] {
  const out: number[][] = [];
  let cur: number[] = [];
  points.forEach((v, i) => {
    if (v == null) { if (cur.length) { out.push(cur); cur = []; } }
    else cur.push(i);
  });
  if (cur.length) out.push(cur);
  return out;
}

// SVG time-series panel: 0-100% y, day-of-month x, hairline grid, area+line
// per series, crosshair hover. Handles sparse data (isolated days = dots).
export function TimeSeries({ title, right, days, series, monthLabel }: {
  title: string; right?: React.ReactNode; days: number; series: Series[]; monthLabel: string;
}) {
  const [hover, setHover] = useState<{ idx: number; px: number } | null>(null);
  const box = useRef<HTMLDivElement>(null);

  const W = 340, H = 150, padL = 30, padR = 10, padT = 12, padB = 20;
  const plotW = W - padL - padR, plotH = H - padT - padB;
  const x = (i: number) => (days <= 1 ? padL + plotW / 2 : padL + (i / (days - 1)) * plotW);
  const y = (v: number) => padT + (1 - Math.min(v, 100) / 100) * plotH;

  const onMove = (e: React.MouseEvent) => {
    const r = box.current!.getBoundingClientRect();
    const ratio = Math.min(1, Math.max(0, (e.clientX - r.left) / r.width));
    setHover({ idx: Math.round(ratio * (days - 1)), px: ratio * r.width });
  };

  const hasData = series.some((s) => s.points.some((p) => p != null));

  return (
    <Panel title={title} right={right}>
      <div className="mb-2 flex gap-3 text-[10px]" style={{ color: C.sec }}>
        {series.map((s) => (
          <span key={s.name} className="flex items-center gap-1">
            <span className="inline-block h-[2px] w-3 rounded" style={{ background: s.color }} />
            {s.name}
          </span>
        ))}
      </div>
      <div ref={box} className="relative" onMouseMove={onMove} onMouseLeave={() => setHover(null)}>
        <svg viewBox={`0 0 ${W} ${H}`} className="w-full" style={{ height: "auto" }}>
          {[0, 25, 50, 75, 100].map((g) => (
            <g key={g}>
              <line x1={padL} x2={W - padR} y1={y(g)} y2={y(g)}
                    stroke={g === 0 ? C.base : C.grid} strokeWidth={1} vectorEffect="non-scaling-stroke" />
              <text x={padL - 5} y={y(g) + 3} textAnchor="end" fontSize={8} fill={C.muted}>{g}</text>
            </g>
          ))}
          {[1, Math.ceil(days / 2), days].map((d) => (
            <text key={d} x={x(d - 1)} y={H - 6} textAnchor="middle" fontSize={8} fill={C.muted}>{d}</text>
          ))}

          {series.map((s) => (
            <g key={s.name}>
              {runs(s.points).map((run, ri) => {
                if (run.length === 1) return null;
                const line = run.map((i) => `${x(i)},${y(s.points[i] as number)}`).join(" ");
                const area = `${x(run[0])},${y(0)} ` + line + ` ${x(run[run.length - 1])},${y(0)}`;
                return (
                  <g key={ri}>
                    <polygon points={area} fill={s.color} opacity={0.1} />
                    <polyline points={line} fill="none" stroke={s.color} strokeWidth={2}
                              strokeLinejoin="round" strokeLinecap="round" vectorEffect="non-scaling-stroke" />
                  </g>
                );
              })}
              {s.points.map((v, i) => v == null ? null : (
                <circle key={i} cx={x(i)} cy={y(v)} r={2.6} fill={s.color}
                        stroke={C.panel} strokeWidth={1.5} />
              ))}
            </g>
          ))}

          {hover && (
            <line x1={x(hover.idx)} x2={x(hover.idx)} y1={padT} y2={H - padB}
                  stroke={C.sec} strokeWidth={1} strokeDasharray="3 3" vectorEffect="non-scaling-stroke" opacity={0.6} />
          )}
        </svg>

        {hover && series.some((s) => s.points[hover.idx] != null) && (
          <div className="pointer-events-none absolute -top-1 z-10 rounded border px-2 py-1 text-[10px]"
               style={{ left: Math.min(hover.px, 220), background: "#0b0b0b", borderColor: C.border, color: C.ink }}>
            <div style={{ color: C.muted }}>{monthLabel} {hover.idx + 1}</div>
            {series.map((s) => s.points[hover.idx] == null ? null : (
              <div key={s.name} className="flex items-center gap-1">
                <span className="inline-block h-2 w-2 rounded-full" style={{ background: s.color }} />
                {s.name}: {s.points[hover.idx]}%
              </div>
            ))}
          </div>
        )}

        {!hasData && (
          <div className="absolute inset-0 flex items-center justify-center text-[11px]" style={{ color: C.muted }}>
            No data yet
          </div>
        )}
      </div>
    </Panel>
  );
}
