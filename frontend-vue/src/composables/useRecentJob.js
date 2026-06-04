const RECENT_JOB_KEY = 'ai-video-factory:recent-job-id'

export function setRecentJob(jobId) {
  if (!jobId) return
  localStorage.setItem(RECENT_JOB_KEY, String(jobId))
}

export function getRecentJob() {
  return localStorage.getItem(RECENT_JOB_KEY) || ''
}

export function clearRecentJob(jobId = '') {
  const current = getRecentJob()
  if (!jobId || current === String(jobId)) {
    localStorage.removeItem(RECENT_JOB_KEY)
  }
}
