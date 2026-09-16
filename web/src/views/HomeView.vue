<template>
  <div>
    <div class="mb-8">
      <h1 class="text-3xl font-bold text-slate-900 mb-2">聊天来源</h1>
      <p class="text-slate-500">先选择电脑，再查看这台电脑同步过来的聊天列表</p>
    </div>

    <div v-if="ingest" class="mb-8 bg-white rounded-2xl border border-slate-200 p-5">
      <div class="text-sm font-medium text-slate-900 mb-2">远端同步助手</div>
      <p class="text-sm text-slate-500 mb-3">
        把 <code class="bg-slate-100 px-1 rounded">WeComSyncAgent.exe</code> 装到对方电脑。
        助手会默认填写服务器地址并自动获取令牌，勾选群聊/单聊后同步到这里。
      </p>
      <div class="grid md:grid-cols-2 gap-3 text-sm">
        <div>
          <div class="text-xs text-slate-400 mb-1">服务器地址</div>
          <div class="flex flex-wrap gap-2">
            <code
              v-for="url in ingest.urls"
              :key="url"
              class="bg-slate-100 px-2 py-1 rounded"
            >{{ url }}</code>
          </div>
        </div>
        <div>
          <div class="text-xs text-slate-400 mb-1">同步令牌</div>
          <code class="bg-slate-100 px-2 py-1 rounded break-all">{{ ingest.token }}</code>
        </div>
      </div>
    </div>

    <div v-if="loading" class="flex items-center justify-center py-20">
      <div class="animate-spin rounded-full h-8 w-8 border-b-2 border-primary-600"></div>
    </div>

    <div v-else-if="!selectedSource" class="grid grid-cols-1 md:grid-cols-3 gap-6">
      <div
        v-for="source in sources"
        :key="source.id"
        class="bg-white rounded-2xl border border-slate-200 p-6 hover:shadow-xl hover:border-primary-200 transition-all cursor-pointer"
        @click="selectSource(source)"
      >
        <div class="flex items-center gap-4 mb-4">
          <div class="w-14 h-14 rounded-2xl bg-primary-50 flex items-center justify-center text-2xl">
            {{ source.kind === 'remote' ? '🖥️' : '💻' }}
          </div>
          <div class="min-w-0">
            <div class="flex items-center gap-2 min-w-0">
              <h3 class="text-lg font-semibold text-slate-900 truncate">{{ sourceTitle(source) }}</h3>
              <span
                v-if="isOnline(source)"
                class="inline-flex items-center gap-1 shrink-0 text-sm font-medium text-emerald-600"
              >
                <span class="w-1.5 h-1.5 rounded-full bg-emerald-500 animate-pulse"></span>
                在线
              </span>
            </div>
            <p class="text-xs text-slate-500 mt-1">{{ sourceSubtitle(source) }}</p>
          </div>
        </div>
        <p class="text-sm text-slate-500 mb-2">{{ source.session_count }} 个会话</p>
        <p class="text-xs text-slate-400">最近同步：{{ source.last_sync || '—' }}</p>
      </div>
      <div v-if="!sources.length" class="col-span-full py-16 text-center text-slate-400">
        还没有电脑数据。请在远端运行同步助手，或先在本机解密企业微信。
      </div>
    </div>

    <div v-else>
      <div class="flex items-center justify-between mb-4">
        <h2 class="text-xl font-semibold text-slate-900 flex items-center gap-2">
          <span>{{ sourceTitle(selectedSource) }}</span>
          <span
            v-if="isOnline(selectedSource)"
            class="inline-flex items-center gap-1 text-sm font-medium text-emerald-600"
          >
            <span class="w-1.5 h-1.5 rounded-full bg-emerald-500 animate-pulse"></span>
            在线
          </span>
          <span class="text-slate-400 font-normal">- 会话列表</span>
        </h2>
        <button @click="selectedSource = null" class="text-sm text-slate-500 hover:text-slate-700">
          返回电脑列表
        </button>
      </div>

      <div v-if="sessionsLoading" class="flex items-center justify-center py-10">
        <div class="animate-spin rounded-full h-6 w-6 border-b-2 border-primary-600"></div>
      </div>

      <div v-else class="bg-white rounded-2xl border border-slate-200 overflow-hidden">
        <div class="divide-y divide-slate-100">
          <div
            v-for="session in sessions"
            :key="session.username"
            class="flex items-center gap-4 px-6 py-4 hover:bg-slate-50 cursor-pointer transition-colors"
            @click="openChat(session)"
          >
            <div class="w-10 h-10 rounded-full bg-gradient-to-br from-primary-400 to-primary-600 flex items-center justify-center text-white text-sm font-medium shrink-0">
              {{ (session.display_name || session.username).charAt(0) }}
            </div>
            <div class="flex-1 min-w-0">
              <div class="flex items-center gap-2">
                <span class="font-medium text-slate-900 truncate">{{ session.display_name || session.username }}</span>
                <span v-if="session.msg_count" class="text-xs text-slate-400">{{ session.msg_count }} 条</span>
                <span
                  v-if="isFreshSync(session)"
                  class="text-[11px] px-1.5 py-0.5 rounded-full bg-primary-50 text-primary-700"
                >最新同步</span>
              </div>
              <p class="text-sm text-slate-500 truncate mt-0.5">{{ session.summary || session.username }}</p>
            </div>
            <div class="text-right shrink-0">
              <div v-if="session.synced_at" class="text-xs text-emerald-600">{{ session.synced_at }} 同步</div>
              <span class="text-xs text-slate-400">{{ session.last_time }}</span>
            </div>
          </div>
        </div>
        <div v-if="!sessions.length" class="py-10 text-center text-slate-400">暂无会话数据</div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { inject, onMounted, onUnmounted, ref, type Ref } from 'vue'
import { useRouter } from 'vue-router'
import { chatApi, type Source, type Session, type IngestInfo, type PresenceClient } from '../api'

const router = useRouter()
const sources = ref<Source[]>([])
const sessions = ref<Session[]>([])
const selectedSource = ref<Source | null>(null)
const ingest = ref<IngestInfo | null>(null)
const loading = ref(true)
const sessionsLoading = ref(false)
const online = inject<Ref<PresenceClient[]>>('presenceOnline', ref([]))
let timer: ReturnType<typeof setInterval> | null = null

onMounted(async () => {
  await loadSources(true)
  timer = setInterval(() => loadSources(false), 8000)
  window.addEventListener('chatinsight-presence', onPresenceEvent)
})

onUnmounted(() => {
  if (timer) clearInterval(timer)
  window.removeEventListener('chatinsight-presence', onPresenceEvent)
})

function onPresenceEvent() {
  loadSources(false)
}

async function loadSources(initial = false) {
  try {
    const [src, info] = await Promise.all([
      chatApi.getSources(),
      initial || !ingest.value ? chatApi.getIngestInfo() : Promise.resolve(null),
    ])
    sources.value = src.data
    if (info) ingest.value = info.data
    if (selectedSource.value) {
      const latest = sources.value.find((item) => item.id === selectedSource.value?.id)
      if (latest) selectedSource.value = latest
      await refreshSessions(false)
    }
  } catch (e) {
    console.error(e)
  } finally {
    if (initial) loading.value = false
  }
}

function sourceTitle(source: Source) {
  return source.operator_name || source.computer_name
}

function sourceSubtitle(source: Source) {
  if (source.operator_name && source.computer_name) {
    return `${source.computer_name} · ${sourceKindLabel(source)}`
  }
  return sourceKindLabel(source)
}

function sourceKindLabel(source: Source) {
  if (source.kind === 'remote') return '远端同步'
  if (source.kind === 'ssh') return 'SSH 直连'
  return '本机'
}

function isOnline(source: Source) {
  const list = online.value || []
  const computer = (source.computer_name || "").replace(/（本机）|（SSH）/g, "")
  return list.some((item) => {
    if (item.source_id && item.source_id === source.id) return true
    if (source.operator_name && item.operator_name && source.operator_name === item.operator_name) {
      return true
    }
    if (item.computer_name && computer && computer.includes(item.computer_name)) {
      return true
    }
    return false
  })
}

function isFreshSync(session: Session) {
  if (!session.synced_at) return false
  const newest = sessions.value[0]?.synced_at
  return Boolean(newest) && session.synced_at === newest
}

async function selectSource(source: Source) {
  selectedSource.value = source
  await refreshSessions(true)
}

async function refreshSessions(showLoading: boolean) {
  if (!selectedSource.value) return
  if (showLoading) sessionsLoading.value = true
  try {
    const { data } = await chatApi.getSourceSessions(selectedSource.value.id)
    sessions.value = data
  } catch (e) {
    console.error(e)
    if (showLoading) sessions.value = []
  } finally {
    sessionsLoading.value = false
  }
}

function openChat(session: Session) {
  if (!selectedSource.value) return
  router.push({
    name: 'chat',
    params: {
      sourceId: selectedSource.value.id,
      sessionId: session.username,
    },
  })
}
</script>
