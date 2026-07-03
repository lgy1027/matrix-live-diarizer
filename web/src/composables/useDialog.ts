// 抽 useDialog 到独立 .ts 文件, 避免 DialogProvider 双 script 块导致 typecheck 找不到
import { inject, type InjectionKey } from 'vue'

export interface DialogApi {
  showConfirm: (opts: ConfirmOpts) => Promise<boolean>
  showPrompt: (opts: PromptOpts) => Promise<string | null>
  showList: (opts: ListOpts) => Promise<boolean>
  showChangePassword: () => Promise<'ok' | 'cancel'>
}

export interface ConfirmOpts {
  title: string
  message?: string
  detail?: string
  confirmText?: string
  cancelText?: string
  danger?: boolean
}
export interface PromptOpts {
  title: string
  message?: string
  placeholder?: string
  initialValue?: string
  confirmText?: string
  cancelText?: string
  validate?: (v: string) => string | null
}
export interface ListOpts {
  title: string
  body?: string
  items: string[]
  itemCount?: number
  itemCountLabel?: string
  confirmText?: string
  cancelText?: string
  danger?: boolean
}

export const DIALOG_KEY: InjectionKey<DialogApi> = Symbol('dialog')

export function useDialog(): DialogApi {
  const api = inject(DIALOG_KEY)
  if (!api) {
    // fallback: 让组件至少不崩, 在测试/SSR 场景下用
    return {
      showConfirm: async () => true,
      showPrompt: async () => null,
      showList: async () => true,
      showChangePassword: async () => 'cancel',
    }
  }
  return api
}
