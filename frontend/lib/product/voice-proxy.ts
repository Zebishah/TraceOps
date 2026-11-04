/** Private voice response handling; only the speech route may return WAV bytes. */
export const MAX_SPEECH_RESPONSE_BYTES = 4 * 1024 * 1024;
const uuid = '[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}';
const speechPath = new RegExp(`^organizations/${uuid}/voice/speech$`);

export function isVoiceSpeechPath(path: string): boolean {
  return speechPath.test(path);
}

export async function proxyVoiceSpeechResponse(upstream: Response): Promise<Response> {
  const failure = () => Response.json(
    { detail: 'The voice service returned invalid audio.' },
    { status: 502, headers: { 'Cache-Control': 'no-store' } },
  );
  if (upstream.status !== 200 ||
      upstream.headers.get('content-type')?.split(';')[0].trim().toLowerCase() !== 'audio/wav' ||
      !upstream.body) {
    await upstream.body?.cancel();
    return failure();
  }
  const declared = upstream.headers.get('content-length');
  if (declared !== null && (!/^\d+$/.test(declared) ||
      !Number.isSafeInteger(Number(declared)) || Number(declared) > MAX_SPEECH_RESPONSE_BYTES)) {
    await upstream.body.cancel();
    return failure();
  }
  const reader = upstream.body.getReader();
  const chunks: Uint8Array[] = [];
  let size = 0;
  try {
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      size += value.byteLength;
      if (size > MAX_SPEECH_RESPONSE_BYTES) {
        await reader.cancel();
        return failure();
      }
      chunks.push(value);
    }
  } finally {
    reader.releaseLock();
  }
  const bytes = new Uint8Array(size);
  let offset = 0;
  for (const chunk of chunks) { bytes.set(chunk, offset); offset += chunk.byteLength; }
  if (size < 12 ||
      String.fromCharCode(...bytes.subarray(0, 4)) !== 'RIFF' ||
      String.fromCharCode(...bytes.subarray(8, 12)) !== 'WAVE') return failure();
  const headers = new Headers({
    'Content-Type': 'audio/wav',
    'Cache-Control': 'no-store',
    'X-Content-Type-Options': 'nosniff',
    'Content-Disposition': 'inline; filename="opspilot-speech.wav"',
  });
  for (const key of ['retry-after', 'x-request-id']) {
    const value = upstream.headers.get(key);
    if (value) headers.set(key, value);
  }
  return new Response(bytes, { status: 200, headers });
}
