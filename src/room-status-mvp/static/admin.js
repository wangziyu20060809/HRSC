/* admin.js — 运营管理：概览 / 知识库 / 助手配置 / 审计 / 账号 */
(function () {
  const { api, toast, esc, fmtMD, dur } = window.APP;
  const $ = (s) => document.querySelector(s);

  /* ---------------- 概览 ---------------- */
  async function loadOverview() {
    try {
      const [d, a] = await Promise.all([api.get('/api/dashboard'), api.get('/api/admin/agent-stats')]);
      renderKpis(d);
      renderChart(d.series);
      renderOverdue(d.overdue_rooms);
      renderAgentStats(a);
      renderBaseline(d);
    } catch (e) { toast(e.message, 'err'); }
  }

  function renderKpis(d) {
    const gap = d.avg_clean_to_ready_min - 15;
    $('#ov-kpis').innerHTML = `
      <div class="kpi accent"><div class="label">可售率</div><div class="value">${d.sellable_rate}%</div><div class="foot">${d.sellable} / ${d.total} 间可售</div></div>
      <div class="kpi"><div class="label">已清扫 → 可售（7 天均值）</div><div class="value">${d.avg_clean_to_ready_min}<span style="font-size:13px;font-weight:400"> 分钟</span></div>
        <div class="foot">P90 ${d.p90_clean_to_ready_min} 分 · ${gap > 0 ? '距 15 分目标还差 ' + gap.toFixed(1) + ' 分' : '已达 15 分目标'}</div></div>
      <div class="kpi ${d.overdue.total ? 'alert' : ''}"><div class="label">超时房间</div><div class="value">${d.overdue.total}</div><div class="foot">待查房 ${d.overdue.clean} · 查房 ${d.overdue.inspecting} · 待清扫 ${d.overdue.dirty}</div></div>
      <div class="kpi"><div class="label">本周拦截</div><div class="value">${d.blocked_week}</div><div class="foot">基线 24 次/周 · 目标 5 次/周</div></div>
      <div class="kpi"><div class="label">今日入住</div><div class="value">${d.checkins_today}</div><div class="foot">未完成任务 ${d.tasks_open} 项</div></div>
      <div class="kpi"><div class="label">助手提案采纳率</div><div class="value">${d.ai_adoption}%</div><div class="foot">待确认 ${d.pending_actions} 项</div></div>`;
  }

  function renderChart(series) {
    if (!series || !series.length) { $('#chart').innerHTML = '<div class="empty">暂无数据</div>'; return; }
    const W = 560, H = 168, pad = 26, bottom = 26;
    const max = Math.max(...series.map((s) => Math.max(s.interventions, s.ready)), 4);
    const bw = (W - pad * 2) / series.length;
    const y = (v) => H - bottom - (v / max) * (H - bottom - 14);
    let bars = '';
    series.forEach((s, i) => {
      const x = pad + i * bw;
      const w = Math.min(14, bw / 3);
      bars += `<rect x="${x + bw / 2 - w - 2}" y="${y(s.interventions)}" width="${w}" height="${H - bottom - y(s.interventions)}" rx="2" fill="#b4443a" opacity=".82"></rect>`;
      bars += `<rect x="${x + bw / 2 + 2}" y="${y(s.ready)}" width="${w}" height="${H - bottom - y(s.ready)}" rx="2" fill="#2d654f" opacity=".85"></rect>`;
      bars += `<text x="${x + bw / 2}" y="${H - 8}" font-size="10" fill="#7d8f85" text-anchor="middle">${s.date}</text>`;
      if (s.interventions) bars += `<text x="${x + bw / 2 - w / 2 - 2}" y="${y(s.interventions) - 4}" font-size="9.5" fill="#b4443a" text-anchor="middle">${s.interventions}</text>`;
      if (s.ready) bars += `<text x="${x + bw / 2 + w / 2 + 2}" y="${y(s.ready) - 4}" font-size="9.5" fill="#2d654f" text-anchor="middle">${s.ready}</text>`;
    });
    const grid = [0, .5, 1].map((p) => {
      const yy = y(max * p);
      return `<line x1="${pad}" x2="${W - pad}" y1="${yy}" y2="${yy}" stroke="#eef2ea" stroke-width="1"></line>
        <text x="${pad - 6}" y="${yy + 3}" font-size="9.5" fill="#a6b3aa" text-anchor="end">${Math.round(max * p)}</text>`;
    }).join('');
    $('#chart').innerHTML = `<svg class="chart" viewBox="0 0 ${W} ${H}" preserveAspectRatio="none">${grid}${bars}</svg>
      <div class="chart-legend"><span><i style="background:#b4443a"></i>入住闸门拦截</span><span><i style="background:#2d654f"></i>转为可售的房间数</span></div>`;
  }

  function renderOverdue(rooms) {
    $('#ov-overdue').innerHTML = rooms && rooms.length ? `<table><thead><tr><th>房间</th><th>状态</th><th>等待</th></tr></thead>
      <tbody>${rooms.map((r) => `<tr><td><b>${esc(r.room_no)}</b></td>
        <td><span class="state-chip" style="background:${r.state_color}">${esc(r.state_label)}</span></td>
        <td>${dur(r.age_min)} <span class="tag high">超时</span></td></tr>`).join('')}</tbody></table>`
      : '<div class="empty">没有超时房间</div>';
  }

  function renderAgentStats(a) {
    if (!a.sessions_7d) {
      $('#ov-agent').innerHTML = '<div class="empty" style="padding:24px 0">员工还没有用过值班助手。到员工端「值班助手」问一句「803 能入住吗」，这里就会出现会话数、平均耗时与工具调用分布。</div>';
      return;
    }
    const tools = (a.tools || []).slice(0, 6).map(([n, c]) => `<span class="trace-chip">${esc(n)} × ${c}</span>`).join('');
    $('#ov-agent').innerHTML = `
      <div class="kpis" style="grid-template-columns:repeat(3,1fr);margin-bottom:12px">
        <div class="kpi"><div class="label">会话</div><div class="value" style="font-size:22px">${a.sessions_7d}</div></div>
        <div class="kpi"><div class="label">平均耗时</div><div class="value" style="font-size:22px">${a.avg_latency_ms}<span style="font-size:12px">ms</span></div></div>
        <div class="kpi"><div class="label">平均工具步数</div><div class="value" style="font-size:22px">${a.avg_steps}</div></div>
      </div>
      <div class="hint">提案：确认 ${a.actions.confirmed} · 忽略 ${a.actions.rejected} · 待处理 ${a.actions.pending} · 失败 ${a.actions.failed}，采纳率 ${a.actions.adoption}%</div>
      <div class="trace" style="margin-top:8px">${tools || '<span class="hint">暂无工具调用</span>'}</div>`;
  }

  function renderBaseline(d) {
    const b = d.baseline;
    $('#ov-baseline').innerHTML = `
      <table><tbody>
        <tr><td>高峰入住等待</td><td>基线 <b>${b.wait_min}</b> 分钟 → 目标 <b>${b.target_wait_min}</b> 分钟</td></tr>
        <tr><td>替代口径</td><td>「已清扫 → 可售」当前 <b>${d.avg_clean_to_ready_min}</b> 分钟（P90 ${d.p90_clean_to_ready_min}）</td></tr>
        <tr><td>房态错误</td><td>基线 <b>${b.errors_per_week}</b> 次/周 → 目标 <b>${b.target_errors}</b> 次/周</td></tr>
        <tr><td>替代口径</td><td>入住闸门拦截 <b>${d.blocked_week}</b> 次（拦截即避免的错误）</td></tr>
        <tr><td>SLA 阈值</td><td>待清扫 ${d.limits.dirty} 分 · 待查房 ${d.limits.clean} 分 · 查房 ${d.limits.inspecting} 分</td></tr>
      </tbody></table>
      <div class="hint" style="margin-top:8px">说明：等待时长需门店按样本补测；本系统用「已清扫→可售」与「拦截次数」作为可自动计算的代理指标。</div>`;
  }

  /* ---------------- 知识库 ---------------- */
  let kbDocs = [];
  let kbCurrent = null;

  async function loadKB() {
    try {
      const d = await api.get('/api/kb/docs');
      kbDocs = d.docs;
      $('#kb-stats').textContent = `${d.stats.docs} 篇 · ${d.stats.chunks} 片 · 平均 ${d.stats.avg_chunk_len} 字/片`;
      $('#kb-list').innerHTML = d.docs.length ? `<table><thead><tr><th>标题</th><th>分类</th><th>字数</th><th>更新</th></tr></thead>
        <tbody>${d.docs.map((x) => `<tr data-doc="${x.id}" style="cursor:pointer">
          <td><b>${esc(x.title)}</b></td><td><span class="tag">${esc(x.category)}</span></td>
          <td class="hint">${x.size}</td><td class="hint">${esc(fmtMD(x.updated_at))}</td></tr>`).join('')}</tbody></table>`
        : '<div class="empty">知识库为空，点击「新建」写入第一篇制度</div>';
      // 首次进入且未选中任何文档时，默认打开第一篇，避免右侧编辑区一片空白
      if (!kbCurrent && d.docs.length) {
        const first = document.querySelector('[data-doc]');
        if (first) first.click();
      }
    } catch (e) { toast(e.message, 'err'); }
  }

  document.addEventListener('click', async (e) => {
    const row = e.target.closest('[data-doc]');
    if (!row) return;
    try {
      const d = await api.get('/api/kb/docs/' + row.dataset.doc);
      kbCurrent = d.doc.id;
      $('#kb-title').value = d.doc.title;
      $('#kb-cat').value = d.doc.category;
      $('#kb-body').value = d.doc.body;
      $('#kb-test-result').innerHTML = `<div class="hint">已切片 ${d.chunks.length} 段：` +
        d.chunks.map((c) => `第${c.ord + 1}段 ${c.text.length}字`).join(' · ') + '</div>';
    } catch (err) { toast(err.message, 'err'); }
  });

  $('#kb-new').addEventListener('click', () => {
    kbCurrent = null;
    $('#kb-title').value = ''; $('#kb-cat').value = '制度'; $('#kb-body').value = '';
    $('#kb-test-result').innerHTML = '';
  });

  $('#kb-save').addEventListener('click', async () => {
    const title = $('#kb-title').value.trim();
    const body = $('#kb-body').value.trim();
    if (!title || !body) return toast('标题与正文不能为空', 'warn');
    try {
      const d = await api.post('/api/kb/docs', { title, body, category: $('#kb-cat').value.trim() || '制度' });
      toast(d.message); loadKB();
    } catch (e) { toast(e.message, 'err'); }
  });

  $('#kb-delete').addEventListener('click', async () => {
    if (!kbCurrent) return toast('请先在左侧选择文档', 'warn');
    window.APP.openModal({
      title: '删除文档',
      body: '<div class="hint">删除后相关切片立即失效，助手将检索不到这篇制度。</div>',
      okText: '确认删除', danger: true,
      onOk: async () => {
        try {
          const d = await api.del('/api/kb/docs/' + kbCurrent);
          toast(d.message); kbCurrent = null;
          $('#kb-title').value = ''; $('#kb-body').value = '';
          window.APP.closeModal(); loadKB();
        } catch (e) { toast(e.message, 'err'); }
      },
    });
  });

  $('#kb-reindex').addEventListener('click', async () => {
    try { const d = await api.post('/api/kb/reindex'); toast(d.message); loadKB(); }
    catch (e) { toast(e.message, 'err'); }
  });

  $('#kb-test').addEventListener('click', async () => {
    const q = $('#kb-title').value.trim();
    if (!q) return toast('先在标题里写个问题再测试', 'warn');
    const query = prompt('检索测试：输入一条员工可能问的话', '已清扫能不能办入住');
    if (!query) return;
    try {
      const d = await api.post('/api/kb/search', { query, top_k: 3 });
      $('#kb-test-result').innerHTML = d.hits.length
        ? d.hits.map((h) => `<div class="cite" style="margin-bottom:6px"><b>${esc(h.ref)}</b> · bm25 ${h.bm25}<br>${esc(h.text.slice(0, 120))}</div>`).join('')
        : '<div class="hint">没有命中</div>';
    } catch (e) { toast(e.message, 'err'); }
  });

  /* ---------------- 助手配置 ---------------- */
  async function loadAgent() {
    try {
      const [s, status] = await Promise.all([api.get('/api/admin/settings'), api.get('/api/agent/status')]);
      const v = s.settings;
      $('#settings-form').innerHTML = `
        <div class="inline-form" style="margin-bottom:10px">
          <div class="field" style="width:150px"><label>待查房阈值（分）</label><input id="s-clean" type="number" min="1" value="${v.sla_clean_wait_min}"></div>
          <div class="field" style="width:150px"><label>查房出结论（分）</label><input id="s-inspect" type="number" min="1" value="${v.sla_inspect_min}"></div>
          <div class="field" style="width:150px"><label>待清扫阈值（分）</label><input id="s-dirty" type="number" min="1" value="${v.sla_dirty_min}"></div>
        </div>
        <div class="inline-form" style="margin-bottom:12px">
          <label style="display:flex;gap:7px;align-items:center"><input type="checkbox" id="s-enabled" ${v.agent_enabled === '1' ? 'checked' : ''}> 启用助手</label>
          <label style="display:flex;gap:7px;align-items:center;margin-left:14px"><input type="checkbox" id="s-write" ${v.agent_allow_write_tools === '1' ? 'checked' : ''}> 允许生成改房态提案</label>
        </div>
        <div class="field"><label>系统提示词（可改，恢复默认见下方按钮）</label>
          <textarea id="s-prompt" rows="12" style="font-family:var(--mono);font-size:12px">${esc(v.agent_system_prompt)}</textarea></div>
        <div class="actions-row">
          <button class="btn" id="s-save">保存</button>
          <button class="btn ghost" id="s-reset">恢复默认提示词</button>
        </div>
        <div class="hint" style="margin-top:10px">当前模型：${status.llm_ready ? esc(status.model) : '未配置密钥，规则模式'}；阈值调大会写审计，避免用放宽红线美化指标。</div>`;

      $('#s-save').addEventListener('click', async () => {
        try {
          const d = await api.put('/api/admin/settings', {
            settings: {
              sla_clean_wait_min: $('#s-clean').value,
              sla_inspect_min: $('#s-inspect').value,
              sla_dirty_min: $('#s-dirty').value,
              agent_enabled: $('#s-enabled').checked ? '1' : '0',
              agent_allow_write_tools: $('#s-write').checked ? '1' : '0',
              agent_system_prompt: $('#s-prompt').value,
            },
          });
          toast(d.message);
        } catch (e) { toast(e.message, 'err'); }
      });
      $('#s-reset').addEventListener('click', () => { $('#s-prompt').value = s.default_prompt; toast('已填入默认提示词，保存后生效'); });

      $('#tools-list').innerHTML = `<table><thead><tr><th>工具</th><th>类型</th><th>说明</th></tr></thead>
        <tbody>${status.tools.map((t) => `<tr><td><code style="font-size:11.5px">${esc(t.name)}</code></td>
          <td><span class="tag ${t.write ? 'agent' : 'sys'}">${t.write ? '提案' : '只读'}</span></td>
          <td class="hint">${esc(t.desc)}</td></tr>`).join('')}</tbody></table>`;
    } catch (e) { toast(e.message, 'err'); }
  }

  /* ---------------- 审计 ---------------- */
  async function loadAudit(q) {
    try {
      const d = await api.get('/api/admin/audit?limit=120' + (q ? '&actor=' + encodeURIComponent(q) : ''));
      $('#audit-table').innerHTML = d.items.length ? `<table><thead><tr><th>时间</th><th>操作人</th><th>岗位</th><th>动作</th><th>对象</th><th>详情</th></tr></thead>
        <tbody>${d.items.map((x) => `<tr>
          <td class="hint">${esc(fmtMD(x.created_at))}</td>
          <td>${esc(x.actor)}</td><td class="hint">${esc(x.role_label)}</td>
          <td><span class="tag ${x.action.startsWith('agent') ? 'agent' : ''}">${esc(x.action)}</span></td>
          <td><b>${esc(x.target || '—')}</b></td><td>${esc(x.detail || '')}</td></tr>`).join('')}</tbody></table>`
        : '<div class="empty">没有记录</div>';
    } catch (e) { toast(e.message, 'err'); }
  }

  $('#audit-search').addEventListener('click', () => loadAudit($('#audit-q').value.trim()));
  $('#audit-q').addEventListener('keydown', (e) => { if (e.key === 'Enter') $('#audit-search').click(); });

  /* ---------------- 账号 ---------------- */
  async function loadUsers() {
    try {
      const d = await api.get('/api/admin/users');
      $('#user-table').innerHTML = `<table><thead><tr><th>账号</th><th>姓名</th><th>岗位</th><th>状态</th><th>创建</th><th>操作</th></tr></thead>
        <tbody>${d.users.map((u) => `<tr>
          <td><code style="font-size:11.5px">${esc(u.username)}</code></td><td>${esc(u.display)}</td>
          <td><span class="tag ${u.role === 'admin' ? 'agent' : 'sys'}">${esc(u.role_label)}</span> <span class="hint">${esc(u.post || '')}</span></td>
          <td>${u.is_active ? '正常' : '<span class="tag high">已停用</span>'}</td>
          <td class="hint">${esc(fmtMD(u.created_at))}</td>
          <td><button class="btn ghost small" data-uid="${u.id}" data-ua="toggle">${u.is_active ? '停用' : '启用'}</button>
              <button class="btn ghost small" data-uid="${u.id}" data-ua="reset">重置口令</button></td></tr>`).join('')}</tbody></table>`;
    } catch (e) { toast(e.message, 'err'); }
  }

  document.addEventListener('click', async (e) => {
    const b = e.target.closest('[data-uid]');
    if (!b) return;
    if (b.dataset.ua === 'toggle') {
      try { const d = await api.post(`/api/admin/users/${b.dataset.uid}/toggle`); toast(d.message); loadUsers(); }
      catch (err) { toast(err.message, 'err'); }
      return;
    }
    window.APP.openModal({
      title: '重置口令',
      body: '<div class="field"><label>新口令（≥6 位）</label><input id="reset-pwd" type="password"></div>',
      okText: '重置',
      onOk: async () => {
        const pwd = $('#reset-pwd').value;
        if (pwd.length < 6) { toast('口令至少 6 位', 'warn'); throw new Error('short'); }
        try {
          const d = await api.post(`/api/admin/users/${b.dataset.uid}/reset-password`, { password: pwd });
          toast(d.message); window.APP.closeModal();
        } catch (err) { toast(err.message, 'err'); }
      },
    });
  });

  $('#u-create').addEventListener('click', async () => {
    try {
      const d = await api.post('/api/admin/users', {
        username: $('#u-username').value.trim(),
        display: $('#u-display').value.trim(),
        role: $('#u-role').value,
        post: $('#u-post').value.trim(),
        password: $('#u-pwd').value,
      });
      toast(d.message);
      $('#u-username').value = ''; $('#u-display').value = ''; $('#u-pwd').value = '';
      loadUsers();
    } catch (e) { toast(e.message, 'err'); }
  });

  /* ---------------- 启动 ---------------- */
  async function initStatus() {
    try {
      const s = await api.get('/api/agent/status');
      const el = $('#llm-badge');
      el.textContent = s.llm_ready ? `助手 · ${s.model}` : '助手 · 规则模式';
      el.className = 'llm-badge ' + (s.llm_ready ? 'on' : 'off');
    } catch (e) { /* ignore */ }
  }

  document.addEventListener('view:change', (e) => {
    if (e.detail === 'kb') loadKB();
    if (e.detail === 'agent') loadAgent();
    if (e.detail === 'audit') loadAudit();
    if (e.detail === 'users') loadUsers();
  });

  loadOverview();
  initStatus();
  setInterval(() => { if ($('#view-overview').classList.contains('active')) loadOverview(); }, 30000);
})();
