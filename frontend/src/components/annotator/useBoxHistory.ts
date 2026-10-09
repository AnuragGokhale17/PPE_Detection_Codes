"use client";

import { useCallback, useState } from "react";

import type { Box } from "./types";

const LIMIT = 200;

/** Box list with undo/redo. Every commit is one undo step (a whole drag is one commit). */
export function useBoxHistory(initial: Box[]) {
  const [state, setState] = useState({ past: [] as Box[][], present: initial, future: [] as Box[][] });

  const commit = useCallback((next: Box[] | ((prev: Box[]) => Box[])) => {
    setState((s) => {
      const value = typeof next === "function" ? next(s.present) : next;
      if (value === s.present) return s;
      return { past: [...s.past.slice(-LIMIT + 1), s.present], present: value, future: [] };
    });
  }, []);

  const undo = useCallback(() => {
    setState((s) => (s.past.length ? { past: s.past.slice(0, -1), present: s.past[s.past.length - 1], future: [s.present, ...s.future] } : s));
  }, []);

  const redo = useCallback(() => {
    setState((s) => (s.future.length ? { past: [...s.past, s.present], present: s.future[0], future: s.future.slice(1) } : s));
  }, []);

  /** Replace without history (e.g. after loading from the server). */
  const reset = useCallback((value: Box[]) => setState({ past: [], present: value, future: [] }), []);

  return {
    boxes: state.present,
    commit,
    undo,
    redo,
    reset,
    canUndo: state.past.length > 0,
    canRedo: state.future.length > 0,
  };
}
