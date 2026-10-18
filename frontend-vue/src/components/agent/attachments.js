// Accepted extensions are hints; the server owns format and media validation.
export const ATTACHMENT_ACCEPT = '.jpg,.jpeg,.png,.webp,.mp4,.mov,.mkv,.webm,.wav,.mp3,.txt,.md,.pdf'
const kinds = { image: /\.(jpg|jpeg|png|webp)$/i, video: /\.(mp4|mov|mkv|webm)$/i, audio: /\.(wav|mp3)$/i, file: /\.(txt|md|pdf)$/i }
export function attachmentKind(name) { return Object.entries(kinds).find(([, pattern]) => pattern.test(name || ''))?.[0] || null }
export function attachmentDescription(attachment) {
  const size = attachment.width && attachment.height ? `${attachment.width}×${attachment.height}` : ''
  const duration = Number.isFinite(attachment.duration) && attachment.duration > 0 ? `${Math.round(attachment.duration * 1000) / 1000}s` : ''
  const pages = Number.isInteger(attachment.page_count) && attachment.page_count > 0 ? `${attachment.page_count}p` : ''
  return [size, duration, pages].filter(Boolean).join(' · ')
}
export function composerReady(text, items, busy, budget) {
  return typeof text === 'string' && text.trim().length >= 2 && !busy
    && Number.isFinite(budget) && budget > 0 && items.every((item) => item.done && !item.error)
}
