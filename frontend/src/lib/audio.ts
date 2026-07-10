// PCM16 mono @ 24kHz is the exact wire format app/voice.py expects/produces
// (see backend/app/voice.py's module docstring) — encode mic input and
// decode playback audio to/from that format here so the rest of the app
// only ever deals with plain Float32 samples and base64 strings.
const TARGET_SAMPLE_RATE = 24000

export function resampleTo24k(input: Float32Array, inputSampleRate: number): Float32Array {
  if (inputSampleRate === TARGET_SAMPLE_RATE) return input
  const ratio = inputSampleRate / TARGET_SAMPLE_RATE
  const outputLength = Math.max(1, Math.round(input.length / ratio))
  const output = new Float32Array(outputLength)
  for (let i = 0; i < outputLength; i++) {
    const srcIndex = i * ratio
    const indexFloor = Math.floor(srcIndex)
    const indexCeil = Math.min(indexFloor + 1, input.length - 1)
    const frac = srcIndex - indexFloor
    output[i] = input[indexFloor] * (1 - frac) + input[indexCeil] * frac
  }
  return output
}

export function floatTo16BitPCM(input: Float32Array): Int16Array {
  const output = new Int16Array(input.length)
  for (let i = 0; i < input.length; i++) {
    const s = Math.max(-1, Math.min(1, input[i]))
    output[i] = s < 0 ? s * 0x8000 : s * 0x7fff
  }
  return output
}

export function float32FromInt16(data: Int16Array): Float32Array {
  const output = new Float32Array(data.length)
  for (let i = 0; i < data.length; i++) {
    const s = data[i]
    output[i] = s < 0 ? s / 0x8000 : s / 0x7fff
  }
  return output
}

export function base64FromInt16(data: Int16Array): string {
  const bytes = new Uint8Array(data.buffer, data.byteOffset, data.byteLength)
  let binary = ''
  for (let i = 0; i < bytes.length; i++) binary += String.fromCharCode(bytes[i])
  return btoa(binary)
}

export function int16FromBase64(base64: string): Int16Array {
  const binary = atob(base64)
  const bytes = new Uint8Array(binary.length)
  for (let i = 0; i < binary.length; i++) bytes[i] = binary.charCodeAt(i)
  // Copy into a freshly-aligned buffer: `bytes.buffer` may not be 2-byte
  // aligned at the right offset for an Int16Array view.
  return new Int16Array(bytes.buffer, bytes.byteOffset, bytes.byteLength / 2)
}

/** Resample a captured mic chunk to 24kHz PCM16 and base64-encode it for
 * the `{"type": "audio", "audio": ...}` browser->server message. */
export function encodeMicChunk(float32: Float32Array, inputSampleRate: number): string {
  const resampled = resampleTo24k(float32, inputSampleRate)
  return base64FromInt16(floatTo16BitPCM(resampled))
}

/** Root-mean-square amplitude of a Float32 sample block, roughly in [0, 1]
 * for normal speech levels — used to drive the voice-reactive orb. */
export function rms(samples: Float32Array): number {
  let sum = 0
  for (let i = 0; i < samples.length; i++) sum += samples[i] * samples[i]
  return Math.sqrt(sum / Math.max(1, samples.length))
}

export function concatInt16(chunks: Int16Array[]): Int16Array {
  const total = chunks.reduce((sum, c) => sum + c.length, 0)
  const out = new Int16Array(total)
  let offset = 0
  for (const chunk of chunks) {
    out.set(chunk, offset)
    offset += chunk.length
  }
  return out
}

export { TARGET_SAMPLE_RATE }
