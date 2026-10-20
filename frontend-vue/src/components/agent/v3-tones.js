// Presentation-only colour mapping for v3 panels; never used for authorization.
const GOOD = new Set(['success', 'completed', 'applied', 'reviewed'])
const BAD = new Set(['failed', 'cancelled', 'rejected', 'invalid', 'limit'])
const WAIT = new Set(['awaiting_input', 'awaiting_plan_review', 'awaiting_gate', 'awaiting_result_review', 'attention',
  'returned', 'stale', 'blocked', 'awaiting_approval', 'awaiting_review', 'review_pending', 'proposed', 'partial_success'])
const BUSY = new Set(['understanding', 'executing', 'delivering', 'running', 'waiting_children'])

export function statusTone(status) {
  if (GOOD.has(status)) return 'emerald'
  if (BAD.has(status)) return 'red'
  if (WAIT.has(status)) return 'amber'
  if (BUSY.has(status)) return 'blue'
  return 'slate'
}

export const isBusy = (status) => BUSY.has(status)

const AGENT_TONES = { producer: 'blue', director: 'violet', creative: 'amber', research: 'teal',
  prompt_smith: 'sky', critic: 'rose', repair: 'orange' }
export const agentTone = (agent) => AGENT_TONES[agent] || 'slate'
