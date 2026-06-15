// 时间/日期/相对时间 格式化
export function fmtSec(sec: number): string {
  if (!isFinite(sec) || sec < 0) sec = 0
  const m = Math.floor(sec / 60)
  const s = Math.floor(sec % 60)
  return `${String(m).padStart(2, '0')}:${String(s).padStart(2, '0')}`
}

export function fmtClock(sec: number): string {
  if (!isFinite(sec) || sec < 0) sec = 0
  const h = Math.floor(sec / 3600)
  const m = Math.floor((sec % 3600) / 60)
  const s = Math.floor(sec % 60)
  return `${String(h).padStart(2, '0')}:${String(m).padStart(2, '0')}:${String(s).padStart(2, '0')}`
}

export function fmtRel(iso: string | number): string {
  const t = typeof iso === 'string' ? new Date(iso).getTime() : iso * 1000
  const diff = Date.now() - t
  const sec = Math.floor(diff / 1000)
  if (sec < 60) return 'just now'
  const min = Math.floor(sec / 60)
  if (min < 60) return `${min}m ago`
  const hr = Math.floor(min / 60)
  if (hr < 24) return `${hr}h ago`
  const day = Math.floor(hr / 24)
  if (day < 30) return `${day}d ago`
  const month = Math.floor(day / 30)
  if (month < 12) return `${month}mo ago`
  const year = Math.floor(month / 12)
  return `${year}y ago`
}

export function fmtDate(iso: string | number): string {
  const t = typeof iso === 'string' ? new Date(iso) : new Date(iso * 1000)
  return t.toLocaleString('zh-CN', { hour12: false })
}

export function fmtSize(bytes?: number): string {
  if (!bytes) return '—'
  const units = ['B', 'KB', 'MB', 'GB']
  let i = 0
  let v = bytes
  while (v > 1024 && i < units.length - 1) {
    v /= 1024
    i++
  }
  return `${v.toFixed(1)} ${units[i]}`
}

export function fmtMinutes(seconds?: number): string {
  if (!seconds) return '0.0'
  return (seconds / 60).toFixed(1)
}
