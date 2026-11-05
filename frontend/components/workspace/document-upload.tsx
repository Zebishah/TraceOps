'use client';

import { useRef, useState, type DragEvent, type FormEvent } from 'react';
import Link from 'next/link';
import { ArrowUpRight, Check, CloudUpload, FileText, LoaderCircle, Upload, X } from 'lucide-react';
import { Panel } from './ui';

type DocumentUploadProps = {
  file: File | null;
  busy: boolean;
  error: string;
  created: string;
  limitBytes: number;
  onSelect: (file: File | null) => void;
  onUpload: (event: FormEvent<HTMLFormElement>) => void;
};

function fileSize(bytes: number) {
  if (bytes === 0) return '0 B';
  return bytes < 1024 * 1024 ? `${Math.max(1, Math.ceil(bytes / 1024))} KB` : `${(bytes / 1024 / 1024).toFixed(1)} MB`;
}

export function DocumentUpload({ file, busy, error, created, limitBytes, onSelect, onUpload }: DocumentUploadProps) {
  const input = useRef<HTMLInputElement>(null);
  const [dragging, setDragging] = useState(false);
  const oversized = Boolean(file && file.size > limitBytes);
  const extension = file?.name.split('.').pop()?.toUpperCase();

  function choose() { input.current?.click(); }
  function reset() { onSelect(null); if (input.current) input.current.value = ''; }
  function drop(event: DragEvent<HTMLFormElement>) {
    event.preventDefault(); setDragging(false);
    if (busy) return;
    const selected = event.dataTransfer.files[0];
    if (selected) onSelect(selected);
  }

  return <Panel title="Add company knowledge">
    <form className={`upload-zone knowledge-upload${dragging ? ' is-dragging' : ''}${created ? ' is-uploaded' : ''}`} onSubmit={onUpload} aria-busy={busy}
      onDragOver={event => { event.preventDefault(); if (!busy) setDragging(true); }}
      onDragLeave={event => { if (!(event.relatedTarget instanceof Node) || !event.currentTarget.contains(event.relatedTarget)) setDragging(false); }}
      onDrop={drop}>
      <input ref={input} id="document-file" type="file" hidden disabled={busy} accept=".pdf,.txt,.md,.markdown,application/pdf,text/plain,text/markdown" aria-label="Choose a document" onChange={event => { const selected = event.target.files?.[0]; if (selected) onSelect(selected); event.target.value = ''; }} />
      {!file && <div className="knowledge-upload-icon" aria-hidden="true"><CloudUpload size={26} strokeWidth={1.5} /></div>}
      <div className="knowledge-upload-heading">
        <h3>{created ? 'Document uploaded' : busy ? 'Adding your document' : oversized ? 'Choose a smaller document' : file ? 'Ready to upload' : 'Bring your knowledge together'}</h3>
        <p>{created ? 'Your file is saved. Open it to review and start processing.' : busy ? 'Keep this page open while we add your file.' : oversized ? 'This file is larger than the upload limit.' : file ? 'Review your file, then add it to your workspace.' : 'Drop a document here, or choose a file to get started.'}</p>
      </div>
      {file && <div className="knowledge-file-card">
        <span className={`knowledge-file-icon${created ? ' is-complete' : ''}`} aria-hidden="true">{created ? <Check size={21} /> : <FileText size={22} strokeWidth={1.5} />}</span>
        <div className="knowledge-file-details"><strong>{file.name}</strong><span>{extension && extension !== file.name.toUpperCase() ? `${extension} document` : 'Document'}<i aria-hidden="true">·</i>{fileSize(file.size)}</span></div>
        {!busy && !created && <button type="button" className="knowledge-file-remove" aria-label={`Remove ${file.name}`} onClick={reset}><X size={16} /></button>}
      </div>}
      {busy && <div className="knowledge-upload-progress"><progress aria-label="Uploading document" /><span role="status">Uploading your document…</span></div>}
      {created && <p className="knowledge-upload-success" role="status"><Check size={14} aria-hidden="true" />Uploaded successfully</p>}
      {error && <p className="form-error knowledge-upload-error" role="alert">{error}</p>}
      <div className="knowledge-upload-actions">
        {created ? <><Link href={`/app/knowledge/${created}`} className="btn knowledge-upload-submit">Open document<ArrowUpRight size={16} aria-hidden="true" /></Link><button type="button" className="btn secondary" onClick={reset}>Upload another</button></> : file ? <><button type="submit" className="btn knowledge-upload-submit" disabled={busy || oversized}>{busy ? <LoaderCircle className="knowledge-upload-spinner" size={16} aria-hidden="true" /> : <Upload size={16} aria-hidden="true" />}{busy ? 'Uploading…' : 'Upload document'}</button><button type="button" className="btn secondary" disabled={busy} onClick={choose}>Change file</button></> : <button type="button" className="btn knowledge-upload-submit" onClick={choose}><Upload size={16} aria-hidden="true" />Choose document</button>}
      </div>
      {!created && <p className="knowledge-upload-formats">PDF, plain text, or Markdown<span aria-hidden="true">·</span>Up to {limitBytes / 1024 / 1024} MB</p>}
    </form>
  </Panel>;
}
