// web/js/detail.js
const sessionId = new URLSearchParams(location.search).get("id");
const titleEl = document.getElementById("title");
const metaEl = document.getElementById("meta");
const textEl = document.getElementById("text");
const statsEl = document.getElementById("stats");
const llmResult = document.getElementById("llm-result");

function escapeHtml(s) {
  return String(s || "").replace(/[&<>"']/g, (c) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
  })[c]);
}

if (!sessionId) {
  // 没带 ?id= 直接打开 detail 页 — 引导回 history
  titleEl.textContent = "缺少会话 ID";
  metaEl.innerHTML = `<div>请从 <a href="/web/history.html" style="color:#4ade80">历史会话</a> 列表选择一个会话查看详情。</div>`;
} else {

async function load() {
  try {
    const data = await Matrix.api.get(`sessions/${sessionId}`);
    titleEl.textContent = data.session.title || data.session.original_filename || "未命名";
    metaEl.innerHTML = `
      <strong>来源</strong>: ${data.session.source === "websocket" ? "实时" : "上传"} |
      <strong>时长</strong>: ${Matrix.formatTime(data.session.duration_sec || 0)} |
      <strong>段数</strong>: ${data.segments.length} |
      <strong>创建</strong>: ${Matrix.formatDate(data.session.created_at)}
    `;
    renderText(data.segments);
    renderStats(data.statistics);
    await checkLLM();
  } catch (e) {
    titleEl.textContent = "加载失败";
    metaEl.textContent = e.message;
  }
}

function renderText(segs) {
  if (!segs.length) {
    textEl.innerHTML = `<div class="empty">无转写内容</div>`;
    return;
  }
  textEl.innerHTML = segs.map((s) => `
    <div class="segment">
      <div class="meta">${Matrix.formatTime(s.start_time)} - ${Matrix.formatTime(s.end_time)}
        ${s.speaker_id ? ` · <strong>${escapeHtml(s.speaker_id)}</strong>` : ""}
      </div>
      <div>${escapeHtml(s.text)}</div>
    </div>
  `).join("");
}

function renderStats(stats) {
  if (!stats.speakers || !stats.speakers.length) {
    statsEl.innerHTML = `<div class="empty">无统计数据</div>`;
    return;
  }
  const max = Math.max(...stats.speakers.map((s) => s.talk_time_sec), 1);
  statsEl.innerHTML = `
    <h2>说话人时长</h2>
    ${stats.speakers.map((s) => `
      <div class="stat-bar">
        <span class="name">${escapeHtml(s.display_name || s.speaker_id || "未识别")}</span>
        <div class="bar" style="width: ${(s.talk_time_sec / max) * 60}%;"></div>
        <span class="pct">${Matrix.formatTime(s.talk_time_sec)} (${(s.talk_ratio * 100).toFixed(1)}%)</span>
      </div>
    `).join("")}
    <h2 style="margin-top:2rem;">热词</h2>
    <div>${(stats.hot_words || []).slice(0, 10).map((w) => `<span style="margin:0 0.5rem;">${escapeHtml(w.word)} (${w.count})</span>`).join("")}</div>
    <h2 style="margin-top:2rem;">总览</h2>
    <p>总时长: ${Matrix.formatTime(stats.total_duration_sec || 0)} · 静音: ${((stats.silence_ratio || 0) * 100).toFixed(1)}% · 说话人切换: ${stats.turn_taking_count || 0} 次</p>
  `;
}

async function checkLLM() {
  try {
    const status = await Matrix.api.get("llm/status");
    if (status.enabled && status.available) {
      document.getElementById("tab-ai").style.display = "block";
    }
  } catch (e) {
    // LLM 不可用，隐藏标签
  }
}

async function llm(op) {
  llmResult.textContent = "生成中...";
  try {
    const data = await Matrix.api.post(`llm/${op}`, { session_id: sessionId });
    llmResult.textContent = data.text || (data.items || []).join("\n") || "";
  } catch (e) {
    llmResult.textContent = `错误: ${e.message}`;
  }
}

function dl(fmt) {
  Matrix.api.download(`exports/${sessionId}?format=${fmt}`);
}

document.querySelectorAll(".tab").forEach((tab) => {
  tab.addEventListener("click", () => {
    document.querySelectorAll(".tab").forEach((t) => t.classList.remove("active"));
    document.querySelectorAll(".tab-content").forEach((c) => c.classList.remove("active"));
    tab.classList.add("active");
    document.getElementById(tab.dataset.tab).classList.add("active");
  });
});

load();

} // 关闭 if (!sessionId) 块
