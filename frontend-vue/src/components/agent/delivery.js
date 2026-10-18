// Delivery is server-authoritative; these helpers never authorize generation.
export const deliveryRunStatuses = new Set(['editing', 'delivery_attention', 'success'])

export function deliveryAssetUrl(asset, kind = 'download') {
  if (!asset || !['preview', 'download'].includes(kind) || !/^[a-zA-Z0-9_-]{1,128}$/.test(asset.artifact_id || '')) return ''
  const expected = `/api/artifacts/${asset.artifact_id}/${kind}`
  return asset[`${kind}_url`] === expected ? expected : ''
}

export function deliveryReady(delivery) {
  return Boolean(delivery?.status === 'success' && delivery.stage === 'complete' && delivery.qc?.passed === true
    && deliveryAssetUrl(delivery.master, 'preview') && deliveryAssetUrl(delivery.master)
    && deliveryAssetUrl(delivery.package))
}

export function deliveryActionAllowed(delivery, action, disabled = false) {
  if (disabled || !delivery?.enabled || delivery.cost_credits !== 0
      || !Number.isInteger(delivery.plan_version) || delivery.plan_version < 1) return false
  return action === 'start_delivery' ? delivery.can_start === true
    : action === 'retry_delivery' && delivery.can_retry === true
}

export function buildDeliveryAction(delivery, action, disabled = false) {
  if (!deliveryActionAllowed(delivery, action, disabled)) throw new Error('DELIVERY_ACTION_UNAVAILABLE')
  return { action, payload: { plan_version: delivery.plan_version } }
}

export function deliveryChecks(delivery) {
  return (Array.isArray(delivery?.qc?.checks) ? delivery.qc.checks : []).filter((check) =>
    check && typeof check.code === 'string' && typeof check.summary === 'string')
}

export function deliveryKeptShots(keptDownstream) {
  return [...new Set((Array.isArray(keptDownstream) ? keptDownstream : [])
    .filter((shot) => typeof shot === 'string').map((shot) => shot.trim()).filter(Boolean))]
}

export function deliveryWarnings(delivery) {
  return [...new Set([...(delivery?.warnings || []), ...(delivery?.qc?.warnings || [])]
    .filter((warning) => typeof warning === 'string' && warning.trim()))]
}

export function downloadFilename(asset, fallback) {
  const name = typeof asset?.file_name === 'string' ? asset.file_name : fallback
  return name.replace(/[\\/:*?"<>|\x00-\x1f]/g, '_').slice(0, 180) || fallback
}
