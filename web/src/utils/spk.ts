// 声纹调色板 + 色 index 计算
export const SPK_PALETTE = [
  '#FF6B35', // amber
  '#4ECDC4', // teal
  '#D4A574', // gold
  '#C589E8', // purple
  '#7BC96F', // green
  '#FFB347', // orange
  '#5DADE2', // blue
  '#EC7063', // coral
] as const

export function spkColorIndex(id: string | undefined | null): number {
  if (!id) return 0
  let h = 0
  for (let i = 0; i < id.length; i++) {
    h = (h * 31 + id.charCodeAt(i)) >>> 0
  }
  return h % SPK_PALETTE.length
}

export function spkColor(id: string | undefined | null): string {
  return SPK_PALETTE[spkColorIndex(id)]
}

export function spkInitial(name: string | undefined | null): string {
  if (!name) return '—'
  return name.replace(/^Spk_/, '').slice(0, 1).toUpperCase()
}
