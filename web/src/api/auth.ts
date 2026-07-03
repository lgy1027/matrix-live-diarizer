import { call } from './client'

export interface LoginResp {
  token: string
  user: { id: number; username: string; must_change_password: boolean }
}

export async function login(username: string, password: string): Promise<LoginResp> {
  return call<LoginResp>({ url: '/v1/auth/login', method: 'POST', data: { username, password } })
}

export async function logout(): Promise<void> {
  await call({ url: '/v1/auth/logout', method: 'POST' })
}

export async function changePassword(old_password: string, new_password: string) {
  return call<{ message: string; token: string; user: LoginResp['user'] }>({
    url: '/v1/auth/change-password',
    method: 'POST',
    data: { old_password, new_password },
  })
}

export async function fetchMe() {
  return call<LoginResp['user']>({ url: '/v1/auth/me' })
}
