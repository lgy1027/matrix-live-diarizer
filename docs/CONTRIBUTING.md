# 贡献指南

## 身份与署名规则

| 项 | 规则 |
|---|---|
| **author / committer** | 必须是 `lgy1027 <lgy10271416@gmail.com>` |
| **不允许的字样** | `claude` / `anthropic` / `Co-Authored-By: Claude` / `🤖 Generated with Claude` / 任何 AI 工具痕迹 |
| **commit message 语言** | 中文 |
| **commit message 风格** | Conventional Commits (`<type>(<scope>): <subject>`) |

## 防御层 (3 道)

1. **本仓库 `.githooks/pre-commit`** — 拦截 author/committer 不在允许列表的 commit
2. **本仓库 `.githooks/commit-msg`** — 拦截 commit message 含 `claude` / `anthropic` / AI 痕迹
3. **Claude Code 工具级** — `~/.claude/settings.json` 设 `attribution.commit = ""` 禁用自动 co-author 注入

## 新协作者 setup

```bash
# 1. 克隆 + 装 hooks
git clone https://github.com/lgy1027/matrix-live-diarizer.git
cd matrix-live-diarizer
git config core.hooksPath .githooks

# 2. 设 git 身份(必须是 lgy1027)
git config user.name "lgy1027"
git config user.email "lgy10271416@gmail.com"

# 3. 验证
git config user.name
git config user.email

# 4. 跑 hooks 自检(应看到"通过")
echo "fix: 自检" > /tmp/test-msg
.githooks/commit-msg /tmp/test-msg && echo "✅ hook 工作"
```

## 关闭 Claude Code 的自动 co-author 注入

`~/.claude/settings.json` 加:

```json
{
  "attribution": {
    "commit": "",
    "pr": ""
  }
}
```

(空字符串 = 隐藏 attribution)

也可用旧版字段(已弃用但仍生效):
```json
{
  "includeCoAuthoredBy": false
}
```

## 关闭其它 AI 工具的 co-author 注入

| 工具 | 配置位置 | 关闭方法 |
|------|---------|----------|
| **Cursor** | Settings → Git → Uncheck "Enable co-author" | 取消勾选 |
| **GitHub Copilot CLI** | `gh config set git_assistant false` | 关闭 git assistant |
| **Aider** | `--no-detach` + 手动 commit | 不用 Aider 的 commit |
| **Windsurf/Cody** | IDE Settings | 关闭 "AI commit message" |

## 误触发了 hook 怎么办

```bash
# hook 拦了 → commit 失败 → 你的 commit 还没创建,直接编辑
git commit                  # 会再次触发 hook
# 改完后再试

# 万一真的提交了(用 --no-verify 绕过)
git commit --no-verify -m "..."
# 立即 amend 改 message + 推送前 filter-branch 清理
git commit --amend        # 编辑 message
# 推送前用 filter-branch 清理整个历史(慎用,会重写所有 commit hash)
```

## 为什么这样规定

1. **隐私合规**: 项目承诺"你的音频、文本、声纹向量、设置永远不会离开你的电脑"(见 `docs/PRIVACY.md`)。任何 AI 工具痕迹都意味着数据可能离开过。
2. **审计可追溯**: reviewer 看到 `lgy1027` 就知道是人类审核;看到 AI 痕迹要重新评估每行代码。
3. **工具无关**: 即便后端用的是国产模型(`ANTHROPIC_BASE_URL` 指向 `api.minimaxi.com`),commit 历史依然干净。
4. **未来兼容**: 如果以后想换回真实 Claude 也不会有历史包袱。

## 例外情况

紧急 fix 但没设对 git config:
```bash
GIT_AUTHOR_NAME="lgy1027" GIT_AUTHOR_EMAIL="lgy10271416@gmail.com" \
GIT_COMMITTER_NAME="lgy1027" GIT_COMMITTER_EMAIL="lgy10271416@gmail.com" \
git commit -m "..."
```

新增协作者邮箱:改 `.githooks/pre-commit` 的 `ALLOWED_EMAILS` 数组,然后 commit 这个改动。
