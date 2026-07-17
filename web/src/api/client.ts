import axios, { AxiosError, type AxiosRequestConfig } from 'axios'
import { useAuthStore } from '../stores/auth'
import { router } from '../router'

export const apiClient = axios.create({
  baseURL: '/',
  timeout: 30_000,
})

// 请求拦截: Bearer 注入 (除 login / logout)
apiClient.interceptors.request.use((config) => {
  const auth = useAuthStore()
  const url = config.url || ''
  if (auth.token && !/\/v1\/auth\/(login|logout)$/.test(url)) {
    config.headers = config.headers || {}
    config.headers.Authorization = `Bearer ${auth.token}`
  }
  return config
})

// 响应拦截: 401 → 跳 login
apiClient.interceptors.response.use(
  (r) => r,
  (err: AxiosError) => {
    if (err.response?.status === 401) {
      const auth = useAuthStore()
      auth.clear()
      const next = router.currentRoute.value.fullPath
      router.push({ name: 'login', query: { next } })
    }
    return Promise.reject(err)
  },
)

/** 将后端 detail 统一转换为前端 Error。 */
export async function call<T = unknown>(config: AxiosRequestConfig): Promise<T> {
  try {
    const r = await apiClient.request<T>(config)
    return r.data
  } catch (err) {
    const ax = err as AxiosError<{ detail?: string }>
    const detail = ax.response?.data?.detail || ax.message || 'Request failed'
    throw new Error(detail)
  }
}
