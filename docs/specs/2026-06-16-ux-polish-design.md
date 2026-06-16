# UX 快修 — 实时转写体验优化

> 日期: 2026-06-16
> 状态: 设计稿 · 待实现
> 维护: lgy1027
> 关联: 用户反馈「实时转写体验不好」,聚焦 **延迟感 + 说话人标签错**

---

## 目标

让用户感知的"实时转写体验"从「沉默几秒 + 突然出现」变成「立刻有反馈 + 渐进呈现 + 说话人友好」。

**核心约束**:
- 不动 ASR / VAD 算法本身
- 1 个最小后端改动:`websocket.py` 在 STATE_SILENCE→STATE_SPEECH 时多推 1 条 ws 消息(`type:'transcribing'`)
- 1 个最小引擎改动:`compare_and_identify` 返回值从 `str` 扩为 `tuple[str, float]`(暴露已有 score,**不改算法**)
- 仅前端派生 displayName / 占位状态机 / 改名菜单
- 1-3 天落地,改动各自独立 commit

---

## 4 个改动

### 1. 转写中占位符(感知延迟)

**问题**:VAD 攒静音帧(~1s)+ ASR 跑(0.5-3s)= **1.5-4s 沉默期**让用户觉得"卡死"。

**方案**:VAD 检测到语音开始第一帧,服务端立刻推 `{"type":"transcribing", "seq": <int>}`;前端立刻显示脉动占位行。ASR 真结果带相同 `seq` 回来时,占位替换为打字机段。

**数据流**:
```
VAD 进入 STATE_SPEECH (第 1 个 loud frame)
  └─► ws.send({type: 'transcribing', seq})
        └─► 前端 segments.push({id, status: 'transcribing', displayed: '▌ 正在识别…'})
VAD 攒够静音 → 触发 ASR
  └─► ws.send({speaker, text, time, seq, score})
        └─► 前端按 seq 找到占位段 → 改成正常段 + 启动打字机
```

**边界**:
- 占位段不计入 `speakers` Map,不显示说话人标签
- 同一时刻仅 1 个占位段:新 transcribing 到达时旧的若未识别完,标 `status: 'stale'` 并折叠(显示为浅灰细行)
- 超时(5s 仍无 ASR 结果):占位标 `status: 'timeout'`,淡出,不污染历史
- 占位段不进数据库(只有正常段走 `transcript_repo`)

**后端最小改动**:`app/api/websocket.py:273-276`(STATE_SILENCE→STATE_SPEECH 分支)加一行 `await ws.send_json({"type": "transcribing", "seq": next_seq()})`。`seq` 在 ws session 内单调递增,与 ASR 完成时的 `seq` 配对。

---

### 2. Speaker 友好显示

**问题**:segment 现在直接显示后端 `speaker` 字段(如 `Spk_a3f9e2` 或 `SYSTEM`),用户看着陌生。

**方案**:前端在 segment 上**派生** `displayName`:

| 后端 speaker | 显示 |
|---|---|
| `SYSTEM` / `LINK_IDLE_TIMEOUT` | 系统 |
| `Spk_xxx` 模式 + **本 session 首次见** | `Speaker N`(N = session 内累计计数,从 1 开始) |
| `Spk_xxx` 模式 + **本 session 已见** | 同上次的 `Speaker N`(稳定) |
| 命中已注册声纹 alias | 别名(或本地化名) |
| 长度异常 / `?` 后缀 | 未知说话人 |

**实现**:
- `live.ts` 维护 `sessionSpeakers: Map<string, number>`(speaker ID → session 内顺序号)
- store 加 `getDisplayName(seg)` getter
- 模板用 `{{ getDisplayName(seg) }}` 替代 `{{ seg.speaker }}`
- 持久化名(已注册声纹别名)通过现有 `speakers` store 取(已实现,只需接线)

---

### 3. 置信度可视化

**问题**:声纹识别相似度低于阈值时,前端不知道,显示"看似确定"的标签。

**方案**:目前 `compare_and_identify` 返回值只有 `spk_id`(str),`score` 是引擎内部计算的,未外露。本设计需把返回扩为 `tuple[str, float]` —— **仅暴露已有数据,不动识别逻辑**。

前端收到 ASR 消息时:`speaker` 字段 = spk_id,新加 `score` 字段 = 引擎内部的相似度(0-1)。

| score 区间 | 视觉 |
|---|---|
| `≥ 0.65` | 实线标签 + 主色 |
| `0.4 ≤ score < 0.65` | 虚线标签 + 黄色 + 后缀 `?`(`Speaker 2?`) |
| `< 0.4` | 灰色"未知说话人" |

阈值 0.65 / 0.4 从 `engine/speaker/base_engine.py:SpeakerConfig.SIMILARITY_THRESHOLD` 拉(后端已有)。

**实现**:新增 `SpeakerLabel.vue`,接收 `{speaker, score}` props,根据区间选 class;`LiveView.vue` 替换原标签渲染。

---

### 4. 一键改名 / 合并

**问题**:segment 说话人标签当前**不可点**,用户发现错标签只能忍着。

**方案**:点击 segment 说话人标签 → 弹菜单:

| 菜单项 | 行为 |
|---|---|
| 改成本次新名字 | 输入框 → 改后 session 内生效 |
| 合并到已有声纹 | 列出所有已注册声纹 + session 内 Speaker N,选一个合并 |
| 保存为新声纹 | 走 enroll 流程(已有,加入口) |
| 恢复原始 ID | 撤销本次改名 |

**实现**:
- 新增 `SpeakerMenu.vue`(基于现有 dialog 体系 `web/src/utils/dialog.ts`)
- `LiveView.vue` segment 标签 `click` 触发
- store 加 `renameSegmentSpeaker(segId, newName)` / `mergeSegmentSpeaker(segId, targetSpeakerId)` / `revertSegmentRename(segId)`
- 改名仅影响前端显示(`segment.displayName` 派生用 `override: Map<segId, string>`),刷新即重置 — 跟"实时显示"对齐,不进数据库

---

## 不在范围

- ❌ 改 ASR 模型/参数
- ❌ 改 VAD 阈值/算法
- ❌ 改 ChromaDB / 声纹比对逻辑
- ❌ 持久化用户重命名到数据库(session 内生效,刷新即重置)
- ❌ 改现有 38 个 pytest 测试
- ❌ 改 i18n 字符串(只新增,不破坏现有)

---

## 测试 + 验收

### 单测

| 文件 | 覆盖 |
|---|---|
| `web/tests/unit/liveStore.spec.ts` (新) | `getDisplayName` 各种输入;`sessionSpeakers` 稳定分配;占位段 → 正常段替换;超时占位淡出 |
| `web/tests/unit/speakerMenu.spec.ts` (新) | 菜单 open/close、改名/合并/恢复的 store mutation |
| `tests/test_websocket_transcribing.py` (新) | mock VAD/ASR,验证 STATE_SPEECH 第一帧发 `transcribing`,ASR 完成时发正常消息,二者带相同 `seq` |

### Playwright E2E

新脚本 `verify_ux_v2.py`(沿用 `verify_all.py` 模式):

1. **占位符**:注入 `{type:'transcribing', seq:1}` → DOM 出现脉动行;注入 ASR 结果 `{seq:1, speaker, text}` → 脉动行替换为打字机段
2. **友好 Speaker 名**:注入 3 条不同 speaker 的 ASR → 显示 `Speaker 1/2/3`(不是 `Spk_xxx`)
3. **置信度 3 档**:注入 `score=0.3` / `0.55` / `0.8` 三条 → class 切换正确
4. **改名**:点 segment 标签 → 弹菜单 → 选"改成本次新名字" → 输入 `Alice` → segment 显示 `Alice`

### 验收标准

| 项 | 标准 |
|---|---|
| 占位符出现到用户感知 | ≤ 100ms(VAD 触发 → 占位出现) |
| Speaker 友好名 | session 内同 speaker 跨多次 ASR 显示一致名称 |
| 置信度 3 档 | 视觉一眼可分辨(实线/虚线/灰) |
| 改名 / 合并 | 菜单可点、可改、可恢复;刷新页面重置 |
| **不动后端 ASR/VAD 算法** | `git diff engine/` 仅改 `compare_and_identify` 签名,不动识别逻辑 |
| 现有测试不退步 | 38+ pytest + i18n 测试全过 |

---

## 提交策略

4 个改动各自 1 个独立 commit:

1. `feat(live): VAD 触发时立刻推 transcribing 占位消息`
2. `feat(live): Speaker 友好显示(Speaker 1/2/3 + 未知)`
3. `feat(live): 置信度可视化(实线/虚线/灰)`
4. `feat(live): 一键改名/合并菜单`

每个 commit 自测通过后再合下一个,**绝不批量提交**。所有 commit 不含 AI 标记(CLAUDE.md 约定)。

---

## 影响面

| 文件 | 是否改 |
|---|---|
| `engine/asr_engine.py` | ❌ |
| `engine/speaker/base_engine.py` | ✅ `compare_and_identify` 返回类型 `str` → `tuple[str, float]`(签名扩) |
| `engine/speaker/{campplus,eres2net,wespeaker}_engine.py` | ✅ 同上,3 个子类同步 |
| `app/api/websocket.py` | ✅ 加 1 行 `ws.send_json({"type":"transcribing", ...})` |
| `app/services/audio_processor.py` | 可能需微调 seq 计数 |
| `web/src/stores/live.ts` | ✅ `getDisplayName` / `sessionSpeakers` / 占位状态机 / rename/merge |
| `web/src/views/LiveView.vue` | ✅ 模板接线 + SpeakerLabel 替换 |
| `web/src/components/SpeakerLabel.vue` | ✅ 新建 |
| `web/src/components/SpeakerMenu.vue` | ✅ 新建 |
| `tests/test_websocket_transcribing.py` | ✅ 新建 |
| `web/tests/unit/liveStore.spec.ts` | ✅ 新建 |
| `web/tests/unit/speakerMenu.spec.ts` | ✅ 新建 |
| `docs/USAGE.md` | ✅ 追加"说话人改名/合并"小节 |
| `docs/ROADMAP.md` | ✅ 把 #1.2(字级时间戳)/ #1.3(合并拆分) 状态更新 |

---

## 后续(本次不做)

- **B 方案**(session 内聚类):本次落地后,可作为下次迭代,把"自动合并未识别段"加上
- **字级时间戳**(ROADMAP #1.2):解锁精确字幕 + 卡拉 OK UX,独立 spec
- **说话人合并拆分**(ROADMAP #1.3):ChromeDB 级合并,独立 spec,可能 2 天

