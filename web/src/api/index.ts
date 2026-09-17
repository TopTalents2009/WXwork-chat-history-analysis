import axios from 'axios'

const api = axios.create({
  baseURL: '/api',
  timeout: 30000,
})

export interface Platform {
  name: string
  display_name: string
  detected: boolean
  data_dir: string
}

export interface Session {
  username: string
  display_name: string
  session_type: number
  summary: string
  last_time: string
  unread: number
  msg_count: number
  synced_at?: string
}

export interface Message {
  time_text: string
  sender: string
  sender_id: string
  text: string
  msg_type: number
  msg_type_label: string
  hour?: number
  message_id?: number
  has_attachment?: boolean
  attachment_name?: string
  media_url?: string
}

export interface Contact {
  user_id: string
  nickname: string
  remark: string
}

export interface Stats {
  total_messages: number
  unique_senders: number
  sender_stats: Record<string, number>
  hourly_distribution: Record<string, number>
  msg_type_distribution: Record<string, number>
  time_range: { start?: string; end?: string }
  top_senders: { name: string; count: number }[]
  activity_timeline: { date: string; count: number }[]
}

export interface Source {
  id: string
  kind: string
  computer_name: string
  operator_name?: string
  username: string
  account_id: string
  host: string
  last_sync: string
  session_count: number
  platform: string
}

export interface ReadApiInfo {
  enabled: boolean
  key: string
  keys?: { name: string; key: string }[]
  urls: string[]
  example?: string
}

export interface IngestInfo {
  token: string
  port: number
  urls: string[]
  web_port?: number
  web_urls?: string[]
  read_api?: ReadApiInfo
}

export interface PresenceClient {
  source_id: string
  operator_name: string
  computer_name: string
  host: string
  last_seen: string
}

export interface PresenceAlert {
  id: number
  kind: string
  title: string
  message: string
  time: string
  source_id?: string
}

export interface PresenceSnapshot {
  online: PresenceClient[]
  alerts: PresenceAlert[]
}

export interface SearchHit {
  source_id: string
  source_name: string
  session_id: string
  session_name: string
  time_text: string
  sender: string
  sender_id: string
  text: string
  snippet: string
  message_id: number
  msg_type: number
  attachment_name: string
  media_url: string
}

export const chatApi = {
  getPlatforms: () => api.get<Platform[]>('/platforms'),
  getSources: () => api.get<Source[]>('/sources'),
  getIngestInfo: () => api.get<IngestInfo>('/ingest/info'),
  getPresence: (since = 0) =>
    api.get<PresenceSnapshot>('/presence', { params: { since } }),
  searchMessages: (params: {
    q: string
    source_id?: string
    session_id?: string
    limit?: number
  }) => api.get<SearchHit[]>('/search', { params }),
  getSourceSessions: (sourceId: string, limit = 200) =>
    api.get<Session[]>(`/sources/${encodeURIComponent(sourceId)}/sessions`, { params: { limit } }),
  getSourceMessages: (sourceId: string, sessionId: string, params?: {
    start_date?: string
    end_date?: string
    limit?: number
  }) => api.get<Message[]>(
    `/sources/${encodeURIComponent(sourceId)}/messages/${encodeURIComponent(sessionId)}`,
    { params },
  ),
  getSourceStats: (sourceId: string, sessionId: string, params?: {
    start_date?: string
    end_date?: string
  }) => api.get<Stats>(
    `/sources/${encodeURIComponent(sourceId)}/stats/${encodeURIComponent(sessionId)}`,
    { params },
  ),
  getSessions: (platform: string, limit = 100) =>
    api.get<Session[]>(`/${platform}/sessions`, { params: { limit } }),
  getMessages: (platform: string, sessionId: string, params?: {
    start_date?: string
    end_date?: string
    limit?: number
  }) => api.get<Message[]>(`/${platform}/messages/${encodeURIComponent(sessionId)}`, { params }),
  getContacts: (platform: string) =>
    api.get<Contact[]>(`/${platform}/contacts`),
  getStats: (platform: string, sessionId: string, params?: {
    start_date?: string
    end_date?: string
  }) => api.get<Stats>(`/${platform}/stats/${encodeURIComponent(sessionId)}`, { params }),
  getGroups: (platform: string) =>
    api.get<Session[]>(`/${platform}/groups`),
}

export default api
