// web/js/history.js
const tbody = document.getElementById("history-tbody");
const searchQ = document.getElementById("search-q");
const filterSource = document.getElementById("filter-source");
const btnSearch = document.getElementById("btn-search");
const hitsPanel = document.getElementById("hits-panel");

const escapeHtml = Matrix.escape;

// 渲染搜索结果高亮: 把 [match]xxx[/match] 替换为 <mark>xxx</mark>
// 输入已 escape 过,只有 [match]/[/match] 是占位符
function renderHighlighted(snippet) {
  return escapeHtml(snippet || "").replace(/\[match\]/g, "<mark>").replace(/\[\/match\]/g, "</mark>");
}

async function load() {
  const q = searchQ.value.trim();
  const source = filterSource.value;

  // 1) 有 q → 调 /v1/search 显示命中
  if (q.length >= 1) {
    try {
      const data = await Matrix.api.get(`search?q=${encodeURIComponent(q)}${source ? `&source=` : ""}`);
      renderHits(data.hits, data.total, q);
      // 隐藏会话列表
      tbody.closest("table").style.display = "none";
    } catch (e) {
      hitsPanel.innerHTML = `<div class="empty">搜索失败: ${escapeHtml(e.message)}</div>`;
    }
    return;
  }

  // 2) 无 q → 显示会话列表
  hitsPanel.innerHTML = "";
  hitsPanel.style.display = "none";
  tbody.closest("table").style.display = "";
  const params = {};
  if (q) params.q = q;
  if (source) params.source = source;
  const qs = Matrix.qs(params);
  try {
    const data = await Matrix.api.get(`history?${qs}`);
    render(data.items, data.total);
  } catch (e) {
    tbody.innerHTML = `<tr><td colspan="6" class="empty">加载失败: ${escapeHtml(e.message)}</td></tr>`;
  }
}

function renderHits(hits, total, q) {
  hitsPanel.style.display = "block";
  if (!hits.length) {
    hitsPanel.innerHTML = `<div class="empty">没有匹配 "${escapeHtml(q)}" 的内容。<br>建议: 至少输入 3 字符以获得更好结果(中文 trigram 限制)。</div>`;
    return;
  }
  hitsPanel.innerHTML = `
    <div class="hits-header">
      <strong>${total}</strong> 个匹配 "${escapeHtml(q)}"
      <a class="btn btn-secondary btn-sm" href="#" onclick="event.preventDefault(); document.getElementById('search-q').value=''; load();">查看所有会话</a>
    </div>
    ${hits.map((h) => `
      <div class="hit">
        <div class="hit-meta">
          <a href="${escapeHtml(h.jump_url)}"><strong>${escapeHtml(h.session_title || h.session_filename || "未命名")}</strong></a>
          ${h.speaker_id ? ` · <span class="hit-spk">${escapeHtml(h.speaker_id)}</span>` : ""}
          · <span class="hit-time">${Matrix.formatTime(h.start_time)}–${Matrix.formatTime(h.end_time)}</span>
        </div>
        <div class="hit-snippet">${renderHighlighted(h.snippet)}</div>
      </div>
    `).join("")}
  `;
}

function render(items) {
  if (!items.length) {
    tbody.innerHTML = `<tr><td colspan="6" class="empty">暂无历史会话</td></tr>`;
    return;
  }
  tbody.innerHTML = items.map((s) => `
    <tr>
      <td>${Matrix.formatDate(s.created_at)}</td>
      <td>${escapeHtml(s.title || s.original_filename || "未命名")}</td>
      <td>${s.source === "websocket" ? "实时" : "上传"}</td>
      <td>${Matrix.formatTime(s.duration_sec || 0)}</td>
      <td>${s.speaker_count || 0}</td>
      <td>
        <a class="btn btn-secondary" href="/web/detail.html?id=${s.id}">查看</a>
        <button class="btn btn-danger" onclick="del('${s.id}')">删除</button>
      </td>
    </tr>
  `).join("");
}

async function del(id) {
  if (!confirm("确认删除？此操作不可撤销。")) return;
  try {
    await Matrix.api.del(`history/${id}`);
    load();
  } catch (e) {
    alert("删除失败: " + e.message);
  }
}

btnSearch.addEventListener("click", load);
searchQ.addEventListener("keypress", (e) => e.key === "Enter" && load());
filterSource.addEventListener("change", load);
load();
