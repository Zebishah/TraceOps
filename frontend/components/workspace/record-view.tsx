'use client';
import { dateValue } from '@/lib/product/contracts';
export function ReadableRecord({ value, depth = 0 }: { value: unknown; depth?: number }) {
  if (value === null || value === undefined) return <span className="record-null">Not recorded</span>;
  if (typeof value === 'boolean') return <span className={`record-boolean ${value ? 'true' : 'false'}`}>{value ? 'Yes' : 'No'}</span>;
  if (typeof value !== 'object') return <span className="record-text">{String(value).replaceAll('\\n', '\n')}</span>;
  if (depth > 5) return <p className="context-note">Further nested data is available from the API.</p>;
  if (Array.isArray(value)) return value.length ? <div className="record-array">{value.map((item, index) => <div key={index}><span className="record-array-index">{String(index + 1).padStart(2, '0')}</span><ReadableRecord value={item} depth={depth + 1} /></div>)}</div> : <span className="record-null">No records</span>;
  const entries = Object.entries(value);
  return <dl className="readable-record">{entries.map(([key, item]) => <div key={key}><dt>{key.replaceAll('_', ' ')}</dt><dd>{key.endsWith('_at') && typeof item === 'string' ? dateValue(item) : <ReadableRecord value={item} depth={depth + 1} />}</dd></div>)}</dl>;
}

export function ToolOutput({ content }: { content: string }) {
  let parsed: unknown;
  try { parsed = JSON.parse(content); } catch { return <p className="tool-text-output">{content}</p>; }
  return <ReadableRecord value={parsed} />;
}

