/* common.js — 请求封装、提示、弹窗等共享工具 */
(function () {
  const ROLE = document.body.dataset.role || '';
  const USER = document.body.dataset.user || '';

  async function req(method, url, body) {
    const opt = { method, headers: {}, credentials: 'same-origin' };
    if (body !== undefined) {
      opt.headers['Content-Type'] = 'application/json';
      opt.body = JSON.stringify(body);
    }
    const res = await fetch(url, opt);
    let data = {};
    try { data = await res.json(); } catch (e) { data = {}; }
    if (res.status === 401) {
      location.href = '/login';
      throw new Error('登录已过期');
    }
    if (!res.ok || (data.code && data.code !== 0)) {
      const err = new Error(data.message || `请求失败（${res.status}）`);
      err.detail = data.detail;
      err.status = res.status;
      throw err;
    }
    return data;
  }

  const api = {
    get: (u) => req('GET', u),
    post: (u, b) => req('POST', u, b),
    put: (u, b) => req('PUT', u, b),
    del: (u) => req('DELETE', u),
  };

  function toast(msg, kind) {
    const box = document.getElementById('toasts');
    if (!box) return;
    const el = document.createElement('div');
    el.className = 'toast' + (kind ? ' ' + kind : '');
    el.textContent = msg;
    box.appendChild(el);
    setTimeout(() => el.remove(), kind === 'err' ? 4200 : 2600);
  }

  function esc(s) {
    return String(s === null || s === undefined ? '' : s)
      .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;').replace(/'/g, '&#39;');
  }

  function fmtHM(ts) {
    if (!ts) return '';
    return String(ts).slice(11, 16);
  }

  function fmtMD(ts) {
    if (!ts) return '';
    return String(ts).slice(5, 16);
  }

  function dur(min) {
    if (min === null || min === undefined) return '';
    if (min < 60) return min + ' 分钟';
    const h = Math.floor(min / 60), m = min % 60;
    return m ? `${h} 小时 ${m} 分` : `${h} 小时`;
  }

  function chip(label, color) {
    return `<span class="state-chip" style="background:${color}">${esc(label)}</span>`;
  }

  let modalOk = null;
  const mask = document.getElementById('modal-mask');
  function openModal(opts) {
    if (!mask) return;
    document.getElementById('m-title').textContent = opts.title || '操作';
    document.getElementById('m-body').innerHTML = opts.body || '';
    const okBtn = document.getElementById('m-ok');
    okBtn.textContent = opts.okText || '确认';
    okBtn.className = 'btn' + (opts.danger ? ' danger' : '');
    modalOk = opts.onOk || null;
    mask.classList.add('open');
    if (opts.after) opts.after();
  }
  function closeModal() { if (mask) mask.classList.remove('open'); modalOk = null; }

  document.addEventListener('DOMContentLoaded', () => {
    const cancel = document.getElementById('m-cancel');
    const ok = document.getElementById('m-ok');
    if (cancel) cancel.addEventListener('click', closeModal);
    if (ok) ok.addEventListener('click', async () => {
      if (!modalOk) return closeModal();
      ok.disabled = true;
      try { await modalOk(); } catch (e) { /* 校验未通过时保持弹窗打开 */ } finally { ok.disabled = false; }
    });
    if (mask) mask.addEventListener('click', (e) => { if (e.target === mask) closeModal(); });

    const clock = document.getElementById('clock');
    if (clock) {
      const tick = () => {
        const d = new Date();
        const p = (n) => String(n).padStart(2, '0');
        clock.textContent = `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())} ${p(d.getHours())}:${p(d.getMinutes())}:${p(d.getSeconds())}`;
      };
      tick(); setInterval(tick, 1000);
    }

    const logout = document.getElementById('logout');
    if (logout) logout.addEventListener('click', async () => {
      try { await api.post('/api/auth/logout'); } catch (e) { /* ignore */ }
      location.href = '/login';
    });

    const tabs = document.getElementById('tabs');
    if (tabs) {
      tabs.addEventListener('click', (e) => {
        const btn = e.target.closest('.tab');
        if (!btn) return;
        document.querySelectorAll('.tab').forEach((t) => t.classList.toggle('active', t === btn));
        document.querySelectorAll('.view').forEach((v) => v.classList.toggle('active', v.id === 'view-' + btn.dataset.view));
        document.dispatchEvent(new CustomEvent('view:change', { detail: btn.dataset.view }));
      });
    }
  });

  window.APP = { ROLE, USER, api, toast, esc, fmtHM, fmtMD, dur, chip, openModal, closeModal };
})();
