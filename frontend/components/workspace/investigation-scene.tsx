'use client';

import { useEffect, useRef, useState } from 'react';
import { Activity, BookOpen, Database, Fingerprint, Layers3, Pause, Play, ShieldCheck } from 'lucide-react';
import type { Job } from '@/lib/product/contracts';
import './investigation-scene.css';

type Particle = { x: number; y: number; z: number; size: number };
const particleCount = 132;
const sphere: Particle[] = Array.from({ length: particleCount }, (_, index) => {
  const y = 1 - (index / (particleCount - 1)) * 2;
  const radius = Math.sqrt(1 - y * y);
  const angle = index * Math.PI * (3 - Math.sqrt(5));
  return { x: Math.cos(angle) * radius, y, z: Math.sin(angle) * radius, size: index % 5 === 0 ? 1.8 : 1 };
});

/** A decorative signal field. It does not represent agent traces or measured activity. */
function SignalField({ animate }: { animate: boolean }) {
  const canvas = useRef<HTMLCanvasElement>(null);
  useEffect(() => {
    const element = canvas.current;
    const context = element?.getContext('2d');
    if (!element || !context) return;
    const reduced = window.matchMedia('(prefers-reduced-motion: reduce)');
    let frame = 0;
    let width = 0;
    let height = 0;
    let phase = 0;
    let last = 0;
    let visible = true;
    let previousTimestamp = 0;
    let disposed = false;

    function draw(time: number) {
      if (!context || !width || !height) return;
      context.clearRect(0, 0, width, height);
      const centerX = width * .5;
      const centerY = height * .5;
      const radius = Math.min(width * .32, height * .33, 126);
      const glow = context.createRadialGradient(centerX, centerY, 0, centerX, centerY, radius * 1.7);
      glow.addColorStop(0, 'rgba(212,180,126,.11)');
      glow.addColorStop(.5, 'rgba(212,180,126,.045)');
      glow.addColorStop(1, 'rgba(212,180,126,0)');
      context.fillStyle = glow;
      context.fillRect(0, 0, width, height);
      const points = sphere.map((point, index) => {
        const x = point.x * Math.cos(time) - point.z * Math.sin(time);
        const z = point.x * Math.sin(time) + point.z * Math.cos(time);
        const y = point.y * Math.cos(.22) - z * Math.sin(.22);
        const depth = point.y * Math.sin(.22) + z * Math.cos(.22);
        const scale = 1 + depth * .16;
        const ripple = 1 + Math.sin(index * .4 + time * 2) * .025;
        return { x: centerX + x * radius * scale * ripple, y: centerY + y * radius * scale * ripple, depth, size: point.size };
      });
      // A fixed mesh bounds drawing work; there is no all-pairs particle search.
      for (let index = 0; index < points.length; index++) {
        for (const step of [8, 13]) {
          const point = points[index];
          const other = points[(index + step) % points.length];
          if (Math.hypot(point.x - other.x, point.y - other.y) > radius * .65) continue;
          context.beginPath();
          context.moveTo(point.x, point.y);
          context.lineTo(other.x, other.y);
          context.strokeStyle = `rgba(212,180,126,${.025 + ((point.depth + 1) / 2) * .12})`;
          context.lineWidth = .6;
          context.stroke();
        }
      }
      points.sort((a, b) => a.depth - b.depth).forEach(point => {
        context.beginPath();
        context.arc(point.x, point.y, point.size * (1 + point.depth * .2), 0, Math.PI * 2);
        context.fillStyle = `rgba(231,209,169,${.18 + ((point.depth + 1) / 2) * .72})`;
        context.fill();
      });
      for (let index = 0; index < 19; index++) {
        const drift = time * (index % 2 === 0 ? 12 : -9);
        const x = ((index * 97.3 + drift) % width + width) % width;
        const y = (index * 61.7 + Math.sin(time + index) * 12) % height;
        context.beginPath();context.arc(x, y, index % 4 === 0 ? 1.2 : .6, 0, Math.PI * 2);
        context.fillStyle = 'rgba(212,180,126,.24)';context.fill();
      }
    }

    function permitted() { return animate && !reduced.matches && !document.hidden && visible; }
    function tick(timestamp: number) {
      frame = 0;
      if (disposed || !permitted()) return;
      if (timestamp - last >= 1000 / 30) {
        phase += previousTimestamp ? Math.min(timestamp - previousTimestamp, 60) * .00013 : 0;
        previousTimestamp = timestamp;
        last = timestamp;
        draw(phase);
      }
      frame = requestAnimationFrame(tick);
    }
    function sync() {
      if (frame) cancelAnimationFrame(frame);
      frame = 0;previousTimestamp = 0;
      draw(phase);
      if (!disposed && permitted()) frame = requestAnimationFrame(tick);
    }
    const resize = new ResizeObserver(entries => {
      const box = entries[0]?.contentRect;
      if (!box) return;
      width = box.width;height = box.height;
      const resolution = Math.min(window.devicePixelRatio || 1, 1.5);
      element.width = Math.round(width * resolution);element.height = Math.round(height * resolution);
      context.setTransform(resolution, 0, 0, resolution, 0, 0);
      sync();
    });
    const intersection = new IntersectionObserver(entries => { visible = entries[0]?.isIntersecting ?? false; sync(); });
    resize.observe(element);intersection.observe(element);
    reduced.addEventListener('change', sync);document.addEventListener('visibilitychange', sync);
    return () => {
      disposed = true;if (frame) cancelAnimationFrame(frame);
      resize.disconnect();intersection.disconnect();reduced.removeEventListener('change', sync);document.removeEventListener('visibilitychange', sync);
    };
  }, [animate]);
  return <canvas ref={canvas} className="signal-field" aria-hidden="true" />;
}

export function InvestigationScene({ job }: { job?: Job | null }) {
  const [motion, setMotion] = useState(true);
  const queued = job?.status === 'queued';
  const processing = job?.status === 'processing';
  const failed = job?.status === 'failed';
  const completed = job?.status === 'succeeded';
  const active = queued || processing;
  const animate = active && motion;
  const heading = queued ? ['Your report.', 'A new perspective.'] : processing ? ['Connecting context.', 'Building clarity.'] : failed ? ['A signal needs', 'your attention.'] : completed ? ['Worker complete.', 'A saved result to review.'] : ['Every signal.', 'A clearer decision.'];
  return <section className={`intelligence-canvas ${active ? 'is-active' : ''} ${animate ? 'motion-on' : ''} ${failed ? 'has-failed' : ''}`} aria-label="AI investigation workspace">
    <div className="canvas-noise" aria-hidden="true" />
    <header className="canvas-header"><span><Fingerprint size={15} /> OPSPILOT / INVESTIGATION ENGINE</span><div><span className={`canvas-state ${active ? 'active' : ''}`}><i />{queued ? 'Queued' : processing ? 'Processing' : failed ? 'Needs attention' : completed ? 'Worker completed' : 'Ready to investigate'}</span>{active && <button type="button" className="motion-toggle" onClick={() => setMotion(value => !value)} aria-label={motion ? 'Pause visual motion' : 'Resume visual motion'}>{motion ? <Pause size={13} /> : <Play size={13} />}</button>}</div></header>
    <div className="canvas-main"><div className="canvas-narrative"><span className="canvas-overline">EVIDENCE. REASONING. HUMAN CONTROL.</span><h2>{heading[0]}<br /><em>{heading[1]}</em></h2><p>{queued ? 'Your incident is saved and waiting for a background worker. The investigation will connect company knowledge with the available operational records.' : processing ? 'The background investigation is running. Its saved findings, source evidence, and recommended next step will appear here when ready.' : failed ? 'The worker could not finish this run. Inspect the recorded error and retry the investigation when the underlying issue is resolved.' : completed ? 'The worker has finished this investigation. Its saved result and supporting records are available according to your workspace permissions.' : 'Bring policy, operational records, and relevant history into one investigation. Review the evidence before deciding what happens next.'}</p><div className="canvas-context-tags"><span><BookOpen size={12} /> Company policy</span><span><Database size={12} /> Operational records</span><span><Layers3 size={12} /> Incident memory</span></div></div>
      <div className="canvas-visual" aria-hidden="true"><SignalField animate={animate} /><div className="canvas-orbit orbit-one" /><div className="canvas-orbit orbit-two" /><div className="canvas-core"><Fingerprint size={29} /></div><span className="visual-coordinate coordinate-top">CONTEXT / INTELLIGENCE</span><span className="visual-coordinate coordinate-bottom">GROUNDED IN YOUR WORKSPACE</span><span className="canvas-satellite satellite-a"><BookOpen size={13} /><span>Knowledge</span></span><span className="canvas-satellite satellite-b"><Database size={13} /><span>Records</span></span><span className="canvas-satellite satellite-c"><ShieldCheck size={13} /><span>Human review</span></span><svg className="canvas-signal-paths" viewBox="0 0 500 350" preserveAspectRatio="none"><path d="M84 100C160 100 130 175 250 175M420 135C340 135 365 175 250 175M370 280C325 280 340 175 250 175" /><path className="signal-travel" d="M84 100C160 100 130 175 250 175M420 135C340 135 365 175 250 175M370 280C325 280 340 175 250 175" /></svg></div>
    </div>
    <footer className="canvas-runtime"><div className="runtime-status"><Activity size={16} /><div><small>RECORDED JOB STATE</small><strong>{queued ? 'Waiting for an available worker' : processing ? 'Background worker processing' : failed ? 'Worker reported a failure' : completed ? 'Worker completed successfully' : 'Start the investigation when ready'}</strong></div></div>{job && <div className="runtime-progress"><div><span>Worker progress</span><strong>{job.progress_percent}%</strong></div><progress value={job.progress_percent} max={100} aria-label="Worker-reported investigation progress" /></div>}<div className="runtime-guardrail"><ShieldCheck size={14} /><span>Human approval<br /><strong>for sensitive actions</strong></span></div></footer>
    <div className="canvas-meta"><span>{job ? `RUN / ${job.id}` : 'DURABLE BACKGROUND INVESTIGATION'}</span><span>Signal animation is illustrative · progress comes from the worker</span></div>
  </section>;
}
