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
