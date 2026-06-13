// web/js/auth.js — 鉴权工具 (Roadmap 安全项 Bug-79)
window.MatrixAuth = {
  TOKEN_KEY: "matrix_token",
  USER_KEY: "matrix_user",
  PWD_CHANGE_KEY: "matrix_pwd_change_until",

  getToken() {
    return localStorage.getItem(this.TOKEN_KEY);
  },

  getUser() {
    try {
      const u = localStorage.getItem(this.USER_KEY);
      return u ? JSON.parse(u) : null;
    } catch {
      return null;
    }
  },

  setToken(token, user) {
    localStorage.setItem(this.TOKEN_KEY, token);
    if (user) localStorage.setItem(this.USER_KEY, JSON.stringify(user));
  },

  clearToken() {
    localStorage.removeItem(this.TOKEN_KEY);
    localStorage.removeItem(this.USER_KEY);
    localStorage.removeItem(this.PWD_CHANGE_KEY);
  },

  /**
   * requireAuth() — 启动时调,无 token 跳 login
   * 返 user 对象(若可解析)或 None
   */
  requireAuth() {
    const t = this.getToken();
    if (!t) {
      location.href = "/web/login.html";
      return null;
    }
    return this.getUser();
  },

  /**
   * apiFetch() — 包装 fetch:
   * 1. 自动加 Authorization: Bearer <token>
   * 2. 401 时清 token 跳 login
   * 3. 其他错误抛 Error
   */
  async apiFetch(path, opts = {}) {
    const t = this.getToken();
    const headers = { "Content-Type": "application/json", ...(opts.headers || {}) };
    if (t) headers["Authorization"] = `Bearer ${t}`;
    const r = await fetch(`/v1/${path}`, { ...opts, headers });
    if (r.status === 401) {
      // 401: token 失效 / 过期 / 错 → 清 token 跳 login
      const data = await r.json().catch(() => ({}));
      this.clearToken();
      // 用 sessionStorage 记一下原因,login 页可读
      try { sessionStorage.setItem("matrix_last_401", data.detail || "会话已过期"); } catch {}
      location.href = "/web/login.html";
      throw new Error(data.detail || "未登录");
    }
    if (!r.ok) {
      const data = await r.json().catch(() => ({}));
      throw new Error(data.detail || r.statusText);
    }
    return r.json();
  },
};

// 全局 fetch 拦截: 给所有 /v1/* 请求自动加 Authorization (除 /v1/auth/login 本身)
const _origFetch = window.fetch;
window.fetch = function (url, opts = {}) {
  try {
    if (typeof url === "string" && url.includes("/v1/") && !url.includes("/v1/auth/login") && !url.includes("/v1/auth/logout")) {
      const t = MatrixAuth.getToken();
      if (t) {
        opts.headers = { ...(opts.headers || {}), Authorization: `Bearer ${t}` };
      }
    }
  } catch {}
  return _origFetch.call(this, url, opts);
};

// 401 全局处理:如果 fetch 返 401,清 token 跳 login
const _origApiGet = Matrix.api.get.bind(Matrix.api);
Matrix.api.get = async function (path) {
  try { return await _origApiGet(path); }
  catch (err) {
    if (err && /未登录|token|401/i.test(String(err.message || ""))) {
      MatrixAuth.clearToken();
      location.href = "/web/login.html";
    }
    throw err;
  }
};
const _origApiPost = Matrix.api.post.bind(Matrix.api);
Matrix.api.post = async function (path, body) {
  try { return await _origApiPost(path, body); }
  catch (err) {
    if (err && /未登录|token|401/i.test(String(err.message || ""))) {
      MatrixAuth.clearToken();
      location.href = "/web/login.html";
    }
    throw err;
  }
};
const _origApiDel = Matrix.api.del.bind(Matrix.api);
Matrix.api.del = async function (path) {
  try { return await _origApiDel(path); }
  catch (err) {
    if (err && /未登录|token|401/i.test(String(err.message || ""))) {
      MatrixAuth.clearToken();
      location.href = "/web/login.html";
    }
    throw err;
  }
};

// 渲染全局账户菜单(任何页面有 #userMenu 容器就生效)
MatrixAuth.renderUserMenu = function (containerId = "userMenu") {
  const host = document.getElementById(containerId);
  if (!host) return;
  const user = this.getUser() || {};
  // 头部 pill: ● 用户名 ▾
  host.innerHTML = `
    <button class="um-trigger" id="umTrigger" type="button">
      <span class="um-dot"></span>
      <span class="um-name">${escapeHtml(user.username || "未知")}</span>
      <span class="um-caret">▾</span>
    </button>
    <div class="um-dropdown" id="umDropdown" hidden>
      <div class="um-info">
        <div class="um-info-name">${escapeHtml(user.username || "未知")}</div>
        <div class="um-info-tag">已登录</div>
      </div>
      <button class="um-item" data-act="change-pwd">🔑 修改密码</button>
      <button class="um-item danger" data-act="logout">⎋ 退出登录</button>
    </div>
  `;
  // 注入样式(只一次)
  if (!document.getElementById("um-styles")) {
    const s = document.createElement("style");
    s.id = "um-styles";
    s.textContent = `
      #${containerId}{position:relative;display:inline-block}
      .um-trigger{
        display:flex;align-items:center;gap:8px;
        padding:6px 10px 6px 8px;
        background:rgba(20,17,15,.6);
        border:1px solid var(--border-soft);
        border-radius:20px;
        font-family:var(--mono);font-size:11px;
        color:var(--text-2);
        cursor:pointer;
        transition:background .15s,border-color .15s;
      }
      .um-trigger:hover{background:var(--ink-3);border-color:var(--border)}
      .um-dot{width:7px;height:7px;border-radius:50%;background:var(--green);box-shadow:0 0 0 2px rgba(107,203,119,.18)}
      .um-name{color:var(--text);font-weight:500;letter-spacing:.04em}
      .um-caret{color:var(--text-3);font-size:9px;margin-top:-1px}
      .um-dropdown{
        position:absolute;right:0;top:calc(100% + 6px);
        min-width:200px;
        background:var(--ink-2);
        border:1px solid var(--border);
        border-radius:8px;
        box-shadow:0 16px 40px rgba(0,0,0,.5);
        padding:6px;
        z-index:60;
      }
      .um-info{padding:10px 12px 8px;border-bottom:1px solid var(--border-soft);margin-bottom:4px}
      .um-info-name{font-family:var(--mono);font-size:12px;color:var(--text);font-weight:500;margin-bottom:2px}
      .um-info-tag{font-family:var(--mono);font-size:9px;color:var(--green);letter-spacing:.1em;text-transform:uppercase}
      .um-item{
        display:block;width:100%;text-align:left;
        padding:9px 12px;
        background:transparent;border:none;
        border-radius:5px;
        color:var(--text);
        font-family:var(--sans);font-size:12px;
        cursor:pointer;
        transition:background .12s;
      }
      .um-item:hover{background:var(--ink-3)}
      .um-item.danger{color:var(--red)}
      .um-item.danger:hover{background:rgba(255,71,87,.12)}
    `;
    document.head.appendChild(s);
  }
  // 切换下拉
  const trigger = document.getElementById("umTrigger");
  const dropdown = document.getElementById("umDropdown");
  trigger.addEventListener("click", (e) => {
    e.stopPropagation();
    dropdown.hidden = !dropdown.hidden;
  });
  document.addEventListener("click", () => { dropdown.hidden = true; });
  // 操作
  host.querySelector('[data-act="change-pwd"]').addEventListener("click", () => {
    dropdown.hidden = true;
    // 在 settings 页直接弹 modal, 否则跳过去
    if (location.pathname.endsWith("/settings.html") || location.pathname.endsWith("/web/settings.html")) {
      const btn = document.getElementById("btn-change-pwd");
      if (btn) btn.click();
      else location.href = "/web/settings.html#account";
    } else {
      location.href = "/web/settings.html#account";
    }
  });
  host.querySelector('[data-act="logout"]').addEventListener("click", async () => {
    if (!confirm("确认退出登录?")) return;
    try { await Matrix.api.post("auth/logout", {}); } catch {}
    MatrixAuth.clearToken();
    location.href = "/web/login.html";
  });
};

function escapeHtml(s) {
  return String(s || "").replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");
}
