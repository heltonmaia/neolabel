import { FILES_BASE } from './env';

/**
 * Absolute URL for a frame image, cache-busted by `frame_rev` so a re-rendered
 * frame (e.g. after rotation) isn't served stale from the browser cache.
 * Returns null when the payload has no image_url.
 */
export function frameUrl(
  payload: { image_url?: string; frame_rev?: number } | undefined | null,
): string | null {
  const url = payload?.image_url;
  if (!url) return null;
  const full = `${FILES_BASE}${url}`;
  return payload?.frame_rev ? `${full}?r=${payload.frame_rev}` : full;
}
