<template>
  <div class="min-h-screen bg-gradient-to-br from-slate-50 to-slate-100">
    <nav class="bg-white/80 backdrop-blur-sm border-b border-slate-200 sticky top-0 z-50">
      <div class="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
        <div class="flex items-center justify-between h-16">
          <router-link to="/" class="flex items-center gap-3">
            <div class="w-9 h-9 bg-gradient-to-br from-primary-500 to-primary-700 rounded-xl flex items-center justify-center shadow-lg shadow-primary-500/25">
              <svg class="w-5 h-5 text-white" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M8 12h.01M12 12h.01M16 12h.01M21 12c0 4.418-4.03 8-9 8a9.863 9.863 0 01-4.255-.949L3 20l1.395-3.72C3.512 15.042 3 13.574 3 12c0-4.418 4.03-8 9-8s9 3.582 9 8z" />
              </svg>
            </div>
            <span class="text-xl font-bold bg-gradient-to-r from-primary-600 to-primary-800 bg-clip-text text-transparent">
              ChatInsight
            </span>
          </router-link>
          <div class="flex items-center gap-4">
            <form class="hidden sm:flex items-center" @submit.prevent="goSearch">
              <input
                v-model="navQuery"
                type="search"
                placeholder="搜索聊天记录"
                class="w-56 text-sm border border-slate-200 rounded-lg px-3 py-1.5 focus:outline-none focus:ring-2 focus:ring-primary-500/20 focus:border-primary-500"
              />
            </form>
            <span class="text-sm text-slate-500">聊天记录分析</span>
          </div>
        </div>
      </div>
    </nav>
    <main class="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8">
      <router-view />
    </main>
    <div class="fixed bottom-4 right-4 z-[80] space-y-2 w-80 max-w-[calc(100vw-2rem)]">
      <div
        v-for="toast in toasts"
        :key="toast.id"
        class="bg-white shadow-xl rounded-2xl border border-slate-200 px-4 py-3"
      >
        <div class="text-sm font-semibold text-slate-900">{{ toast.title }}</div>
        <div class="text-sm text-slate-500 mt-0.5">{{ toast.message }}</div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { onMounted, onUnmounted, provide, ref } from 'vue'
import { useRouter } from 'vue-router'
import { chatApi, type PresenceClient, type PresenceAlert } from './api'

const router = useRouter()
const navQuery = ref('')

const online = ref<PresenceClient[]>([])
const toasts = ref<PresenceAlert[]>([])
const lastAlertId = ref(0)
let primed = false
let timer: ReturnType<typeof setInterval> | null = null

provide('presenceOnline', online)

onMounted(() => {
  if (typeof Notification !== 'undefined' && Notification.permission === 'default') {
    Notification.requestPermission().catch(() => undefined)
  }
  pollPresence()
  timer = setInterval(pollPresence, 4000)
})

onUnmounted(() => {
  if (timer) clearInterval(timer)
})

async function pollPresence() {
  try {
    const { data } = await chatApi.getPresence(lastAlertId.value)
    online.value = data.online || []
    const alerts = data.alerts || []
    window.dispatchEvent(new CustomEvent('chatinsight-presence', { detail: { online: online.value, alerts } }))
    if (!primed) {
      primed = true
      if (alerts.length) lastAlertId.value = Math.max(...alerts.map((item) => item.id))
      return
    }
    if (alerts.length) {
      lastAlertId.value = Math.max(...alerts.map((item) => item.id))
      for (const alert of alerts) {
        pushToast(alert)
        desktopNotify(alert)
      }
    }
  } catch (e) {
    console.error(e)
  }
}

function pushToast(alert: PresenceAlert) {
  toasts.value = [...toasts.value, alert].slice(-4)
  window.setTimeout(() => {
    toasts.value = toasts.value.filter((item) => item.id !== alert.id)
  }, 8000)
}

function desktopNotify(alert: PresenceAlert) {
  if (typeof Notification === 'undefined' || Notification.permission !== 'granted') return
  try {
    new Notification(alert.title, { body: alert.message })
  } catch {
    // ignore unsupported environments
  }
}

function goSearch() {
  const q = navQuery.value.trim()
  if (!q) return
  router.push({ name: 'search', query: { q } })
}
</script>
