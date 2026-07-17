import fs from 'node:fs'

function keys(path) {
  const source = fs.readFileSync(path, 'utf8')
  return new Set([...source.matchAll(/'([^']+)'\s*:/g)].map((match) => match[1]))
}

const zh = keys('src/i18n/zh.ts')
const en = keys('src/i18n/en.ts')
const missingEnglish = [...zh].filter((key) => !en.has(key))
const missingChinese = [...en].filter((key) => !zh.has(key))

if (missingEnglish.length || missingChinese.length) {
  console.error('Missing English keys:', missingEnglish)
  console.error('Missing Chinese keys:', missingChinese)
  process.exit(1)
}

console.log(`i18n dictionaries are aligned (${zh.size} keys each)`)
