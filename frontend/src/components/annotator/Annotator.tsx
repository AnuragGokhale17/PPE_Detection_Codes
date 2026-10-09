"use client";

import { Eye, EyeOff, Maximize, Minus, Plus, Redo2, Trash2, Undo2 } from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import type { useBoxHistory } from "./useBoxHistory";
import { newId, type Box, type ClassInfo } from "./types";

// Same colours inference.py draws on the evidence images, so reviewers read them the same way
const VIOLATION = "#ef4444";
const COMPLIANT = "#10b981";
const MIN_PX = 4;
const MAX_ZOOM = 10;
const KEYS = ["1", "2", "3", "4", "5", "6", "7", "8", "9", "0"];

type Handle = "nw" | "n" | "ne" | "e" | "se" | "s" | "sw" | "w";
const HANDLES: Handle[] = ["nw", "n", "ne", "e", "se", "s", "sw", "w"];

type Drag =
  | { kind: "draw"; sx: number; sy: number; box: Box }
  | { kind: "move"; id: string; sx: number; sy: number; orig: Box; moved: boolean }
  | { kind: "resize"; id: string; handle: Handle; orig: Box; box: Box }
  | { kind: "pan"; cx: number; cy: number; px: number; py: number };

type History = ReturnType<typeof useBoxHistory>;

const clamp = (v: number, lo = 0, hi = 1) => Math.min(hi, Math.max(lo, v));
const norm = (b: Box): Box => ({ ...b, x1: Math.min(b.x1, b.x2), x2: Math.max(b.x1, b.x2), y1: Math.min(b.y1, b.y2), y2: Math.max(b.y1, b.y2) });

export function Annotator({
  imageUrl,
  width,
  height,
  classes,
  history,
  activeClassId,
  onActiveClassChange,
  suggestions = [],
  onAcceptSuggestion,
  readOnly = false,
}: {
  imageUrl: string;
  width: number;
  height: number;
  classes: ClassInfo[];
  history: History;
  activeClassId: number;
  onActiveClassChange: (id: number) => void;
  suggestions?: Box[];
  onAcceptSuggestion?: (box: Box) => void;
  readOnly?: boolean;
}) {
  const { boxes, commit, undo, redo, canUndo, canRedo } = history;
  const viewport = useRef<HTMLDivElement>(null);
  const stage = useRef<HTMLDivElement>(null);
  const spaceDown = useRef(false);
  const [view, setView] = useState({ w: 800, h: 500 });
  const [zoom, setZoom] = useState(1);
  const [pan, setPan] = useState({ x: 0, y: 0 });
  const [selected, setSelected] = useState<string | null>(null);
  const [drag, setDrag] = useState<Drag | null>(null);
  // Live position of a box being moved; committed to history once on release
  const [movePreview, setMovePreview] = useState<Box | null>(null);
  const [showLabels, setShowLabels] = useState(true);
  const [loaded, setLoaded] = useState(false);
  const [imgError, setImgError] = useState(false);

  const classById = useMemo(() => new Map(classes.map((c) => [c.class_id, c])), [classes]);
  const keyed = useMemo(() => classes.filter((c) => c.enabled).slice(0, KEYS.length), [classes]);
  const aspect = width / height;
  const fit = useMemo(() => {
    const w = Math.min(view.w, view.h * aspect);
    return { w, h: w / aspect };
  }, [view, aspect]);

  const resetView = useCallback(() => setZoom(1), []);

  useEffect(() => {
    const el = viewport.current;
    if (!el) return;
    const ro = new ResizeObserver(([e]) => setView({ w: e.contentRect.width, h: e.contentRect.height }));
    ro.observe(el);
    return () => ro.disconnect();
  }, []);

  // At 100% the frame is always centred; the stored pan only applies once zoomed in
  const offset = zoom === 1 ? { x: (view.w - fit.w) / 2, y: (view.h - fit.h) / 2 } : pan;

  // While dragging, render the in-progress box in place of the committed one
  const rendered = useMemo(() => {
    if (!drag || drag.kind === "pan") return boxes;
    if (drag.kind === "draw") return [...boxes, norm(drag.box)];
    if (drag.kind === "resize") return boxes.map((b) => (b.id === drag.id ? norm(drag.box) : b));
    return boxes;
  }, [boxes, drag]);

  const toNorm = (clientX: number, clientY: number) => {
    const r = stage.current!.getBoundingClientRect();
    return { x: clamp((clientX - r.left) / r.width), y: clamp((clientY - r.top) / r.height) };
  };

  const minW = MIN_PX / width;
  const minH = MIN_PX / height;

  function onPointerDown(e: React.PointerEvent) {
    if (e.button === 2) return;
    viewport.current?.focus();
    const target = e.target as HTMLElement;
    const wantsPan = e.button === 1 || spaceDown.current || readOnly;
    if (wantsPan) {
      e.preventDefault();
      setDrag({ kind: "pan", cx: e.clientX, cy: e.clientY, px: offset.x, py: offset.y });
      viewport.current?.setPointerCapture(e.pointerId);
      return;
    }
    const handle = target.dataset.handle as Handle | undefined;
    const boxId = target.closest<HTMLElement>("[data-box-id]")?.dataset.boxId;
    const suggestionId = target.closest<HTMLElement>("[data-suggestion-id]")?.dataset.suggestionId;
    if (suggestionId) {
      const s = suggestions.find((x) => x.id === suggestionId);
      if (s) onAcceptSuggestion?.(s);
      return;
    }
    const p = toNorm(e.clientX, e.clientY);
    viewport.current?.setPointerCapture(e.pointerId);
    if (handle && selected) {
      const orig = boxes.find((b) => b.id === selected);
      if (orig) setDrag({ kind: "resize", id: orig.id, handle, orig, box: orig });
      return;
    }
    if (boxId) {
      const orig = boxes.find((b) => b.id === boxId);
      setSelected(boxId);
      if (orig) setDrag({ kind: "move", id: boxId, sx: p.x, sy: p.y, orig, moved: false });
      return;
    }
    setSelected(null);
    setDrag({
      kind: "draw",
      sx: p.x,
      sy: p.y,
      box: { id: newId(), class_id: activeClassId, x1: p.x, y1: p.y, x2: p.x, y2: p.y, origin: "human" },
    });
  }

  function onPointerMove(e: React.PointerEvent) {
    if (!drag) return;
    if (drag.kind === "pan") {
      if (zoom > 1) setPan({ x: drag.px + e.clientX - drag.cx, y: drag.py + e.clientY - drag.cy });
      return;
    }
    const p = toNorm(e.clientX, e.clientY);
    if (drag.kind === "draw") {
      setDrag({ ...drag, box: { ...drag.box, x2: p.x, y2: p.y } });
    } else if (drag.kind === "move") {
      const o = drag.orig;
      const dx = clamp(p.x - drag.sx, -o.x1, 1 - o.x2);
      const dy = clamp(p.y - drag.sy, -o.y1, 1 - o.y2);
      setMovePreview({ ...o, x1: o.x1 + dx, x2: o.x2 + dx, y1: o.y1 + dy, y2: o.y2 + dy });
      if (!drag.moved && (Math.abs(dx) > 0.001 || Math.abs(dy) > 0.001)) setDrag({ ...drag, moved: true });
    } else if (drag.kind === "resize") {
      const b = { ...drag.orig };
      if (drag.handle.includes("w")) b.x1 = p.x;
      if (drag.handle.includes("e")) b.x2 = p.x;
      if (drag.handle.includes("n")) b.y1 = p.y;
      if (drag.handle.includes("s")) b.y2 = p.y;
      setDrag({ ...drag, box: b });
    }
  }

  function onPointerUp() {
    if (!drag) return;
    if (drag.kind === "draw") {
      const b = norm(drag.box);
      if (b.x2 - b.x1 >= minW && b.y2 - b.y1 >= minH) {
        commit((prev) => [...prev, b]);
        setSelected(b.id);
      }
    } else if (drag.kind === "resize") {
      const b = norm(drag.box);
      if (b.x2 - b.x1 >= minW && b.y2 - b.y1 >= minH) commit((prev) => prev.map((x) => (x.id === b.id ? { ...b, origin: "human" } : x)));
    } else if (drag.kind === "move" && movePreview && drag.moved) {
      commit((prev) => prev.map((x) => (x.id === movePreview.id ? { ...movePreview, origin: "human" } : x)));
    }
    setMovePreview(null);
    setDrag(null);
  }

  function onWheel(e: React.WheelEvent) {
    const r = viewport.current!.getBoundingClientRect();
    const cx = e.clientX - r.left;
    const cy = e.clientY - r.top;
    const next = clamp(zoom * (e.deltaY < 0 ? 1.15 : 1 / 1.15), 1, MAX_ZOOM);
    if (next === zoom) return;
    setPan({ x: cx - ((cx - offset.x) * next) / zoom, y: cy - ((cy - offset.y) * next) / zoom });
    setZoom(next);
  }

  // Page scroll must not fight wheel-zoom inside the canvas
  useEffect(() => {
    const el = viewport.current;
    if (!el) return;
    const prevent = (e: WheelEvent) => e.preventDefault();
    el.addEventListener("wheel", prevent, { passive: false });
    return () => el.removeEventListener("wheel", prevent);
  }, []);

  function zoomBy(factor: number) {
    const next = clamp(zoom * factor, 1, MAX_ZOOM);
    if (next === 1) return resetView();
    const cx = view.w / 2;
    const cy = view.h / 2;
    setPan({ x: cx - ((cx - offset.x) * next) / zoom, y: cy - ((cy - offset.y) * next) / zoom });
    setZoom(next);
  }

  const setClass = useCallback(
    (classId: number) => {
      onActiveClassChange(classId);
      if (selected && !readOnly) commit((prev) => prev.map((b) => (b.id === selected ? { ...b, class_id: classId, origin: "human" } : b)));
    },
    [selected, readOnly, commit, onActiveClassChange],
  );

  const removeBox = useCallback(
    (id: string) => {
      commit((prev) => prev.filter((b) => b.id !== id));
      setSelected((s) => (s === id ? null : s));
    },
    [commit],
  );

  useEffect(() => {
    const isTyping = (t: EventTarget | null) => t instanceof HTMLElement && (t.isContentEditable || ["INPUT", "TEXTAREA", "SELECT"].includes(t.tagName));
    const down = (e: KeyboardEvent) => {
      if (isTyping(e.target)) return;
      if (e.code === "Space") {
        spaceDown.current = true;
        if (e.target === viewport.current) e.preventDefault();
        return;
      }
      if (readOnly) return;
      const mod = e.ctrlKey || e.metaKey;
      if (mod && e.key.toLowerCase() === "z") {
        e.preventDefault();
        if (e.shiftKey) redo();
        else undo();
      } else if (mod && e.key.toLowerCase() === "y") {
        e.preventDefault();
        redo();
      } else if ((e.key === "Delete" || e.key === "Backspace") && selected) {
        e.preventDefault();
        removeBox(selected);
      } else if (e.key === "Escape") {
        setSelected(null);
      } else if (!mod && KEYS.includes(e.key)) {
        const cls = keyed[KEYS.indexOf(e.key)];
        if (cls) setClass(cls.class_id);
      } else if (selected && e.key.startsWith("Arrow")) {
        e.preventDefault();
        const step = (e.shiftKey ? 10 : 1) / width;
        const stepY = (e.shiftKey ? 10 : 1) / height;
        const dx = e.key === "ArrowLeft" ? -step : e.key === "ArrowRight" ? step : 0;
        const dy = e.key === "ArrowUp" ? -stepY : e.key === "ArrowDown" ? stepY : 0;
        commit((prev) =>
          prev.map((b) => {
            if (b.id !== selected) return b;
            const mx = clamp(dx, -b.x1, 1 - b.x2);
            const my = clamp(dy, -b.y1, 1 - b.y2);
            return { ...b, x1: b.x1 + mx, x2: b.x2 + mx, y1: b.y1 + my, y2: b.y2 + my, origin: "human" };
          }),
        );
      }
    };
    const up = (e: KeyboardEvent) => {
      if (e.code === "Space") spaceDown.current = false;
    };
    window.addEventListener("keydown", down);
    window.addEventListener("keyup", up);
    return () => {
      window.removeEventListener("keydown", down);
      window.removeEventListener("keyup", up);
    };
  }, [readOnly, selected, keyed, undo, redo, commit, removeBox, setClass, width, height]);

  const shown = movePreview ? rendered.map((b) => (b.id === movePreview.id ? movePreview : b)) : rendered;
  const inv = 1 / zoom;
  const selectedBox = shown.find((b) => b.id === selected);

  return (
    <div className="grid grid-cols-1 gap-4 xl:grid-cols-[minmax(0,1fr)_280px]">
      <div className="min-w-0">
        <div className="mb-2 flex flex-wrap items-center gap-1.5" role="toolbar" aria-label="Canvas tools">
          <button type="button" className="btn btn-sm" aria-label="Zoom out" onClick={() => zoomBy(1 / 1.4)} disabled={zoom <= 1}>
            <Minus className="size-4" aria-hidden />
          </button>
          <span className="tabular w-12 text-center text-xs text-ink-2">{Math.round(zoom * 100)}%</span>
          <button type="button" className="btn btn-sm" aria-label="Zoom in" onClick={() => zoomBy(1.4)} disabled={zoom >= MAX_ZOOM}>
            <Plus className="size-4" aria-hidden />
          </button>
          <button type="button" className="btn btn-sm" onClick={resetView} aria-label="Fit image">
            <Maximize className="size-4" aria-hidden />
          </button>
          <span className="mx-1 h-5 w-px bg-line" aria-hidden />
          {!readOnly && (
            <>
              <button type="button" className="btn btn-sm" onClick={undo} disabled={!canUndo} aria-label="Undo (Ctrl+Z)">
                <Undo2 className="size-4" aria-hidden />
              </button>
              <button type="button" className="btn btn-sm" onClick={redo} disabled={!canRedo} aria-label="Redo (Ctrl+Shift+Z)">
                <Redo2 className="size-4" aria-hidden />
              </button>
            </>
          )}
          <button type="button" className="btn btn-sm" onClick={() => setShowLabels((s) => !s)} aria-pressed={!showLabels}>
            {showLabels ? <EyeOff className="size-4" aria-hidden /> : <Eye className="size-4" aria-hidden />}
            {showLabels ? "Hide names" : "Show names"}
          </button>
          <span className="ml-auto hidden text-xs text-ink-3 md:inline">
            {readOnly ? "Drag to pan · scroll to zoom" : "Drag to draw · Space+drag to pan · scroll to zoom"}
          </span>
        </div>

        <div
          ref={viewport}
          tabIndex={0}
          aria-label="Annotation canvas"
          className={`relative h-[min(68vh,720px)] min-h-[320px] touch-none overflow-hidden rounded-md border border-line bg-[#0f1216] outline-none focus-visible:ring-3 focus-visible:ring-accent-200 ${
            drag?.kind === "pan" ? "cursor-grabbing" : readOnly ? "cursor-grab" : "cursor-crosshair"
          }`}
          onPointerDown={onPointerDown}
          onPointerMove={onPointerMove}
          onPointerUp={onPointerUp}
          onPointerCancel={onPointerUp}
          onWheel={onWheel}
          onContextMenu={(e) => e.preventDefault()}
        >
          <div
            ref={stage}
            className="absolute top-0 left-0 origin-top-left select-none"
            style={{ width: fit.w, height: fit.h, transform: `translate(${offset.x}px, ${offset.y}px) scale(${zoom})` }}
          >
            {/* eslint-disable-next-line @next/next/no-img-element -- authenticated API image */}
            <img
              src={imageUrl}
              alt="Frame being annotated"
              draggable={false}
              className="pointer-events-none block h-full w-full"
              onLoad={() => setLoaded(true)}
              onError={() => setImgError(true)}
            />
            {loaded &&
              suggestions.map((s) => (
                <div
                  key={s.id}
                  data-suggestion-id={s.id}
                  title="Model suggestion: click to accept"
                  className="absolute cursor-copy"
                  style={{
                    left: `${s.x1 * 100}%`,
                    top: `${s.y1 * 100}%`,
                    width: `${(s.x2 - s.x1) * 100}%`,
                    height: `${(s.y2 - s.y1) * 100}%`,
                    outline: `${1.5 * inv}px solid ${classById.get(s.class_id)?.is_violation ? VIOLATION : COMPLIANT}`,
                    opacity: 0.55,
                    background: "rgba(255,255,255,0.06)",
                  }}
                />
              ))}
            {loaded &&
              shown.map((b) => {
                const cls = classById.get(b.class_id);
                const color = cls?.is_violation ? VIOLATION : COMPLIANT;
                const isSel = b.id === selected;
                return (
                  <div
                    key={b.id}
                    data-box-id={b.id}
                    className={readOnly ? "absolute" : "absolute cursor-move"}
                    style={{
                      left: `${b.x1 * 100}%`,
                      top: `${b.y1 * 100}%`,
                      width: `${(b.x2 - b.x1) * 100}%`,
                      height: `${(b.y2 - b.y1) * 100}%`,
                      boxShadow: `0 0 0 ${(isSel ? 2.5 : 2) * inv}px ${color}${isSel ? `, 0 0 0 ${4.5 * inv}px rgba(255,255,255,0.85)` : ""}`,
                      background: isSel ? `${color}22` : "transparent",
                    }}
                  >
                    {showLabels && (
                      <span
                        className="pointer-events-none absolute bottom-full left-0 origin-bottom-left whitespace-nowrap rounded-t-[3px] px-1 text-[11px] leading-4 font-medium text-white"
                        style={{ background: color, transform: `scale(${inv})`, marginLeft: -2 * inv }}
                      >
                        {cls?.name ?? `Class ${b.class_id}`}
                        {b.origin === "model" && b.conf != null ? ` · ${Math.round(b.conf * 100)}%` : ""}
                      </span>
                    )}
                    {isSel &&
                      !readOnly &&
                      HANDLES.map((h) => (
                        <span
                          key={h}
                          data-handle={h}
                          className="absolute rounded-[2px] border border-[#0f1216] bg-white"
                          style={{
                            width: 9 * inv,
                            height: 9 * inv,
                            left: h.includes("w") ? 0 : h.includes("e") ? "100%" : "50%",
                            top: h.includes("n") ? 0 : h.includes("s") ? "100%" : "50%",
                            transform: "translate(-50%, -50%)",
                            cursor: `${h}-resize`,
                          }}
                        />
                      ))}
                  </div>
                );
              })}
          </div>
          {imgError && <p className="absolute inset-0 flex items-center justify-center text-sm text-white/70">The image couldn&apos;t be loaded.</p>}
        </div>
        {selectedBox && (
          <p className="mt-2 text-xs text-ink-3">
            Selected: <span className="font-medium text-ink">{classById.get(selectedBox.class_id)?.name}</span> ·{" "}
            {Math.round((selectedBox.x2 - selectedBox.x1) * width)}×{Math.round((selectedBox.y2 - selectedBox.y1) * height)} px
            {!readOnly && " · press a number to change its class, Delete to remove, arrows to nudge"}
          </p>
        )}
      </div>

      <aside className="grid content-start gap-4">
        <section>
          <h3 className="eyebrow mb-2">Class for new boxes{selected && !readOnly ? " · applies to the selected box" : ""}</h3>
          <ul className="grid gap-1">
            {classes
              .filter((c) => c.enabled)
              .map((c) => {
                const key = KEYS[keyed.findIndex((k) => k.class_id === c.class_id)];
                const active = c.class_id === activeClassId;
                return (
                  <li key={c.class_id}>
                    <button
                      type="button"
                      disabled={readOnly}
                      onClick={() => setClass(c.class_id)}
                      aria-pressed={active}
                      className={`flex w-full items-center gap-2 rounded-md border px-2.5 py-1.5 text-left text-[13px] transition ${
                        active ? "border-accent-200 bg-accent-50 text-accent-700" : "border-transparent hover:bg-surface-3"
                      }`}
                    >
                      <span className="size-2.5 shrink-0 rounded-sm" style={{ background: c.is_violation ? VIOLATION : COMPLIANT }} aria-hidden />
                      <span className="flex-1 truncate">{c.name}</span>
                      {key && <kbd className="tabular rounded border border-line bg-surface px-1 text-[10px] text-ink-3">{key}</kbd>}
                    </button>
                  </li>
                );
              })}
          </ul>
        </section>

        <section>
          <h3 className="eyebrow mb-2">Boxes in this frame ({boxes.length})</h3>
          {boxes.length === 0 ? (
            <p className="text-xs text-ink-3">No boxes. Saving with none marks the frame as background (nothing to detect).</p>
          ) : (
            <ul className="grid max-h-64 gap-0.5 overflow-y-auto">
              {boxes.map((b) => {
                const cls = classById.get(b.class_id);
                return (
                  <li key={b.id} className={`flex items-center gap-2 rounded-md px-2 py-1 text-[13px] ${b.id === selected ? "bg-accent-50" : "hover:bg-surface-3"}`}>
                    <span className="size-2.5 shrink-0 rounded-sm" style={{ background: cls?.is_violation ? VIOLATION : COMPLIANT }} aria-hidden />
                    <button type="button" className="flex-1 truncate text-left" onClick={() => setSelected(b.id)}>
                      {cls?.name ?? b.class_id}
                      <span className="ml-1 text-xs text-ink-3">{b.origin === "model" ? `model${b.conf != null ? ` ${Math.round(b.conf * 100)}%` : ""}` : "edited"}</span>
                    </button>
                    {!readOnly && (
                      <button type="button" className="text-ink-3 hover:text-critical" aria-label={`Delete ${cls?.name ?? "box"}`} onClick={() => removeBox(b.id)}>
                        <Trash2 className="size-3.5" aria-hidden />
                      </button>
                    )}
                  </li>
                );
              })}
            </ul>
          )}
        </section>

        {suggestions.length > 0 && !readOnly && (
          <section>
            <h3 className="eyebrow mb-1">Low-confidence suggestions ({suggestions.length})</h3>
            <p className="mb-2 text-xs text-ink-3">Faint boxes on the image. Click one to add it, then correct its class if needed.</p>
            <button
              type="button"
              className="btn btn-sm w-full"
              onClick={() => suggestions.forEach((s) => onAcceptSuggestion?.(s))}
            >
              Add all suggestions
            </button>
          </section>
        )}
      </aside>
    </div>
  );
}
