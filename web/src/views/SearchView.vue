<template>
  <div>
    <div class="mb-6">
      <h1 class="text-3xl font-bold text-slate-900 mb-2">搜索聊天记录</h1>
      <p class="text-slate-500">在服务端检索已同步和本机解密的消息</p>
    </div>

    <form class="flex gap-2 mb-6" @submit.prevent="runSearch">
      <input
        v-model="query"
        type="search"
        autofocus
        placeholder="关键词，可空格组合，匹配消息、发送者、文件名"
        class="flex-1 text-sm border border-slate-200 rounded-lg px-3 py-2 focus:outline-none focus:ring-2 focus:ring-primary-500/20 focus:border-primary-500"
      />
      <button
        type="submit"
        class="text-sm bg-primary-600 text-white px-4 py-2 rounded-lg hover:bg-primary-700"
      >
        搜索
      </button>
    </form>

    <div v-if="scopeText" class="text-xs text-slate-400 mb-4">{{ scopeText }}</div>

    <div v-if="loading" class="flex items-center justify-center py-16">
      <div class="animate-spin rounded-full h-8 w-8 border-b-2 border-primary-600"></div>
    </div>

    <div v-else-if="errorText" class="py-16 text-center text-amber-700">{{ errorText }}</div>

    <div v-else-if="searched && !hits.length" class="py-16 text-center text-slate-400">
      没有匹配的消息
    </div>

    <div v-else class="bg-white rounded-2xl border border-slate-200 overflow-hidden">
      <div
        v-for="hit in hits"
        :key="`${hit.source_id}-${hit.session_id}-${hit.message_id}-${hit.time_text}`"
        class="px-6 py-4 border-b border-slate-100 last:border-b-0 hover:bg-slate-50 cursor-pointer"
        @click="openHit(hit)"
      >
        <div class="flex flex-wrap items-center gap-x-2 gap-y-1 text-xs text-slate-400 mb-1">
          <span class="text-slate-600 font-medium break-words">{{ hit.session_name }}</span>
          <span v-if="hit.source_name" class="break-words">· {{ hit.source_name }}</span>
          <span class="ml-auto">{{ hit.time_text }}</span>
        </div>
        <div class="text-sm text-slate-900 break-words">
          <span class="font-medium">{{ hit.sender || '未知' }}：</span>
          <span>{{ hit.snippet || hit.text || hit.attachment_name }}</span>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { apiErrorMessage, chatApi, type SearchHit } from '../api'

const route = useRoute()
const router = useRouter()
const query = ref('')
const hits = ref<SearchHit[]>([])
const loading = ref(false)
const searched = ref(false)
const errorText = ref('')

const sourceId = computed(() => String(route.query.source_id || ''))
const sessionId = computed(() => String(route.query.session_id || ''))

const scopeText = computed(() => {
  const parts = []
  if (sourceId.value) parts.push(`来源 ${sourceId.value}`)
  if (sessionId.value) parts.push(`会话 ${sessionId.value}`)
  return parts.join(' · ')
})

onMounted(() => {
  query.value = String(route.query.q || '')
  if (query.value.trim()) runSearch()
})

watch(() => route.query.q, (value) => {
  const next = String(value || '')
  if (next !== query.value) {
    query.value = next
    if (next.trim()) runSearch()
  }
})

async function runSearch() {
  const q = query.value.trim()
  if (!q) return
  loading.value = true
  searched.value = true
  errorText.value = ''
  router.replace({
    name: 'search',
    query: {
      q,
      ...(sourceId.value ? { source_id: sourceId.value } : {}),
      ...(sessionId.value ? { session_id: sessionId.value } : {}),
    },
  })
  try {
    const { data } = await chatApi.searchMessages({
      q,
      source_id: sourceId.value || undefined,
      session_id: sessionId.value || undefined,
      limit: 80,
    })
    hits.value = data
  } catch (e) {
    console.error(e)
    hits.value = []
    errorText.value = apiErrorMessage(e, '搜索失败')
  } finally {
    loading.value = false
  }
}

function openHit(hit: SearchHit) {
  router.push({
    name: 'chat',
    params: {
      sourceId: hit.source_id,
      sessionId: hit.session_id,
    },
    query: { name: hit.session_name || hit.session_id },
  })
}
</script>
