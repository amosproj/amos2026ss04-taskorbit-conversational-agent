/**
 * Canvas-rendered audio waveform driven by `useMicRecorder`'s levels
 * ref. Reads the ref every animation frame so the parent component
 * doesn't have to re-render on each tick.
 */

import { useEffect, useRef } from "react";

import { cn } from "@/lib/utils";

type Props = {
  /** Live frequency-bin amplitudes (0–255). Read on every frame. */
  levelsRef: React.MutableRefObject<Uint8Array>;
  /** Whether the mic is currently active — drives the idle baseline. */
  active: boolean;
  className?: string;
};

const BAR_GAP = 2;
const MIN_HEIGHT = 2;

export function Waveform({ levelsRef, active, className }: Props) {
  const canvasRef = useRef<HTMLCanvasElement>(null);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext("2d");
    if (!ctx) return;

    let raf = 0;
    let cancelled = false;

    const draw = () => {
      if (cancelled) return;
      const dpr = window.devicePixelRatio || 1;
      const cssWidth = canvas.clientWidth;
      const cssHeight = canvas.clientHeight;
      if (canvas.width !== cssWidth * dpr || canvas.height !== cssHeight * dpr) {
        canvas.width = cssWidth * dpr;
        canvas.height = cssHeight * dpr;
        ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      }

      ctx.clearRect(0, 0, cssWidth, cssHeight);

      const levels = levelsRef.current;
      const total = levels.length;
      if (total === 0) {
        raf = requestAnimationFrame(draw);
        return;
      }

      const barWidth = (cssWidth - (total - 1) * BAR_GAP) / total;
      const center = cssHeight / 2;

      // Hue derived from CSS variable so the waveform matches theme.
      const fill = active
        ? "var(--primary, oklch(0.6 0.18 270))"
        : "var(--muted-foreground, oklch(0.6 0.02 240))";
      ctx.fillStyle = fill;

      for (let i = 0; i < total; i++) {
        const value = levels[i] ?? 0;
        const intensity = active ? value / 255 : 0.05;
        const height = Math.max(MIN_HEIGHT, intensity * (cssHeight * 0.9));
        const x = i * (barWidth + BAR_GAP);
        const y = center - height / 2;
        ctx.fillRect(x, y, barWidth, height);
      }

      raf = requestAnimationFrame(draw);
    };

    raf = requestAnimationFrame(draw);
    return () => {
      cancelled = true;
      cancelAnimationFrame(raf);
    };
  }, [active, levelsRef]);

  return (
    <canvas
      ref={canvasRef}
      aria-hidden
      className={cn("h-8 w-full", className)}
    />
  );
}
