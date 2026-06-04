<template>
  <div class="bg-[#0a0f1e] min-h-screen flex items-center justify-center overflow-hidden relative">
    <div class="glow-orb" style="width:400px;height:400px;background:rgba(99,102,241,0.12);top:-100px;left:-100px;"></div>
    <div class="glow-orb" style="width:500px;height:500px;background:rgba(59,130,246,0.10);bottom:-150px;right:-150px;"></div>
    <div class="glow-orb" style="width:250px;height:250px;background:rgba(139,92,246,0.08);top:40%;left:60%;"></div>

    <canvas ref="particlesCanvas" class="fixed inset-0 pointer-events-none z-0"></canvas>

    <div class="glass-card" style="width:440px;max-width:94vw;padding:44px 40px;position:relative;z-index:1;">
      <div style="text-align:center;margin-bottom:32px;">
        <div style="display:flex;align-items:center;justify-content:center;gap:10px;margin-bottom:8px;">
          <PhPlayCircle weight="fill" :size="28" color="#3b82f6" />
          <span style="font-size:22px;font-weight:700;color:#f1f5f9;">{{ t('app.title') }}</span>
        </div>
        <p style="color:#64748b;font-size:13px;">{{ t('app.subtitle') }}</p>
      </div>

      <div style="display:flex;justify-content:center;margin-bottom:28px;gap:8px;">
        <button
          class="tab-btn"
          :class="{ active: tab === 'login' }"
          @click="switchTab('login')"
        >{{ t('auth.login') }}</button>
        <button
          class="tab-btn"
          :class="{ active: tab === 'register' }"
          @click="switchTab('register')"
        >{{ t('auth.register') }}</button>
      </div>

      <div v-if="errorMsg" class="mb-4 rounded-lg px-4 py-2.5 text-sm" :class="errorType === 'success' ? 'bg-green-500/10 border border-green-500/20 text-green-400' : 'bg-red-500/10 border border-red-500/20 text-red-400'">
        {{ errorMsg }}
      </div>

      <form v-if="tab === 'login'" @submit.prevent="handleLogin" style="display:flex;flex-direction:column;gap:16px;">
        <div>
          <label style="color:#94a3b8;font-size:12px;font-weight:500;display:block;margin-bottom:6px;">{{ t('auth.username') }}</label>
          <input v-model="loginUsername" type="text" class="input-field" :placeholder="t('auth.enterUsername')" autocomplete="username" />
        </div>
        <div>
          <label style="color:#94a3b8;font-size:12px;font-weight:500;display:block;margin-bottom:6px;">{{ t('auth.password') }}</label>
          <input v-model="loginPassword" type="password" class="input-field" :placeholder="t('auth.enterPassword')" autocomplete="current-password" />
        </div>
        <button type="submit" class="btn-primary" :disabled="loading"> {{ loading ? t('auth.loading') : t('auth.login') }} </button>
      </form>

      <form v-else @submit.prevent="handleRegister" style="display:flex;flex-direction:column;gap:16px;">
        <div>
          <label style="color:#94a3b8;font-size:12px;font-weight:500;display:block;margin-bottom:6px;">{{ t('auth.username') }}</label>
          <input v-model="regUsername" type="text" class="input-field" :placeholder="t('auth.chooseUsername')" autocomplete="username" />
        </div>
        <div>
          <label style="color:#94a3b8;font-size:12px;font-weight:500;display:block;margin-bottom:6px;">{{ t('auth.email') }} <span style="color:#64748b;">({{ t('auth.emailOptional') }})</span></label>
          <input v-model="regEmail" type="email" class="input-field" :placeholder="t('auth.enterEmail')" autocomplete="email" />
        </div>
        <div>
          <label style="color:#94a3b8;font-size:12px;font-weight:500;display:block;margin-bottom:6px;">{{ t('auth.password') }}</label>
          <input v-model="regPassword" type="password" class="input-field" :placeholder="t('auth.minPassword')" autocomplete="new-password" />
        </div>
        <button type="submit" class="btn-primary" :disabled="loading"> {{ loading ? t('auth.loading') : t('auth.createAccount') }} </button>
      </form>

      <div style="margin-top:24px;padding-top:20px;border-top:1px solid rgba(255,255,255,0.06);">
        <div style="display:flex;align-items:center;justify-content:center;gap:8px;">
          <span style="width:8px;height:8px;border-radius:50%;display:inline-block;" :style="{ background: apiOnline ? '#22c55e' : '#ef4444' }"></span>
          <span style="color:#64748b;font-size:11px;">{{ apiOnline ? t('auth.apiConnected') : t('auth.apiUnavailable') }}</span>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, onMounted, onUnmounted } from 'vue'
import { useRouter } from 'vue-router'
import { useAuthStore } from '@/stores/auth'
import { PhPlayCircle } from '@phosphor-icons/vue'

import { useI18n } from 'vue-i18n'

const router = useRouter()
const authStore = useAuthStore()
const { t } = useI18n()

const tab = ref('login')
const loading = ref(false)
const errorMsg = ref('')
const errorType = ref('error')
const loginUsername = ref('')
const loginPassword = ref('')
const regUsername = ref('')
const regEmail = ref('')
const regPassword = ref('')
const apiOnline = ref(false)

const particlesCanvas = ref(null)

function switchTab(t) {
  tab.value = t
  errorMsg.value = ''
}

function showError(msg) { errorMsg.value = msg; errorType.value = 'error' }
function showSuccess(msg) { errorMsg.value = msg; errorType.value = 'success' }

async function handleLogin() {
  if (!loginUsername.value.trim() || !loginPassword.value) {
    showError(t('auth.invalidCredentials'))
    return
  }
  loading.value = true
  try {
    await authStore.login(loginUsername.value.trim(), loginPassword.value)
    showSuccess(t('auth.loginSuccess'))
    setTimeout(() => router.push('/dashboard'), 800)
  } catch (err) {
    showError(err.response?.data?.error?.message || err.message || t('auth.loginFailed'))
  } finally {
    loading.value = false
  }
}

async function handleRegister() {
  if (!regUsername.value.trim() || regUsername.value.trim().length < 2) {
    showError(t('auth.usernameMinLength'))
    return
  }
  if (!regPassword.value || regPassword.value.length < 6) {
    showError(t('auth.passwordMinLength'))
    return
  }
  loading.value = true
  try {
    await authStore.register(regUsername.value.trim(), regEmail.value.trim() || undefined, regPassword.value)
    showSuccess(t('auth.registerSuccess'))
    setTimeout(() => router.push('/dashboard'), 800)
  } catch (err) {
    showError(err.response?.data?.error?.message || err.message || t('auth.registerFailed'))
  } finally {
    loading.value = false
  }
}

async function checkHealth() {
  try {
    const res = await fetch('/api/health', { signal: AbortSignal.timeout(5000) })
    apiOnline.value = res.ok
  } catch {
    apiOnline.value = false
  }
}

// Particle animation
let animId
function initParticles() {
  const canvas = particlesCanvas.value
  if (!canvas) return
  const ctx = canvas.getContext('2d')
  const particles = []
  const count = 60

  function resize() {
    canvas.width = window.innerWidth
    canvas.height = window.innerHeight
  }
  resize()
  window.addEventListener('resize', resize)

  for (let i = 0; i < count; i++) {
    particles.push({
      x: Math.random() * canvas.width,
      y: Math.random() * canvas.height,
      vx: (Math.random() - 0.5) * 0.4,
      vy: (Math.random() - 0.5) * 0.4,
      r: Math.random() * 1.5 + 0.5,
      o: Math.random() * 0.5 + 0.1,
    })
  }

  function animate() {
    ctx.clearRect(0, 0, canvas.width, canvas.height)
    for (const p of particles) {
      p.x += p.vx
      p.y += p.vy
      if (p.x < -10) p.x = canvas.width + 10
      if (p.x > canvas.width + 10) p.x = -10
      if (p.y < -10) p.y = canvas.height + 10
      if (p.y > canvas.height + 10) p.y = -10
      ctx.beginPath()
      ctx.arc(p.x, p.y, p.r, 0, Math.PI * 2)
      ctx.fillStyle = `rgba(148, 163, 184, ${p.o})`
      ctx.fill()
    }
    for (let i = 0; i < particles.length; i++) {
      for (let j = i + 1; j < particles.length; j++) {
        const a = particles[i], b = particles[j]
        const dx = a.x - b.x, dy = a.y - b.y
        const dist = Math.sqrt(dx * dx + dy * dy)
        if (dist < 100) {
          ctx.beginPath()
          ctx.moveTo(a.x, a.y)
          ctx.lineTo(b.x, b.y)
          ctx.strokeStyle = `rgba(148, 163, 184, ${0.06 * (1 - dist / 100)})`
          ctx.stroke()
        }
      }
    }
    animId = requestAnimationFrame(animate)
  }
  animate()
}

onMounted(() => {
  checkHealth()
  initParticles()
})

onUnmounted(() => {
  if (animId) cancelAnimationFrame(animId)
})
</script>