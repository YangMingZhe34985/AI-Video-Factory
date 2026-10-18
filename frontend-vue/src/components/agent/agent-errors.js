// Localized text for server error codes shown in Agent review panels. Server
// messages can be English internals (e.g. budget scopes with Run IDs), so known
// codes use local copy and unknown ones fall back to the server message.
const TEXT = {
  zh: {
    BUDGET_EXCEEDED: '超出本次创作的预算上限，请缩小范围或新建预算更高的创作。',
    PRODUCTION_QUOTE_EXPIRED: '镜头、费用或计划已变化，请重新获取报价。',
    TRANSFORM_QUOTE_EXPIRED: '报价已过期，请重新报价后再确认。',
    TRANSFORM_INPUT_CHANGED: '素材在报价后发生变化，请重新报价。',
    PLAN_VERSION_CONFLICT: '计划已被更新，请刷新后再操作。',
    VIDEO_INCOMPLETE: '仍有缺失或未完成的视频，请先处理。',
    PREVIEW_INCOMPLETE: '仍有缺失、失败或过期的预览，请先处理。',
    PRODUCTION_DISABLED: '视频生产尚未开启。',
    DELIVERY_DISABLED: '本地成片交付尚未开启。',
    REPAIR_LIMIT_EXCEEDED: '已达到自动修复上限。',
  },
  en: {
    BUDGET_EXCEEDED: 'This exceeds the run budget. Reduce the scope or start a run with a higher budget.',
    PRODUCTION_QUOTE_EXPIRED: 'Shots, cost or plan changed. Request a new quote.',
    TRANSFORM_QUOTE_EXPIRED: 'The quote expired. Refresh it before approving.',
    TRANSFORM_INPUT_CHANGED: 'References changed after quoting. Refresh the quote.',
    PLAN_VERSION_CONFLICT: 'The plan was updated. Refresh and try again.',
    VIDEO_INCOMPLETE: 'Some videos are missing or unfinished.',
    PREVIEW_INCOMPLETE: 'Some previews are missing, failed or stale.',
    PRODUCTION_DISABLED: 'Video production is not enabled.',
    DELIVERY_DISABLED: 'Local delivery is not enabled.',
    REPAIR_LIMIT_EXCEEDED: 'The automatic repair limit was reached.',
  },
}

export function errorCode(error) {
  return error?.response?.data?.error?.code || null
}

// Local text for a known server code, or null so callers keep their fallback.
export function knownErrorText(error, locale = 'zh') {
  const table = TEXT[String(locale).startsWith('zh') ? 'zh' : 'en']
  const code = typeof error === 'string' ? error : errorCode(error)
  return (code && table[code]) || null
}
