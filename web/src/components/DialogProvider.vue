<script setup lang="ts">
import { provide, reactive } from 'vue'
import { useI18n } from 'vue-i18n'
import { changePassword as apiChangePassword } from '../api/auth'
import { useAuthStore } from '../stores/auth'
import { DIALOG_KEY, type ConfirmOpts, type PromptOpts, type ListOpts } from '../composables/useDialog'
import ConfirmDialog from './ConfirmDialog.vue'
import PromptDialog from './PromptDialog.vue'
import ListDialog from './ListDialog.vue'
import ChangePwdDialog from './ChangePwdDialog.vue'

interface State {
  confirm: (ConfirmOpts & { resolve: (v: boolean) => void }) | null
  prompt: (PromptOpts & { resolve: (v: string | null) => void }) | null
  list: (ListOpts & { resolve: (v: boolean) => void }) | null
  changePwd: { resolve: (v: 'ok' | 'cancel') => void } | null
}
const state = reactive<State>({
  confirm: null,
  prompt: null,
  list: null,
  changePwd: null,
})

const auth = useAuthStore()
const { t } = useI18n()

function showConfirm(opts: ConfirmOpts): Promise<boolean> {
  return new Promise((resolve) => { state.confirm = { ...opts, resolve } })
}
function showPrompt(opts: PromptOpts): Promise<string | null> {
  return new Promise((resolve) => { state.prompt = { ...opts, resolve } })
}
function showList(opts: ListOpts): Promise<boolean> {
  return new Promise((resolve) => { state.list = { ...opts, resolve } })
}
function showChangePassword(): Promise<'ok' | 'cancel'> {
  return new Promise((resolve) => { state.changePwd = { resolve } })
}

provide(DIALOG_KEY, { showConfirm, showPrompt, showList, showChangePassword })

async function onPwdSubmit(oldPwd: string, newPwd: string) {
  try {
    const r = await apiChangePassword(oldPwd, newPwd)
    if (r.token) auth.setToken(r.token, r.user)
    window.toast?.(t('account.pwd.changed') || '密码已修改', 'ok')
    state.changePwd?.resolve('ok')
    state.changePwd = null
  } catch (e) {
    // 把错误抛给 ChangePwdDialog 内部显示
    throw e
  }
}
</script>

<template>
  <slot />
  <ConfirmDialog
    v-if="state.confirm"
    v-bind="state.confirm"
    @close="state.confirm?.resolve(false); state.confirm = null"
    @confirm="state.confirm?.resolve(true); state.confirm = null"
  />
  <PromptDialog
    v-if="state.prompt"
    v-bind="state.prompt"
    @close="state.prompt?.resolve(null); state.prompt = null"
    @submit="(v: string) => { state.prompt?.resolve(v); state.prompt = null }"
  />
  <ListDialog
    v-if="state.list"
    v-bind="state.list"
    @close="state.list?.resolve(false); state.list = null"
    @confirm="state.list?.resolve(true); state.list = null"
  />
  <ChangePwdDialog
    v-if="state.changePwd"
    @close="state.changePwd?.resolve('cancel'); state.changePwd = null"
    @submit="(oldPwd, newPwd) => onPwdSubmit(oldPwd, newPwd)"
  />
</template>
