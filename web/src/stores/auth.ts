import { defineStore } from 'pinia'
import { computed, ref } from 'vue'

export interface User {
  id: number
  username: string
  must_change_password: boolean
}

const TOKEN_KEY = 'matrix_token'
const USER_KEY = 'matrix_user'

function loadToken(): string | null {
  try {
    return localStorage.getItem(TOKEN_KEY) ?? sessionStorage.getItem(TOKEN_KEY)
  } catch { return null }
}
function loadUser(): User | null {
  try {
    const raw =
      localStorage.getItem(USER_KEY) ?? sessionStorage.getItem(USER_KEY)
    return raw ? JSON.parse(raw) : null
  } catch { return null }
}

function _storeFor(persist: boolean): Storage {
  return persist ? localStorage : sessionStorage
}

export const useAuthStore = defineStore('auth', () => {
  const token = ref<string | null>(loadToken())
  const user = ref<User | null>(loadUser())
  const isLoggedIn = computed(() => !!token.value)
  const mustChangePwd = computed(() => !!user.value?.must_change_password)

  function setToken(t: string, u?: User, persist: boolean = true) {
    // persist=false(未勾"记住我")用 sessionStorage: 关闭浏览器后失效。
    const store = _storeFor(persist)
    const other = _storeFor(!persist)
    other.removeItem(TOKEN_KEY)
    other.removeItem(USER_KEY)
    token.value = t
    store.setItem(TOKEN_KEY, t)
    if (u) {
      user.value = u
      store.setItem(USER_KEY, JSON.stringify(u))
    }
  }

  function clear() {
    token.value = null
    user.value = null
    localStorage.removeItem(TOKEN_KEY)
    localStorage.removeItem(USER_KEY)
    sessionStorage.removeItem(TOKEN_KEY)
    sessionStorage.removeItem(USER_KEY)
  }

  return { token, user, isLoggedIn, mustChangePwd, setToken, clear }
})
