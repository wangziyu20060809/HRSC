// 测试证据截图驱动：一次启动 Edge，按计划顺序执行步骤并截图
// 用法：node tools/capture.js plans/xxx.json
// 计划格式：[{ "out":"x.png", "origin":"http://127.0.0.1:8101", "login":["front","Front@123"],
//             "url":"/staff", "js":"...", "wait":1500, "height":1000 }]
const { spawn } = require('child_process');
const fs = require('fs');
const path = require('path');

const EDGE = 'C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe';
const PORT = 9700 + Math.floor(Math.random() * 200);
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

/** 注入到页面的证据面板与工具函数 */
const PRELUDE = `
window.__pending = [];
window.__toast = (m) => {
  let el = document.getElementById('__toast');
  if (!el) { el = document.createElement('div'); el.id = '__toast';
    el.style.cssText = 'position:fixed;left:50%;top:12%;transform:translateX(-50%);z-index:99999;background:#1F3D33;color:#fff;padding:10px 18px;border-radius:8px;font:14px/1.5 "Microsoft YaHei";box-shadow:0 8px 24px rgba(0,0,0,.25)';
    document.body.appendChild(el); }
  el.textContent = m;
};
/** 把真实请求/响应渲染成证据面板（测试专用） */
window.__ev = async (title, items) => {
  const rows = [];
  for (const it of items) {
    if (it.wait) { await new Promise(r => setTimeout(r, it.wait)); }
    let status = it.status || '-', body = it.body || '';
    if (it.fetch) {
      const opt = it.fetch;
      const res = await fetch(opt.url, {
        method: opt.method || 'GET',
        headers: opt.body ? { 'Content-Type': 'application/json' } : undefined,
        body: opt.body ? JSON.stringify(opt.body) : undefined,
        credentials: 'include',
      });
      status = res.status;
      const txt = await res.text();
      try {
        let obj = JSON.parse(txt);
        const pick = (it.pick || (it.fetch && it.fetch.pick));
        if (pick && obj && typeof obj === 'object') {
          const sub = {};
          for (const k of pick) sub[k] = obj[k];
          obj = sub;
        }
        body = JSON.stringify(obj, null, 1);
      } catch (e) { body = txt.slice(0, 400); }
      if (body.length > 620) body = body.slice(0, 620) + ' …';
    }
    rows.push({ label: it.label, req: it.req || '', status, body: String(body) });
  }
  const color = (s) => (String(s).startsWith('2') ? '#2d654f' : String(s).startsWith('4') ? '#b4443a' : '#5E6B64');
  document.documentElement.innerHTML = '<body style="margin:0;background:#F3F5F2;font:13px/1.6 \\'Microsoft YaHei\\',sans-serif;color:#1E2A25">' +
    '<div style="max-width:1180px;margin:24px auto;background:#fff;border:1px solid #DDE5DE;border-radius:10px;overflow:hidden;box-shadow:0 6px 22px rgba(31,61,51,.08)">' +
    '<div style="background:#1F3D33;color:#fff;padding:14px 20px;font-size:15px;font-weight:600">' + title +
    '<span style="float:right;font-weight:400;font-size:12px;opacity:.8">接口证据面板 · 请求与响应均为真实调用</span></div>' +
    '<table style="width:100%;border-collapse:collapse"><thead><tr style="background:#EDF3EF;color:#1F3D33">' +
    '<th style="text-align:left;padding:9px 12px;width:170px;border-bottom:1px solid #DDE5DE">步骤</th>' +
    '<th style="text-align:left;padding:9px 12px;width:330px;border-bottom:1px solid #DDE5DE">请求</th>' +
    '<th style="text-align:center;padding:9px 12px;width:70px;border-bottom:1px solid #DDE5DE">状态</th>' +
    '<th style="text-align:left;padding:9px 12px;border-bottom:1px solid #DDE5DE">返回</th></tr></thead><tbody>' +
    rows.map((r, i) => '<tr style="background:' + (i % 2 ? '#F8FAF8' : '#fff') + ';vertical-align:top">' +
      '<td style="padding:9px 12px;border-bottom:1px solid #EEF2EE">' + r.label.replace(/</g, '&lt;') + '</td>' +
      '<td style="padding:9px 12px;border-bottom:1px solid #EEF2EE;font-family:Consolas,monospace;font-size:12px;color:#4A5A52">' + r.req.replace(/</g, '&lt;') + '</td>' +
      '<td style="padding:9px 12px;border-bottom:1px solid #EEF2EE;text-align:center;font-weight:700;color:' + color(r.status) + '">' + r.status + '</td>' +
      '<td style="padding:9px 12px;border-bottom:1px solid #EEF2EE;font-family:Consolas,monospace;font-size:11.5px;color:#2B3A32;white-space:pre-wrap">' + r.body.replace(/</g, '&lt;') + '</td></tr>').join('') +
    '</tbody></table></div></body>';
  return rows.length;
};
`;

function cdp(ws, id, method, params) {
  return new Promise((resolve, reject) => {
    const onMsg = (ev) => {
      const m = JSON.parse(ev.data);
      if (m.id === id) {
        ws.removeEventListener('message', onMsg);
        m.error ? reject(new Error(method + ':' + JSON.stringify(m.error))) : resolve(m.result);
      }
    };
    ws.addEventListener('message', onMsg);
    ws.send(JSON.stringify({ id, method, params }));
    setTimeout(() => reject(new Error(method + ' timeout')), 60000);
  });
}

(async () => {
  const planPath = process.argv[2];
  const plan = JSON.parse(fs.readFileSync(planPath, 'utf8'));
  const outDir = process.argv[3] || path.dirname(planPath);
  fs.mkdirSync(outDir, { recursive: true });

  const profile = `C:\\Users\\kangr\\Desktop\\酒店房态与入住协同\\.tmpshot\\cap${PORT}`;
  const proc = spawn(EDGE, ['--headless=new', `--remote-debugging-port=${PORT}`, `--user-data-dir=${profile}`,
    '--disable-gpu', '--no-first-run', '--hide-scrollbars', '--window-size=1440,1000', 'about:blank'],
    { stdio: 'ignore' });

  let list = null;
  for (let i = 0; i < 40; i++) {
    await sleep(400);
    try { list = await (await fetch(`http://127.0.0.1:${PORT}/json/list`)).json(); if (list.length) break; } catch (e) {}
  }
  if (!list || !list.length) { console.error('edge not ready'); proc.kill(); process.exit(1); }

  const ws = new WebSocket(list.find((t) => t.type === 'page').webSocketDebuggerUrl);
  await new Promise((r) => ws.addEventListener('open', r));
  await cdp(ws, 1, 'Page.enable', {});
  await cdp(ws, 2, 'Runtime.enable', {});

  let id = 10;
  let current = null;
  const evalJs = async (expr) => cdp(ws, ++id, 'Runtime.evaluate', { expression: expr, awaitPromise: true, returnByValue: true });

  for (const step of plan) {
    if (current !== step.origin) {
      await cdp(ws, ++id, 'Page.navigate', { url: step.origin + '/login' });
      await sleep(900);
      await evalJs(PRELUDE);
      current = step.origin;
    }
    if (step.cookie) {
      // 复用事先拿到的会话（故障注入时登录接口本身也会失败，不能现场登录）
      await cdp(ws, ++id, 'Network.enable', {});
      await cdp(ws, ++id, 'Network.setCookie', {
        name: 'rs_token', value: step.cookie, domain: new URL(step.origin).hostname, path: '/',
      });
    }
    if (step.login) {
      const [u, p] = step.login;
      const r = await evalJs(`fetch('/api/auth/login',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({username:'${u}',password:'${p}'}),credentials:'include'}).then(r=>r.status)`);
      process.stdout.write(`[login ${u}] ${r.result.value} `);
    }
    if (step.url) {
      await cdp(ws, ++id, 'Page.navigate', { url: step.origin + step.url });
      await sleep(step.load || 1600);
      await evalJs(PRELUDE);
    }
    if (step.js) {
      const r = await evalJs(step.js);
      if (r.result && r.result.value !== undefined) process.stdout.write(`[js]${JSON.stringify(r.result.value).slice(0, 120)} `);
    }
    await sleep(step.wait === undefined ? 1200 : step.wait);
    const h = step.height || 1000;
    await cdp(ws, ++id, 'Emulation.setDeviceMetricsOverride', { width: 1440, height: h, deviceScaleFactor: 1, mobile: false });
    await sleep(300);
    const shot = await cdp(ws, ++id, 'Page.captureScreenshot', { format: 'png', captureBeyondViewport: true });
    fs.writeFileSync(path.join(outDir, step.out), Buffer.from(shot.data, 'base64'));
    console.log('saved', step.out);
  }
  ws.close();
  proc.kill();
  process.exit(0);
})().catch((e) => { console.error('ERR', e.message); process.exit(1); });
