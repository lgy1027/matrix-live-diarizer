// web/js/util.js — 通用工具函数 + Modal/toast
// 加载顺序: api.js → i18n.js → util.js → 主 script
// 假设全局: window.Matrix (api.js 提供), window.t (i18n.js 提供)

/* DOM helpers */
const $ = (s, r=document) => r.querySelector(s);
const $$ = (s, r=document) => Array.from(r.querySelectorAll(s));
const esc = window.Matrix ? Matrix.escape : (s => String(s ?? ""));

/* format helpers */
const fmtSec = (s) => {
  if (!s || isNaN(s)) return "00:00";
  const m = Math.floor(s/60);
  const r = Math.floor(s%60);
  return `${String(m).padStart(2,"0")}:${String(r).padStart(2,"0")}`;
};

const fmtClock = (s) => {
  const h = Math.floor(s/3600);
  const m = Math.floor((s%3600)/60);
  const r = Math.floor(s%60);
  return h > 0
    ? `${h}:${String(m).padStart(2,"0")}:${String(r).padStart(2,"0")}`
    : `${String(m).padStart(2,"0")}:${String(r).padStart(2,"0")}`;
};

const fmtRel = (iso) => {
  if (!iso) return "—";
  const t = new Date(iso).getTime();
  const d = (Date.now() - t) / 1000;
  if (d < 60) return "just now";
  if (d < 3600) return Math.floor(d/60) + "m ago";
  if (d < 86400) return Math.floor(d/3600) + "h ago";
  if (d < 604800) return Math.floor(d/86400) + "d ago";
  return new Date(iso).toLocaleDateString("zh-CN", {month:"short", day:"numeric"});
};

const fmtSize = (mb) => mb ? mb.toFixed(1) + " MB" : "—";

/* toast — 简单消息提示 */
const toast = (msg, kind="") => {
  const el = $("#toast");
  el.textContent = msg;
  el.className = "toast show " + kind;
  clearTimeout(toast._t);
  toast._t = setTimeout(() => el.classList.remove("show"), 3200);
};

/* spk helpers — 纯函数, 不依赖 state(颜色索引由调用方维护) */
const spkInitial = (name) => {
  if (!name) return "·";
  return name.replace(/^Spk_/, "").slice(0, 1).toUpperCase();
};

const spkPalette = ["#FF6B35","#4ECDC4","#D4A574","#C589E8","#7BC96F","#FFB347","#5DADE2","#EC7063"];

const spkColorIndex = (id) => {
  if (!id) return 0;
  let h = 0;
  for (let i = 0; i < id.length; i++) h = (h * 31 + id.charCodeAt(i)) >>> 0;
  return h % 8;
};

/* Modal 组件 (Boutique Audio Atelier 风格) */
/*
 * 3 种类型:
 *   Modal.confirm(opts) -> Promise<bool>
 *   Modal.prompt(opts)  -> Promise<string|null>  (取消时返回 null)
 *   Modal.list(opts)    -> Promise<bool>
 * 通用 opts: { title, body, confirmText, cancelText, danger, persistent }
 * prompt 额外: { placeholder, initialValue, validate }
 * list  额外: { items, itemCount }
 */
const Modal = (() => {
  function createBackdrop() {
    let bd = document.getElementById('modalBackdrop');
    if (!bd) {
      bd = document.createElement('div');
      bd.id = 'modalBackdrop';
      bd.className = 'modal-backdrop';
      document.body.appendChild(bd);
    }
    return bd;
  }

  function show(opts) {
    return new Promise(resolve => {
      const bd = createBackdrop();
      bd._modal = { opts, resolve };
      bd.innerHTML = '';

      const m = document.createElement('div');
      m.className = 'modal';

      // title
      const h3 = document.createElement('h3');
      h3.textContent = opts.title || '';
      m.appendChild(h3);

      // body
      if (opts.body) {
        const body = document.createElement('div');
        body.className = 'body';
        if (opts.bodyIsHtml) body.innerHTML = opts.body;
        else body.textContent = opts.body;
        m.appendChild(body);
      }

      // input
      let inputEl = null;
      if (opts.input) {
        inputEl = document.createElement('input');
        inputEl.className = 'modal-input';
        inputEl.type = 'text';
        inputEl.placeholder = opts.placeholder || '';
        inputEl.value = opts.initialValue || '';
        m.appendChild(inputEl);
      }

      // list
      if (opts.list) {
        const ul = document.createElement('ul');
        ul.className = 'modal-list';
        (opts.items || []).forEach(it => {
          const li = document.createElement('li');
          li.className = 'modal-list-item';
          li.textContent = typeof it === 'string' ? it : (it.label || '');
          ul.appendChild(li);
        });
        m.appendChild(ul);
      }

      // buttons
      const buttons = document.createElement('div');
      buttons.className = 'modal-buttons';
      if (!opts.persistent) {
        const cancel = document.createElement('button');
        cancel.className = 'btn ghost';
        cancel.textContent = opts.cancelText || (window.t ? t('btn.cancel') : 'Cancel');
        cancel.onclick = () => close(bd, null);
        buttons.appendChild(cancel);
      }
      const confirm = document.createElement('button');
      confirm.className = 'btn' + (opts.danger ? ' danger' : '');
      confirm.textContent = opts.confirmText || 'OK';
      confirm.onclick = () => {
        if (opts.input && inputEl) {
          const v = inputEl.value;
          if (opts.validate && !opts.validate(v)) return;
          close(bd, v);
          return;
        }
        close(bd, true);
      };
      buttons.appendChild(confirm);
      m.appendChild(buttons);
      bd.appendChild(m);

      // ESC 关闭
      const escHandler = (e) => {
        if (e.key === 'Escape' && !opts.persistent) close(bd, null);
        else if (e.key === 'Enter' && opts.input) {
          confirm.click();
        }
      };
      bd._escHandler = escHandler;
      document.addEventListener('keydown', escHandler);

      // 点击背景关闭(默认)
      if (!opts.persistent) {
        bd.onclick = (e) => { if (e.target === bd) close(bd, null); };
      }

      // 自动聚焦
      setTimeout(() => {
        if (inputEl) inputEl.focus();
        else confirm.focus();
      }, 50);
    });
  }

  function close(bd, result) {
    if (!bd._modal) return;
    document.removeEventListener('keydown', bd._escHandler);
    bd._modal.resolve(result);
    bd._modal = null;
    bd.innerHTML = '';
    bd.onclick = null;
  }

  return {
    show,
    confirm: (opts) => show({ ...opts, input: false }),
    prompt: (opts) => show({ ...opts, input: true }),
    list: (opts) => show({ ...opts, input: false, list: true }),
  };
})();
