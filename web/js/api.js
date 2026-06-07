// web/js/api.js — 共享 API 工具
window.Matrix = {
  api: {
    async get(path) {
      const r = await fetch(`/v1/${path}`);
      if (!r.ok) throw new Error((await r.json()).detail || r.statusText);
      return r.json();
    },
    async post(path, body) {
      const r = await fetch(`/v1/${path}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      if (!r.ok) throw new Error((await r.json()).detail || r.statusText);
      return r.json();
    },
    async put(path, body) {
      const r = await fetch(`/v1/${path}`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      if (!r.ok) throw new Error((await r.json()).detail || r.statusText);
      return r.json();
    },
    async patch(path, body) {
      const r = await fetch(`/v1/${path}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      if (!r.ok) throw new Error((await r.json()).detail || r.statusText);
      return r.json();
    },
    async del(path) {
      const r = await fetch(`/v1/${path}`, { method: "DELETE" });
      if (!r.ok) throw new Error((await r.json()).detail || r.statusText);
      return r.json();
    },
    download(path, filename) {
      const a = document.createElement("a");
      a.href = `/v1/${path}`;
      a.download = filename;
      a.click();
    },
  },
  formatTime(sec) {
    const m = Math.floor(sec / 60);
    const s = Math.floor(sec % 60);
    return `${String(m).padStart(2, "0")}:${String(s).padStart(2, "0")}`;
  },
  formatDate(iso) {
    return new Date(iso).toLocaleString("zh-CN", { hour12: false });
  },
  qs(obj) {
    return new URLSearchParams(obj).toString();
  },
};
