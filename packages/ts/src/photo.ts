import { InvalidInputError } from './errors.js'
import { LIMITS } from './generated/contract.js'

/** Largest decoded photo the contract accepts, in bytes (LIMITS.imageMaxMiB MiB). */
export const IMAGE_MAX_BYTES: number = LIMITS.imageMaxMiB * 1024 * 1024

const DATA_URL_PREFIX = /^data:image\/[A-Za-z0-9.+-]+;base64,/

/** Photo given as Base64 (optionally with a data:image/…;base64, prefix), as raw bytes, or as a file path (Node only). */
export type PhotoSource =
  | { image_base64: string; image?: never; file?: never }
  | { image: Uint8Array | ArrayBuffer | Blob; image_base64?: never; file?: never }
  | { file: string; image_base64?: never; image?: never }

/** Decoded size of a Base64 string, computed from its length (like the API does before decoding). */
export function decodedBase64Bytes(b64: string): number {
  const s = b64.replace(DATA_URL_PREFIX, '').replace(/\s+/g, '')
  const padding = s.endsWith('==') ? 2 : s.endsWith('=') ? 1 : 0
  return Math.floor((s.length * 3) / 4) - padding
}

function tooLarge(bytes: number): InvalidInputError {
  return new InvalidInputError(
    `The photo has ${bytes} bytes; the API accepts at most ${LIMITS.imageMaxMiB} MiB (${IMAGE_MAX_BYTES} bytes) before Base64 encoding. Nothing was sent.`,
  )
}

/** Base64 without line breaks; uses Buffer in Node and btoa elsewhere. */
export function bytesToBase64(bytes: Uint8Array): string {
  const B = (globalThis as { Buffer?: { from(b: Uint8Array): { toString(enc: string): string } } }).Buffer
  if (B) return B.from(bytes).toString('base64')
  let bin = ''
  const CHUNK = 0x8000
  for (let i = 0; i < bytes.length; i += CHUNK) bin += String.fromCharCode(...bytes.subarray(i, i + CHUNK))
  return btoa(bin)
}

async function readFileNode(path: string): Promise<Uint8Array> {
  /* Loaded on demand and through a variable, so browser bundles never pull in node:fs. */
  const spec = 'node:fs/promises'
  let fs: { stat(p: string): Promise<{ size: number }>; readFile(p: string): Promise<Uint8Array> }
  try {
    fs = (await import(/* @vite-ignore */ spec)) as typeof fs
  } catch {
    throw new InvalidInputError('file is only supported in Node; in browsers pass image (Blob, File, Uint8Array or ArrayBuffer).')
  }
  const { size } = await fs.stat(path)
  if (size > IMAGE_MAX_BYTES) throw tooLarge(size)
  return fs.readFile(path)
}

/** Turns any PhotoSource into image_base64 and enforces the contract's size limit before anything is sent. */
export async function toImageBase64(src: PhotoSource): Promise<string> {
  const given = [src.image_base64 !== undefined, src.image !== undefined, src.file !== undefined].filter(Boolean).length
  if (given !== 1) throw new InvalidInputError('Pass exactly one of image_base64, image or file.')
  if (src.image_base64 !== undefined) {
    if (typeof src.image_base64 !== 'string' || src.image_base64.length === 0) throw new InvalidInputError('image_base64 must be a non-empty string.')
    const size = decodedBase64Bytes(src.image_base64)
    if (size > IMAGE_MAX_BYTES) throw tooLarge(size)
    return src.image_base64
  }
  let bytes: Uint8Array
  if (src.file !== undefined) {
    bytes = await readFileNode(src.file)
  } else {
    const img = src.image
    if (typeof Blob !== 'undefined' && img instanceof Blob) {
      if (img.size > IMAGE_MAX_BYTES) throw tooLarge(img.size)
      bytes = new Uint8Array(await img.arrayBuffer())
    } else if (img instanceof ArrayBuffer) {
      bytes = new Uint8Array(img)
    } else if (img instanceof Uint8Array) {
      bytes = img
    } else {
      throw new InvalidInputError('image must be a Uint8Array, ArrayBuffer or Blob.')
    }
  }
  if (bytes.byteLength === 0) throw new InvalidInputError('The photo is empty.')
  if (bytes.byteLength > IMAGE_MAX_BYTES) throw tooLarge(bytes.byteLength)
  return bytesToBase64(bytes)
}
