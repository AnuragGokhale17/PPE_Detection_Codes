export interface ClassInfo {
  class_id: number;
  name: string;
  is_violation: boolean;
  enabled: boolean;
}

/** Normalised YOLO box as the API sends and receives it. */
export interface Label {
  class_id: number;
  cx: number;
  cy: number;
  w: number;
  h: number;
  origin: "model" | "human";
  conf?: number | null;
}

/** Editor box: corners are easier to drag than centres. All values 0..1. */
export interface Box {
  id: string;
  class_id: number;
  x1: number;
  y1: number;
  x2: number;
  y2: number;
  origin: "model" | "human";
  conf?: number | null;
}

let seq = 0;
export const newId = () => `b${Date.now().toString(36)}${(seq++).toString(36)}`;

export function toBox(l: Label): Box {
  return {
    id: newId(),
    class_id: l.class_id,
    x1: l.cx - l.w / 2,
    y1: l.cy - l.h / 2,
    x2: l.cx + l.w / 2,
    y2: l.cy + l.h / 2,
    origin: l.origin,
    conf: l.conf ?? null,
  };
}

export function toLabel(b: Box): Label {
  const x1 = Math.max(0, Math.min(b.x1, b.x2));
  const x2 = Math.min(1, Math.max(b.x1, b.x2));
  const y1 = Math.max(0, Math.min(b.y1, b.y2));
  const y2 = Math.min(1, Math.max(b.y1, b.y2));
  return { class_id: b.class_id, cx: (x1 + x2) / 2, cy: (y1 + y2) / 2, w: x2 - x1, h: y2 - y1, origin: b.origin, conf: b.conf ?? null };
}

export function sameLabels(a: Box[], b: Box[]): boolean {
  if (a.length !== b.length) return false;
  const key = (x: Box) => `${x.class_id}:${x.x1.toFixed(4)}:${x.y1.toFixed(4)}:${x.x2.toFixed(4)}:${x.y2.toFixed(4)}`;
  const sa = a.map(key).sort();
  const sb = b.map(key).sort();
  return sa.every((k, i) => k === sb[i]);
}
