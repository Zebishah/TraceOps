'use client';

import { useEffect, useRef } from 'react';

type Particle = { x: number; y: number; z: number; size: number };
const particleCount = 132;
const sphere: Particle[] = Array.from({ length: particleCount }, (_, index) => {
  const y = 1 - (index / (particleCount - 1)) * 2;
  const radius = Math.sqrt(1 - y * y);
  const angle = index * Math.PI * (3 - Math.sqrt(5));
  return { x: Math.cos(angle) * radius, y, z: Math.sin(angle) * radius, size: index % 5 === 0 ? 1.8 : 1 };
});
const tiltCos = Math.cos(.22);
const tiltSin = Math.sin(.22);
const lineColors = ['#d4b47e15', '#d4b47e25', '#d4b47e37', '#d4b47e50'];
const pointColors = ['#e7d1a951', '#e7d1a97a', '#e7d1a9ac', '#e7d1a9e0'];
const tau = Math.PI * 2;

/** Decorative motion only. Backend progress is displayed separately from this field. */
export function SignalField({ animate }: { animate: boolean }) {
  const canvas = useRef<HTMLCanvasElement>(null);
  const synchronize = useRef<(() => void) | null>(null);
  const enabled = useRef(animate);
  useEffect(() => {
    enabled.current = animate;
    synchronize.current?.();
  }, [animate]);

  useEffect(() => {
    const element = canvas.current;
    const context = element?.getContext('2d');
    if (!element || !context) return;
    const reduced = window.matchMedia('(prefers-reduced-motion: reduce)');
    // Reuse projection storage and paint styles; no objects, sorting, gradients,
    // or per-edge canvas strokes are created in the animation loop.
    const x = new Float32Array(particleCount);
    const y = new Float32Array(particleCount);
    const depth = new Float32Array(particleCount);
    const buckets = new Uint8Array(particleCount);
    let frame = 0;
    let width = 0;
    let height = 0;
    let phase = 0;
    let previousTimestamp: number | null = null;
    let visible = true;
    let disposed = false;
    let glow: CanvasGradient | null = null;

    function draw(time: number) {
      if (!context || !width || !height) return;
      context.clearRect(0, 0, width, height);
      const centerX = width * .5;
      const centerY = height * .5;
      const radius = Math.min(width * .32, height * .33, 150);
      if (glow) {
        context.fillStyle = glow;
        context.fillRect(0, 0, width, height);
      }
      const cos = Math.cos(time);
      const sin = Math.sin(time);
      for (let i = 0; i < particleCount; i++) {
        const point = sphere[i];
        const rotatedX = point.x * cos - point.z * sin;
        const rotatedZ = point.x * sin + point.z * cos;
        depth[i] = point.y * tiltSin + rotatedZ * tiltCos;
        const scale = 1 + depth[i] * .16;
        const ripple = 1 + Math.sin(i * .4 + time * 2) * .025;
        x[i] = centerX + rotatedX * radius * scale * ripple;
        y[i] = centerY + (point.y * tiltCos - rotatedZ * tiltSin) * radius * scale * ripple;
        buckets[i] = Math.min(3, Math.max(0, Math.floor((depth[i] + 1) * 2)));
      }
      const maxDistanceSquared = radius * radius * .4225;
      context.lineWidth = .65;
      // Four depth batches replace hundreds of individual stroke/fill calls.
      for (let bucket = 0; bucket < 4; bucket++) {
        context.beginPath();
        for (let i = 0; i < particleCount; i++) {
          if (buckets[i] !== bucket) continue;
          for (let step = 8; step <= 13; step += 5) {
            const other = (i + step) % particleCount;
            const dx = x[i] - x[other];
            const dy = y[i] - y[other];
            if (dx * dx + dy * dy > maxDistanceSquared) continue;
            context.moveTo(x[i], y[i]);
            context.lineTo(x[other], y[other]);
          }
        }
        context.strokeStyle = lineColors[bucket];
        context.stroke();
        context.beginPath();
        for (let i = 0; i < particleCount; i++) {
          if (buckets[i] !== bucket) continue;
          const size = sphere[i].size * (1 + depth[i] * .2);
          context.moveTo(x[i] + size, y[i]);
          context.arc(x[i], y[i], size, 0, tau);
        }
        context.fillStyle = pointColors[bucket];
        context.fill();
      }
      context.beginPath();
      for (let i = 0; i < 19; i++) {
        const drift = time * (i % 2 === 0 ? 16 : -12);
        const px = ((i * 97.3 + drift) % width + width) % width;
        const py = (i * 61.7 + Math.sin(time + i) * 16) % height;
        const size = i % 4 === 0 ? 1.2 : .65;
        context.moveTo(px + size, py);
        context.arc(px, py, size, 0, tau);
      }
      context.fillStyle = '#d4b47e65';
      context.fill();
      // Moving signal packets give the whole map visible motion at a modest cost.
      for (let packet = 0; packet < 3; packet++) {
        const angle = time * 1.6 + packet * tau / 3;
        for (let tail = 0; tail < 5; tail++) {
          const position = angle - tail * .026;
          const px = centerX + Math.cos(position) * width * .34;
          const py = centerY + Math.sin(position) * height * .35;
          context.globalAlpha = (1 - tail / 5) * .85;
          context.beginPath();
          context.arc(px, py, tail === 0 ? 2 : 1.1, 0, tau);
          context.fillStyle = '#ead2a3';
          context.fill();
        }
      }
      context.globalAlpha = 1;
    }

    function permitted() { return enabled.current && !reduced.matches && !document.hidden && visible; }
    function tick(timestamp: number) {
      frame = 0;
      if (disposed || !permitted()) return;
      // Every display frame, at the same speed on 60/120/144 Hz screens.
      // A long task cannot produce a large jump on the next frame.
      if (previousTimestamp !== null) phase += Math.min(timestamp - previousTimestamp, 64) * .00042;
      previousTimestamp = timestamp;
      draw(phase);
      frame = requestAnimationFrame(tick);
    }
    function sync() {
      if (frame) cancelAnimationFrame(frame);
      frame = 0;
      previousTimestamp = null;
      draw(phase);
      if (!disposed && permitted()) frame = requestAnimationFrame(tick);
    }
    synchronize.current = sync;
    const resize = new ResizeObserver(entries => {
      const box = entries[0]?.contentRect;
      if (!box || (box.width === width && box.height === height)) return;
      width = box.width;
      height = box.height;
      const resolution = Math.min(window.devicePixelRatio || 1, 1.5);
      element.width = Math.round(width * resolution);
      element.height = Math.round(height * resolution);
      context.setTransform(resolution, 0, 0, resolution, 0, 0);
      const radius = Math.min(width * .32, height * .33, 150);
      glow = context.createRadialGradient(width * .5, height * .5, 0, width * .5, height * .5, radius * 1.7);
      glow.addColorStop(0, '#d4b47e2e');
      glow.addColorStop(.5, '#d4b47e0b');
      glow.addColorStop(1, '#d4b47e00');
      sync();
    });
    const intersection = new IntersectionObserver(entries => { visible = entries[0]?.isIntersecting ?? false; sync(); });
    resize.observe(element);
    intersection.observe(element);
    reduced.addEventListener('change', sync);
    document.addEventListener('visibilitychange', sync);
    return () => {
      disposed = true;
      synchronize.current = null;
      if (frame) cancelAnimationFrame(frame);
      resize.disconnect();
      intersection.disconnect();
      reduced.removeEventListener('change', sync);
      document.removeEventListener('visibilitychange', sync);
    };
  }, []);
  return <canvas ref={canvas} className="signal-field" aria-hidden="true" />;
}
