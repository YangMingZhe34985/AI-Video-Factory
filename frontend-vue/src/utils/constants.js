export const BRANCH_COLORS = {
  core:              { bg: 'bg-blue-500',    border: 'border-blue-200',    light: 'bg-blue-50',    text: 'text-blue-600',    hex: '#3b82f6' },
  t2v:               { bg: 'bg-purple-500',  border: 'border-purple-200',  light: 'bg-purple-50',  text: 'text-purple-600',  hex: '#a855f7' },
  first_frame_image: { bg: 'bg-cyan-500',    border: 'border-cyan-200',    light: 'bg-cyan-50',    text: 'text-cyan-600',    hex: '#06b6d4' },
  r2v_flash:         { bg: 'bg-orange-500',  border: 'border-orange-200',  light: 'bg-orange-50',  text: 'text-orange-600',  hex: '#f97316' },
  i2v:               { bg: 'bg-emerald-500', border: 'border-emerald-200', light: 'bg-emerald-50', text: 'text-emerald-600', hex: '#10b981' },
  i2i_test:          { bg: 'bg-amber-500',   border: 'border-amber-200',   light: 'bg-amber-50',   text: 'text-amber-600',   hex: '#f59e0b' },
}

export const BRANCH_LABELS = {
  core:              'Core Path',
  t2v:               'T2V Branch',
  first_frame_image: 'First Frame',
  r2v_flash:         'R2V Flash',
  i2v:               'Main I2V',
  i2i_test:          'I2I Test',
}

export const NAV_ITEMS = [
  { to: '/dashboard', icon: 'PhSquaresFour', labelKey: 'nav.dashboard' },
  { to: '/templates', icon: 'PhFolder', labelKey: 'nav.templates' },
  { to: '/prompts', icon: 'PhChatText', labelKey: 'nav.prompts' },
  { to: '/models', icon: 'PhCube', labelKey: 'nav.models' },
  { to: '/jobs', icon: 'PhBriefcase', labelKey: 'nav.jobs' },
  { to: '/workflow', icon: 'PhGitMerge', labelKey: 'nav.workflow' },
  { to: '/artifacts', icon: 'PhImage', labelKey: 'nav.artifacts' },
  { to: '/settings', icon: 'PhGear', labelKey: 'nav.settings' },
]
