// 共用 enroll 声纹流程: 文件选择 → 弹 prompt 拿 speaker_id → 弹 prompt 拿 name → 调 API
// Live view / Voice view 共享
import { useI18n } from 'vue-i18n'
import { useDialog } from './useDialog'
import { useVoiceStore } from '../stores/voice'

export function useEnrollSpeaker() {
  const dialog = useDialog()
  const voice = useVoiceStore()
  const { t } = useI18n()

  async function pickFile(): Promise<File | null> {
    return await new Promise((resolve) => {
      const input = document.createElement('input')
      input.type = 'file'
      input.accept = 'audio/wav,audio/mpeg,audio/mp4,audio/flac,audio/ogg,audio/aac,audio/x-m4a,.wav,.mp3,.m4a,.flac,.ogg,.aac,.wma'
      input.onchange = () => resolve(input.files?.[0] || null)
      input.click()
    })
  }

  async function enroll() {
    const file = await pickFile()
    if (!file) return
    const baseName = file.name.replace(/\.[^.]+$/, '').replace(/[^a-zA-Z0-9_]/g, '_').slice(0, 30)
    const suffix = String(Date.now()).slice(-6)
    const defaultId = `Spk_${baseName || 'user'}_${suffix}`
    const speakerId = await dialog.showPrompt({
      title: t('voice.enroll.id.title') || '输入声纹 ID',
      message: t('voice.enroll.id.body') || `将使用文件: ${file.name}\n格式必须 Spk_xxx (字母数字下划线)`,
      initialValue: defaultId,
      validate: (v: string) => {
        if (!/^Spk_[a-zA-Z0-9_]{1,50}$/.test(v)) return '格式: Spk_xxx (字母数字下划线, 1-50 字符)'
        return null
      },
    })
    if (!speakerId) return
    const name = await dialog.showPrompt({
      title: t('voice.enroll.name.title') || '名称 (可选)',
      placeholder: t('voice.enroll.name.ph') || '例如: 张三',
    })
    try {
      window.toast?.(t('voice.enroll.uploading') || '正在注册声纹...', 'info')
      await voice.enroll(file, speakerId, name || undefined)
      window.toast?.(t('voice.enroll.ok') || '已注册', 'ok')
    } catch (e) {
      window.toast?.(`${t('toast.error')}: ${e instanceof Error ? e.message : e}`, 'error')
    }
  }

  return { enroll }
}
