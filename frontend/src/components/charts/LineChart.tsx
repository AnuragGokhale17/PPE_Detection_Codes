"use client";

import { useEffect, useMemo, useRef, useState } from "react";

import { formatNumber } from "@/lib/format";

export interface LinePoint {
  key: string;
  y: number;
}

const M = { top: 16, right: 16, bottom: 28, left: 44 };

function niceMax(v: number): number {
  if (v <= 0) return 1;
  const exp = Math.pow(10, Math.floor(Math.log10(v)));
  for (const m of [1, 2, 2.5, 5, 10]) {
    if (v <= m * exp) return m * exp;
  }
  return 10 * exp;
}

/**
 * Single-series line over evenly spaced buckets (hours, days, epochs).
 * Graphite 2px line with a 10% wash; crosshair snaps to the nearest bucket and
 * works from the keyboard; the peak is labelled; a table view mirrors the data.
 */
export function LineChart({
  points,
  formatKey,
  formatTick = formatKey,
  formatValue = (v) => formatNumber(v),
  yMax,
  height = 220,
  ariaLabel,
  valueLabel,
}: {
  points: LinePoint[];
  formatKey: (key: string) => string;
  formatTick?: (key: string) => string;
  formatValue?: (v: number) => string;
  yMax?: number;
  height?: number;
  ariaLabel: string;
  valueLabel: string;
}) {
  const wrap = useRef<HTMLDivElement>(null);
  const [width, setWidth] = useState(640);
  const [active, setActive] = useState<number | null>(null);
  const [showTable, setShowTable] = useState(false);

  useEffect(() => {
    const el = wrap.current;
    if (!el) return;
    const ro = new ResizeObserver(([entry]) => setWidth(Math.max(280, entry.contentRect.width)));
    ro.observe(el);
    return () => ro.disconnect();
  }, []);

  const geo = useMemo(() => {
    const innerW = width - M.left - M.right;
    const innerH = height - M.top - M.bottom;
    const top = yMax ?? niceMax(Math.max(0, ...points.map((p) => p.y)));
    const n = points.length;
    const x = (i: number) => M.left + (n <= 1 ? innerW / 2 : (i / (n - 1)) * innerW);
    const y = (v: number) => M.top + innerH - (v / top) * innerH;
    const ticks = [0, 0.25, 0.5, 0.75, 1].map((f) => f * top);
    const every = Math.max(1, Math.ceil(n / Math.max(2, Math.floor(innerW / 90))));
    const xTicks = points.map((p, i) => ({ i, key: p.key })).filter(({ i }) => i % every === 0);
    const line = points.map((p, i) => `${i ? "L" : "M"}${x(i).toFixed(1)},${y(p.y).toFixed(1)}`).join("");
    const area = n ? `${line}L${x(n - 1).toFixed(1)},${y(0)}L${x(0).toFixed(1)},${y(0)}Z` : "";
    let peak = -1;
    points.forEach((p, i) => {
      if (p.y > 0 && (peak < 0 || p.y > points[peak].y)) peak = i;
    });
    return { innerW, innerH, x, y, ticks, xTicks, line, area, peak, top };
  }, [points, width, height, yMax]);

  function onPointer(e: React.PointerEvent<SVGSVGElement>) {
    const rect = e.currentTarget.getBoundingClientRect();
    const px = e.clientX - rect.left;
    const n = points.length;
    if (!n) return;
    const i = Math.round(((px - M.left) / geo.innerW) * (n - 1));
    setActive(Math.min(n - 1, Math.max(0, i)));
  }

  function onKey(e: React.KeyboardEvent) {
    if (!points.length) return;
    if (e.key === "ArrowRight" || e.key === "ArrowLeft") {
      e.preventDefault();
      setActive((a) => {
        const cur = a ?? (e.key === "ArrowRight" ? -1 : points.length);
        return Math.min(points.length - 1, Math.max(0, cur + (e.key === "ArrowRight" ? 1 : -1)));
      });
    } else if (e.key === "Escape") {
      setActive(null);
    }
  }

  const activePoint = active != null ? points[active] : null;
  const tooltipLeft = active != null ? Math.min(Math.max(geo.x(active), 70), width - 70) : 0;

  return (
    <div>
      <div ref={wrap} className="relative">
        <svg
          width={width}
          height={height}
          role="img"
          aria-label={ariaLabel}
          tabIndex={0}
          className="block touch-none focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent-200 rounded-sm"
          onPointerMove={onPointer}
          onPointerLeave={() => setActive(null)}
          onKeyDown={onKey}
          onBlur={() => setActive(null)}
        >
          {geo.ticks.map((t) => (
            <g key={t}>
              <line x1={M.left} x2={width - M.right} y1={geo.y(t)} y2={geo.y(t)} stroke="var(--line)" strokeWidth={1} />
              <text x={M.left - 8} y={geo.y(t)} dy="0.32em" textAnchor="end" className="tabular fill-ink-3 text-[11px]">
                {formatValue(t)}
              </text>
            </g>
          ))}
          {geo.xTicks.map(({ i, key }) => (
            <text key={key} x={geo.x(i)} y={height - 8} textAnchor="middle" className="tabular fill-ink-3 text-[11px]">
              {formatTick(key)}
            </text>
          ))}
          <path d={geo.area} fill="var(--data)" opacity={0.1} />
          <path d={geo.line} fill="none" stroke="var(--data)" strokeWidth={2} strokeLinejoin="round" strokeLinecap="round" />
          {geo.peak >= 0 && active == null && (
            <g>
              <circle cx={geo.x(geo.peak)} cy={geo.y(points[geo.peak].y)} r={4} fill="var(--data)" stroke="var(--surface)" strokeWidth={2} />
              <text
                x={geo.x(geo.peak)}
                y={geo.y(points[geo.peak].y) - 10}
                textAnchor={geo.x(geo.peak) > width - 60 ? "end" : geo.x(geo.peak) < 60 ? "start" : "middle"}
                className="tabular fill-ink text-[11px] font-medium"
              >
                Peak {formatValue(points[geo.peak].y)}
              </text>
            </g>
          )}
          {activePoint && active != null && (
            <g aria-hidden>
              <line x1={geo.x(active)} x2={geo.x(active)} y1={M.top} y2={M.top + geo.innerH} stroke="var(--ink-3)" strokeWidth={1} />
              <circle cx={geo.x(active)} cy={geo.y(activePoint.y)} r={4} fill="var(--data)" stroke="var(--surface)" strokeWidth={2} />
            </g>
          )}
        </svg>
        {activePoint && (
          <div
            role="status"
            className="pointer-events-none absolute top-0 -translate-x-1/2 rounded-md border border-line bg-surface px-2.5 py-1.5 shadow-md"
            style={{ left: tooltipLeft }}
          >
            <p className="tabular text-sm font-bold text-ink">{formatValue(activePoint.y)}</p>
            <p className="flex items-center gap-1.5 text-[11px] text-ink-3 whitespace-nowrap">
              <span className="inline-block h-0.5 w-3 bg-data" aria-hidden />
              {valueLabel} · {formatKey(activePoint.key)}
            </p>
          </div>
        )}
      </div>
      <button type="button" className="mt-1 text-xs font-medium text-accent-700 hover:underline" onClick={() => setShowTable((s) => !s)}>
        {showTable ? "Hide table" : "View as table"}
      </button>
      {showTable && (
        <div className="mt-2 max-h-56 overflow-y-auto rounded-md border border-line">
          <table className="w-full text-left text-xs">
            <thead className="sticky top-0 bg-surface-2 text-ink-3">
              <tr>
                <th scope="col" className="px-3 py-1.5 font-medium">Period</th>
                <th scope="col" className="px-3 py-1.5 text-right font-medium">{valueLabel}</th>
              </tr>
            </thead>
            <tbody>
              {points.map((p) => (
                <tr key={p.key} className="border-t border-line">
                  <td className="px-3 py-1">{formatKey(p.key)}</td>
                  <td className="tabular px-3 py-1 text-right">{formatValue(p.y)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
