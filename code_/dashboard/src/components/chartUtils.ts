import { useEffect, useRef, useState, type KeyboardEvent, type PointerEvent } from "react";

export type Series = {
  key: string;
  label: string;
  /** CSS custom property holding the series color, e.g. "var(--series-1)". */
  color: string;
  values: (number | null)[];
  /** Short name drawn at the end of a line; defaults to `label`. */
  endLabel?: string;
};

export const PLOT_HEIGHT = 180;
export const AXIS_BAND = 26; // room under the plot for x-axis labels
export const MARGIN = { top: 10, right: 12, left: 52 };

/** Round a maximum up to a clean axis top and return evenly spaced ticks from zero. */
export function niceTicks(max: number, count = 4): number[] {
  if (!(max > 0)) return [0, 1];
  const rough = max / count;
  const magnitude = 10 ** Math.floor(Math.log10(rough));
  const step = [1, 2, 2.5, 5, 10].map((m) => m * magnitude).find((s) => s >= rough) ?? 10 * magnitude;
  const ticks: number[] = [];
  for (let value = 0; value <= max + step * 1e-9; value += step) ticks.push(value);
  if (ticks[ticks.length - 1] < max) ticks.push(ticks[ticks.length - 1] + step);
  return ticks;
}

/** Indices of at most `max` evenly spaced x labels, always including the last point. */
export function labelIndices(length: number, max: number): number[] {
  if (length <= max) return Array.from({ length }, (_, i) => i);
  const step = Math.ceil((length - 1) / (max - 1));
  const indices: number[] = [];
  for (let i = length - 1; i >= 0; i -= step) indices.unshift(i);
  return indices;
}

/** Track an element's rendered width so SVG charts can be drawn at 1:1 pixels. */
export function useElementWidth<T extends HTMLElement>() {
  const ref = useRef<T | null>(null);
  const [width, setWidth] = useState(0);
  useEffect(() => {
    const node = ref.current;
    if (!node) return;
    const observer = new ResizeObserver(([entry]) => setWidth(Math.floor(entry.contentRect.width)));
    observer.observe(node);
    return () => observer.disconnect();
  }, []);
  return [ref, width] as const;
}

/**
 * Hover and keyboard focus for the x position of a chart. The pointer snaps to the nearest
 * point; arrow keys move between points so the tooltip is reachable without a mouse.
 */
export function useActiveIndex(length: number, xOf: (index: number) => number) {
  const [active, setActive] = useState<number | null>(null);

  function nearest(x: number) {
    let best = 0;
    for (let i = 1; i < length; i++) {
      if (Math.abs(xOf(i) - x) < Math.abs(xOf(best) - x)) best = i;
    }
    return best;
  }

  return {
    active: active !== null && active < length ? active : null,
    handlers: {
      onPointerMove(event: PointerEvent<SVGSVGElement>) {
        if (length === 0) return;
        const bounds = event.currentTarget.getBoundingClientRect();
        setActive(nearest(event.clientX - bounds.left));
      },
      onPointerLeave() {
        setActive(null);
      },
      onFocus() {
        if (length > 0) setActive((current) => current ?? length - 1);
      },
      onBlur() {
        setActive(null);
      },
      onKeyDown(event: KeyboardEvent<SVGSVGElement>) {
        if (length === 0) return;
        const moves: Record<string, number> = { ArrowLeft: -1, ArrowRight: 1 };
        if (event.key in moves) {
          event.preventDefault();
          setActive((current) => Math.min(length - 1, Math.max(0, (current ?? length - 1) + moves[event.key])));
        } else if (event.key === "Home" || event.key === "End") {
          event.preventDefault();
          setActive(event.key === "Home" ? 0 : length - 1);
        }
      },
    },
  };
}
