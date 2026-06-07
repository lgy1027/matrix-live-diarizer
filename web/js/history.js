// web/js/history.js
const tbody = document.getElementById("history-tbody");
const searchQ = document.getElementById("search-q");
const filterSource = document.getElementById("filter-source");
const btnSearch = document.getElementById("btn-search");

const escapeHtml = Matrix.escape;

async function load() {
  const params = {};
  if (searchQ.value) params.q = searchQ.value;
  if (filterSource.value) params.source = filterSource.value;
  const qs = Matrix.qs(params);
  try {
    const data = await Matrix.api.get(`history?${qs}`);
    render(data.items, data.total);
  } catch (e) {
    tbody.innerHTML = `<tr><td colspan="6" class="empty">加载失败: ${escapeHtml(e.message)}</td></tr>`;
  }
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
