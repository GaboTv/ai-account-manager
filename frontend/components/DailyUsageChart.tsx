"use client";
import { useState } from "react";

export interface DayPoint {
  day: number; // day of month, 1-based
  value: number | null; // used_percent aggregate, null = no data
}

// Single-series column chart: days of the current month on x, 0-100% on y.
// Sequential single hue per chart (palette ref: blue #2a78d6/#3987e5,
// aqua #1baf7a/#199e70); title names the series so no legend is needed.
export default function DailyUsageChart({
  title,
  points,
  light,
  dark,
}: {
  title: string;
  points: DayPoint[];
  light: string;
  dark: string;
}) {
  const [tip, setTip] = useState<{ x: number; text: string } | null>(null);
  const monthName = new Date().toLocaleString(undefined, { month: "long" });

  return (
    <div
      className="relative"
      style={{ "--bar-light": light, "--bar-dark": dark } as React.CSSProperties}
    >
      <div className="mb-1 flex justify-between text-xs text-[#52514e] dark:text-[#c3c2b7]">
        <span>{title}</span>
        <span className="text-[#898781]">{monthName} · %</span>
      </div>
      <div
        className="relative h-16 rounded-sm bg-[#fcfcfb] dark:bg-[#1a1a19]"
        onMouseLeave={() => setTip(null)}
      >
        {/* hairline gridlines at 50/100 */}
        <div className="absolute inset-x-0 top-0 border-t border-[#e1e0d9] dark:border-[#2c2c2a]" />
        <div className="absolute inset-x-0 top-1/2 border-t border-[#e1e0d9] dark:border-[#2c2c2a]" />
        <div className="absolute inset-x-0 bottom-0 border-t border-[#c3c2b7] dark:border-[#383835]" />

        <div className="absolute inset-0 flex items-end gap-[2px] px-[2px]">
          {points.map((p) => (
            <div
              key={p.day}
              className="relative flex-1 cursor-default"
              style={{ height: "100%" }}
              onMouseEnter={(e) => {
                if (p.value === null) return setTip(null);
                const rect = e.currentTarget.parentElement!.getBoundingClientRect();
                const x = e.currentTarget.getBoundingClientRect().left - rect.left;
                setTip({ x, text: `${monthName} ${p.day} · ${p.value}%` });
              }}
            >
              {p.value !== null && (
                <div
                  className="usage-bar absolute bottom-0 w-full rounded-t-[3px]"
                  style={{ height: `${Math.max(p.value, 2)}%` }}
                />
              )}
            </div>
          ))}
        </div>

        {tip && (
          <div
            className="pointer-events-none absolute -top-6 z-10 rounded border border-black/10 bg-white px-1.5 py-0.5 text-[10px] text-[#0b0b0b] shadow-sm dark:border-white/10 dark:bg-[#2c2c2a] dark:text-white"
            style={{ left: Math.min(tip.x, 220) }}
          >
            {tip.text}
          </div>
        )}
      </div>
      <div className="mt-0.5 flex justify-between text-[9px] text-[#898781]">
        <span>1</span>
        <span>{points.length}</span>
      </div>
    </div>
  );
}
