import { createI18n } from 'vue-i18n'
import zh from './zh'
import en from './en'

const LANG_KEY = 'matrix_lang'

export const i18n = createI18n({
  legacy: false,
  locale: (localStorage.getItem(LANG_KEY) as 'zh' | 'en') || 'zh',
  fallbackLocale: 'en',
  messages: { zh, en },
})

export function setLocale(lang: 'zh' | 'en') {
  i18n.global.locale.value = lang
  localStorage.setItem(LANG_KEY, lang)
  document.documentElement.lang = lang === 'zh' ? 'zh-CN' : 'en'
}

// 启动时同步 html lang
document.documentElement.lang = i18n.global.locale.value === 'zh' ? 'zh-CN' : 'en'
