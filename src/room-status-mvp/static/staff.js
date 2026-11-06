/* staff.js — 员工工作台：房态看板 / 入住闸门 / 待办 / 交接 / 助手 */
(function () {
  const { api, toast, esc, fmtHM, dur, chip, ROLE } = window.APP;
  const $ = (s) => document.querySelector(s);

  const STATE = { rooms: [], counts: {}, states: [], limits: {}, filter: '', current: null, taskStatus: 'open,doing' };
  let sessionId = null;

  /* ---------------- 看板 ---------------- */
  async function loadBoard(silent) {
    try {
      const data = await api.get('/api/rooms');
      STATE.rooms = data.rooms;
      STATE.counts = data.counts;
      STATE.states = data.states;
      STATE.limits = data.limits;
      renderKpis(data);
      renderLegend(data.states);
      renderBoard();
    } catch (e) {
      if (!silent) toast(e.message, 'err');
    }
  }

  function renderKpis(data) {
    const c = data.counts;
    const overdue = data.rooms.filter((r) => r.overdue).length;
    const total = data.rooms.length;
    const rate = total ? Math.round((c.ready || 0) / total * 100) : 0;
    $('#kpis').innerHTML = `
      <div class="kpi accent"><div class="label">可售（可办入住）</div><div class="value">${c.ready || 0}</div><div class="foot">占全部房间 ${rate}%</div></div>
      <div class="kpi"><div class="label">已清扫待查房</div><div class="value">${c.clean || 0}</div><div class="foot">不等于可售</div></div>
      <div class="kpi"><div class="label">查房中</div><div class="value">${c.inspecting || 0}</div><div class="foot">阈值 ${data.limits.inspecting} 分钟出结论</div></div>
      <div class="kpi"><div class="label">清扫中 / 待清扫</div><div class="value">${(c.cleaning || 0) + (c.dirty || 0)}</div><div class="foot">清扫完成后仍需查房</div></div>
      <div class="kpi"><div class="label">在住</div><div class="value">${c.occupied || 0}</div><div class="foot">退房后转待清扫</div></div>
      <div class="kpi ${overdue ? 'alert' : ''}"><div class="label">超时房间</div><div class="value">${overdue}</div><div class="foot">待查房阈值 ${data.limits.clean} 分钟</div></div>`;
  }

  function renderLegend(states) {
    $('#legend').innerHTML = states
      .map((s) => `<span><i style="background:${s.color}"></i>${esc(s.label)}</span>`)
      .join('');
  }

  function renderBoard() {
    const rooms = STATE.filter ? STATE.rooms.filter((r) => r.state === STATE.filter) : STATE.rooms;
    if (!rooms.length) { $('#board').innerHTML = '<div class="empty">该筛选下没有房间</div>'; return; }
    const floors = [...new Set(rooms.map((r) => r.floor))].sort((a, b) => a - b);
    $('#board').innerHTML = floors.map((f) => {
      const list = rooms.filter((r) => r.floor === f);
      const ready = list.filter((r) => r.state === 'ready').length;
      const od = list.filter((r) => r.overdue).length;
      return `<div class="floor-block">
        <div class="floor-head"><h4>${f} 层</h4><span class="meta">${list.length} 间 · 可售 ${ready}${od ? ' · 超时 ' + od : ''}</span></div>
        <div class="rooms">${list.map(roomCard).join('')}</div>
      </div>`;
    }).join('');
  }

  function roomCard(r) {
    return `<div class="room ${r.overdue ? 'overdue' : ''} ${r.sellable ? 'sellable' : ''}"
      style="--state-color:${r.state_color}" data-no="${esc(r.room_no)}">
      ${r.overdue ? '<span class="flag">超时</span>' : ''}
      <div><span class="no">${esc(r.room_no)}</span><span class="type">${esc(r.room_type)}</span></div>
      <div class="row">
        ${chip(r.state_label, r.state_color)}
        <span class="age">${r.state === 'occupied' ? '在住' : dur(r.age_min)}</span>
      </div>
      <div class="guest">${r.guest_name ? '客人 ' + esc(r.guest_name) : esc(r.state_desc)}</div>
    </div>`;
  }

  document.addEventListener('click', (e) => {
    const card = e.target.closest('.room');
    if (card) openRoom(card.dataset.no);
  });

  /* ---------------- 抽屉 ---------------- */
  async function openRoom(no) {
    try {
      const data = await api.get('/api/rooms/' + encodeURIComponent(no));
      STATE.current = data.room;
      renderDrawer(data.room, data.events, data.gate);
      $('#drawer-mask').classList.add('open');
      $('#drawer').classList.add('open');
    } catch (e) { toast(e.message, 'err'); }
  }

  function closeDrawer() {
    $('#drawer-mask').classList.remove('open');
    $('#drawer').classList.remove('open');
  }

  function renderDrawer(r, events, gate) {
    $('#d-no').textContent = r.room_no;
    $('#d-badge').innerHTML = chip(r.state_label, r.state_color);
    $('#d-sub').textContent = `${r.floor} 楼 · ${r.room_type} · ${r.state_desc}`;
    const rows = [
      ['当前状态', `${r.state_label}${r.overdue ? '（已超时）' : ''}`],
      ['已保持', dur(r.age_min) + (r.sla_min ? ` / 阈值 ${r.sla_min} 分钟` : '')],
      ['能否入住', gate.allowed ? '<b style="color:var(--ok)">可以</b>' : `<b style="color:var(--danger)">不可以</b>：${esc(gate.reason)}`],
    ];
    if (r.guest_name) rows.push(['在住客人', `${esc(r.guest_name)} · ${r.nights} 晚`]);
    if (r.block_reason) rows.push(['停用原因', esc(r.block_reason)]);
    if (r.eta) rows.push(['预计可售', esc(r.eta)]);
    if (gate.next_step) rows.push(['下一步', esc(gate.next_step)]);

    $('#d-body').innerHTML = `
      <dl class="meta-list">${rows.map(([k, v]) => `<dt>${k}</dt><dd>${v}</dd>`).join('')}</dl>
      ${gate.alternatives && gate.alternatives.length ? `<div style="margin-top:16px"><div class="hint">可替代房间</div>
        <div class="alt-rooms">${gate.alternatives.map((a) => `<button class="alt-room" data-alt="${esc(a.room_no)}"><b>${esc(a.room_no)}</b> ${esc(a.room_type)}<br><span class="hint">${esc(a.reason)}</span></button>`).join('')}</div></div>` : ''}
      <div class="timeline">${events.map((e) => `<div class="item">
        <div class="t">${esc(fmtHM(e.created_at))}</div>
        <div class="d">${esc(e.from_label)} → <b>${esc(e.to_label)}</b> · ${esc(e.role)}${e.reason ? ' · ' + esc(e.reason) : ''}</div>
      </div>`).join('') || '<div class="hint">暂无流水</div>'}</div>`;

    const actions = r.allowed_actions.filter((a) => a.roles.includes(ROLE) || ROLE === 'admin');
    $('#d-actions').innerHTML = actions.map((a) =>
      `<button class="btn ${a.action === 'check_in' ? '' : 'ghost'} small" data-act="${a.action}">${esc(a.label)}</button>`
    ).join('') || '<span class="hint">当前岗位无直接操作权限，请交接给对应岗位</span>';
  }

  document.addEventListener('click', async (e) => {
    const alt = e.target.closest('[data-alt]');
    if (alt) { closeDrawer(); gotoCheckin(alt.dataset.alt); return; }
    const btn = e.target.closest('[data-act]');
    if (btn && STATE.current) {
      const action = btn.dataset.act;
      const no = STATE.current.room_no;
      if (action === 'check_in') { closeDrawer(); gotoCheckin(no); return; }
      if (action === 'pass_inspection') return askChecklist(no);
      if (action === 'start_inspection' || action === 'start_cleaning' || action === 'finish_cleaning' || action === 'check_out' || action === 'unblock') {
        return doTransition(no, action, {});
      }
      return askReason(no, action, btn.textContent.trim());
    }
  });

  async function doTransition(no, action, extra) {
    try {
      const data = await api.post(`/api/rooms/${encodeURIComponent(no)}/transition`, { action, ...extra });
      toast(data.message);
      closeDrawer();
      await loadBoard(true);
      if ($('#view-tasks').classList.contains('active')) loadTasks();
    } catch (e) { toast(e.message, 'err'); }
  }

  function askReason(no, action, label) {
    window.APP.openModal({
      title: `${label} · ${no}`,
      body: `<div class="field"><label>原因（必填，会写入房态流水）</label>
        <textarea id="reason-input" rows="3" placeholder="例如：卫生间漏水 / 床单有毛发需返工"></textarea></div>`,
      okText: label,
      danger: action === 'block',
      onOk: async () => {
        const reason = $('#reason-input').value.trim();
        if (!reason) { toast('请填写原因', 'warn'); throw new Error('no reason'); }
        await doTransition(no, action, { reason });
        window.APP.closeModal();
      },
    });
  }

  const CHECK_ITEMS = [
    ['bed', '床品'], ['bath', '卫浴'], ['floor', '地面家具'], ['amenity', '客用品'], ['device', '设备'], ['smell', '气味噪音'],
  ];

  function askChecklist(no) {
    window.APP.openModal({
      title: `查房通过 · ${no}`,
      body: `<div class="hint" style="margin-bottom:10px">六项全部通过才能置为可售；有不合格项请选「查房不通过」。</div>
        <div id="ck-list">${CHECK_ITEMS.map(([k, label]) =>
          `<label style="display:flex;gap:8px;align-items:center;padding:5px 0"><input type="checkbox" data-k="${k}"> ${label}</label>`).join('')}</div>
        <div class="field" style="margin-top:10px"><label>备注（可选）</label><input id="ck-note" placeholder="如：1208 客人加床已备好"></div>`,
      okText: '确认通过',
      after: () => {
        const all = document.createElement('button');
        all.type = 'button'; all.className = 'btn ghost small'; all.textContent = '全部勾选';
        all.style.marginBottom = '8px';
        all.addEventListener('click', () => document.querySelectorAll('#ck-list input').forEach((i) => (i.checked = true)));
        $('#ck-list').before(all);
      },
      onOk: async () => {
        const checklist = {};
        document.querySelectorAll('#ck-list input').forEach((i) => (checklist[i.dataset.k] = i.checked));
        if (Object.values(checklist).some((v) => !v)) { toast('还有检查项未通过，请改选「查房不通过」', 'warn'); throw new Error('incomplete'); }
        await doTransition(no, 'pass_inspection', { checklist, reason: $('#ck-note').value.trim() });
        window.APP.closeModal();
      },
    });
  }

  /* ---------------- 入住闸门 ---------------- */
  $('#ci-check').addEventListener('click', () => {
    const no = $('#ci-room').value.trim();
    if (!no) return toast('请输入房号', 'warn');
    gotoCheckin(no);
  });
  $('#ci-room').addEventListener('keydown', (e) => { if (e.key === 'Enter') $('#ci-check').click(); });

  function gotoCheckin(no) {
    document.querySelector('.tab[data-view="checkin"]').click();
    $('#ci-room').value = no;
    checkGate(no);
  }

  async function checkGate(no) {
    $('#gate-result').innerHTML = '<div class="empty">校验中…</div>';
    try {
      const g = await api.get('/api/checkin/gate?room_no=' + encodeURIComponent(no));
      renderGate(g);
    } catch (e) {
      $('#gate-result').innerHTML = `<div class="gate-card blocked"><div class="verdict"><span class="icon">!</span>${esc(e.message)}</div></div>`;
    }
  }

  function renderGate(g) {
    const r = g.room;
    if (g.allowed) {
      $('#gate-result').innerHTML = `
        <div class="gate-card ok">
          <div class="verdict"><span class="icon">✓</span>${esc(r.room_no)} 可以办理入住</div>
          <div class="why">${esc(g.reason)}。房间 ${esc(r.room_type)}，${esc(r.floor)} 楼。</div>
          <div class="inline-form" style="margin-top:14px">
            <div class="field" style="width:150px"><label>客人姓名</label><input id="ci-name" placeholder="入住人"></div>
            <div class="field" style="width:90px"><label>住晚</label><input id="ci-nights" type="number" min="1" max="30" value="1"></div>
            <button class="btn" id="ci-confirm">确认开房</button>
          </div>
        </div>`;
      $('#ci-confirm').addEventListener('click', () => submitCheckin(r.room_no));
    } else {
      $('#gate-result').innerHTML = `
        <div class="gate-card blocked">
          <div class="verdict"><span class="icon">!</span>${esc(r.room_no)} 现在不能办入住</div>
          <div class="why"><b>${esc(g.state_label)}</b>：${esc(g.reason)}</div>
          <div class="next">下一步：${esc(g.next_step)}${g.owner ? `（责任岗位：${esc(g.owner)}）` : ''}${g.wait_min ? `，预计 ${g.wait_min} 分钟` : ''}</div>
          <div class="hint" style="margin-top:8px">本次拦截已记入「房态错误拦截」，可在管理端看到趋势。</div>
          ${g.alternatives && g.alternatives.length ? `<div style="margin-top:14px"><div class="hint">可替代房间</div>
            <div class="alt-rooms">${g.alternatives.map((a) => `<button class="alt-room" data-alt="${esc(a.room_no)}"><b>${esc(a.room_no)}</b> ${esc(a.room_type)}<br><span class="hint">${esc(a.reason)}</span></button>`).join('')}</div></div>` : ''}
        </div>`;
    }
  }

  async function submitCheckin(no) {
    const name = $('#ci-name').value.trim();
    const nights = parseInt($('#ci-nights').value || '1', 10);
    if (!name) return toast('请填写客人姓名', 'warn');
    try {
      const data = await api.post(`/api/rooms/${encodeURIComponent(no)}/checkin`, { guest_name: name, nights });
      toast(data.message);
      $('#gate-result').innerHTML = `<div class="gate-card ok"><div class="verdict"><span class="icon">✓</span>已开房</div>
        <div class="why">${esc(no)} · ${esc(name)} · ${nights} 晚。房态已转为「在住」。</div></div>`;
      loadBoard(true);
      loadAvailable();
    } catch (e) { toast(e.message, 'err'); checkGate(no); }
  }

  async function loadAvailable() {
    try {
      const data = await api.get('/api/rooms?state=ready');
      $('#available-list').innerHTML = data.rooms.length
        ? `<div class="rooms">${data.rooms.map((r) => `<div class="room sellable" style="--state-color:${r.state_color}" data-no="${esc(r.room_no)}">
            <div><span class="no">${esc(r.room_no)}</span><span class="type">${esc(r.room_type)}</span></div>
            <div class="row">${chip(r.state_label, r.state_color)}<span class="age">${dur(r.age_min)}</span></div>
          </div>`).join('')}</div>`
        : '<div class="empty">当前没有可售房间</div>';
    } catch (e) { toast(e.message, 'err'); }
  }

  /* ---------------- 待办 ---------------- */
  async function loadTasks() {
    try {
      const data = await api.get('/api/tasks?status=' + encodeURIComponent(STATE.taskStatus));
      const open = STATE.taskStatus.includes('open');
      if (open) {
        const n = data.tasks.length;
        const dot = $('#task-dot');
        dot.hidden = !n; dot.textContent = n;
      }
      $('#task-table').innerHTML = data.tasks.length ? `<table>
        <thead><tr><th>房间</th><th>类型</th><th>房态</th><th>优先级</th><th>来源</th><th>说明</th><th>创建</th><th>操作</th></tr></thead>
        <tbody>${data.tasks.map((t) => `<tr>
          <td><b>${esc(t.room_no)}</b></td>
          <td>${esc(t.kind_label)}</td>
          <td>${esc(t.room_state_label)}</td>
          <td><span class="tag ${t.priority === 'high' ? 'high' : ''}">${t.priority === 'high' ? '高' : '普通'}</span></td>
          <td><span class="tag ${t.source === 'agent' ? 'agent' : 'sys'}">${t.source === 'agent' ? '助手' : '系统'}</span></td>
          <td>${esc(t.note || '—')}${t.assignee ? ' · ' + esc(t.assignee) : ''}</td>
          <td class="hint">${esc(fmtHM(t.created_at))}</td>
          <td>${open
            ? `${t.status === 'open' ? `<button class="btn ghost small" data-task="${t.id}" data-ta="claim">接单</button>` : ''}
               <button class="btn ghost small" data-task="${t.id}" data-ta="done">完成</button>`
            : ''}</td>
        </tr>`).join('')}</tbody></table>` : '<div class="empty">没有任务</div>';
    } catch (e) { toast(e.message, 'err'); }
  }

  document.addEventListener('click', async (e) => {
    const b = e.target.closest('[data-task]');
    if (!b) return;
    try {
      const data = await api.post(`/api/tasks/${b.dataset.task}/action`, { action: b.dataset.ta });
      toast(data.message);
      loadTasks();
    } catch (err) { toast(err.message, 'err'); }
  });

  $('#task-filter').addEventListener('click', (e) => {
    const b = e.target.closest('button[data-s]');
    if (!b) return;
    $('#task-filter').querySelectorAll('button').forEach((x) => x.classList.toggle('active', x === b));
    STATE.taskStatus = b.dataset.s;
    loadTasks();
  });

  /* ---------------- 交接班 ---------------- */
  async function loadHandover() {
    try {
      const d = await api.get('/api/handover/draft');
      $('#h-summary').value = d.handover_text;
      $('#h-meta').textContent = `生成于 ${fmtHM(d.generated_at)} · 超时 ${d.overdue_count} 间 · 未完成任务 ${d.tasks.length} 项`;
      const items = []
        .concat(d.waiting_inspection.map((r) => ({ no: r.room_no, label: r.state_label, age: r.age_min, od: r.overdue })))
        .concat(d.blocked.map((r) => ({ no: r.room_no, label: '维修中', age: null, note: r.block_reason })));
      $('#h-draft').innerHTML = items.length ? `<table><thead><tr><th>房间</th><th>状态</th><th>等待</th><th>备注</th></tr></thead>
        <tbody>${items.map((i) => `<tr><td><b>${esc(i.no)}</b></td><td>${esc(i.label)}</td>
          <td>${i.age !== null ? dur(i.age) + (i.od ? ' <span class="tag high">超时</span>' : '') : '—'}</td>
          <td class="hint">${esc(i.note || '')}</td></tr>`).join('')}</tbody></table>`
        : '<div class="empty">没有需要交接的未完成事项</div>';
      const hist = await api.get('/api/handover/history');
      $('#h-history').innerHTML = hist.items.length ? `<table><thead><tr><th>时间</th><th>班次</th><th>交接人</th><th>摘要</th></tr></thead>
        <tbody>${hist.items.map((h) => `<tr><td class="hint">${esc(fmtHM(h.created_at))}</td><td>${esc(h.shift)}</td>
          <td>${esc(h.created_by)}</td><td>${esc(h.summary)}${h.issues ? '<br><span class="hint">遗留：' + esc(h.issues) + '</span>' : ''}</td></tr>`).join('')}</tbody></table>`
        : '<div class="empty">暂无历史交接单</div>';
    } catch (e) { toast(e.message, 'err'); }
  }

  $('#h-submit').addEventListener('click', async () => {
    const summary = $('#h-summary').value.trim();
    if (!summary) return toast('交接内容不能为空', 'warn');
    try {
      const d = await api.post('/api/handover', { shift: $('#h-shift').value, summary, issues: $('#h-issues').value.trim() });
      toast(d.message);
      $('#h-issues').value = '';
      loadHandover();
    } catch (e) { toast(e.message, 'err'); }
  });

  /* ---------------- 助手 ---------------- */
  function addMsg(role, html, meta) {
    const wrap = document.createElement('div');
    wrap.className = 'msg ' + (role === 'user' ? 'user' : 'bot');
    wrap.innerHTML = `<div class="bubble">${html}</div>${meta ? `<div class="meta">${meta}</div>` : ''}`;
    $('#chat-body').appendChild(wrap);
    $('#chat-body').scrollTop = $('#chat-body').scrollHeight;
    return wrap;
  }

  async function send(msg) {
    if (!msg.trim()) return;
    addMsg('user', esc(msg));
    $('#chat-text').value = '';
    const sendBtn = $('#chat-send');
    sendBtn.disabled = true;
    const thinking = addMsg('bot', '<span class="typing"><i></i><i></i><i></i></span> <span class="hint">正在查房态与制度…</span>');
    try {
      const d = await api.post('/api/agent/chat', { message: msg, session_id: sessionId });
      sessionId = d.session_id;
      thinking.remove();
      const modeText = { llm: '模型 + 工具', guarded: '依据校验后改用规则答案', fallback: '规则模式' }[d.mode] || d.mode;
      let meta = `<span class="mode-badge ${d.mode}">${modeText}</span><span>${d.latency_ms} ms</span>`;
      if (d.trace && d.trace.length) {
        meta += `<div class="trace">${d.trace.map((t) => `<span class="trace-chip ${t.write ? 'write' : ''}" title="${esc(t.brief)}">${esc(t.tool)} · ${esc(String(t.brief || '').slice(0, 34))}${String(t.brief || '').length > 34 ? '…' : ''}</span>`).join('')}</div>`;
      }
      const node = addMsg('bot', esc(d.answer).replace(/\n/g, '<br>'), meta);
      if (d.citations && d.citations.length) {
        const box = document.createElement('div');
        box.className = 'cites';
        box.innerHTML = d.citations.map((c) => `<div class="cite"><b>${esc(c.ref)}</b><br>${esc(c.text)}</div>`).join('');
        node.appendChild(box);
      }
      if (d.note) {
        const n = document.createElement('div');
        n.className = 'hint';
        n.textContent = '说明：' + d.note;
        node.appendChild(n);
      }
      (d.actions || []).forEach((a) => {
        const card = document.createElement('div');
        card.className = 'action-card';
        card.innerHTML = `<div class="t">待确认动作：${esc(a.summary)}</div>
          <button class="btn small" data-act-confirm="${a.id}">确认执行</button>
          <button class="btn ghost small" data-act-reject="${a.id}">忽略</button>`;
        node.appendChild(card);
      });
    } catch (e) {
      thinking.remove();
      addMsg('bot', `<span style="color:var(--danger)">${esc(e.message)}</span>`);
    } finally {
      sendBtn.disabled = false;
      $('#chat-text').focus();
    }
  }

  document.addEventListener('click', async (e) => {
    const c = e.target.closest('[data-act-confirm]');
    const j = e.target.closest('[data-act-reject]');
    if (c) {
      try {
        const d = await api.post(`/api/agent/actions/${c.dataset.actConfirm}/confirm`);
        toast(d.message);
        c.closest('.action-card').innerHTML = `<div class="t">已执行：${esc(d.message)}</div>`;
        loadBoard(true);
      } catch (err) { toast(err.message, 'err'); }
    }
    if (j) {
      try {
        await api.post(`/api/agent/actions/${j.dataset.actReject}/reject`);
        j.closest('.action-card').innerHTML = '<div class="t">已忽略</div>';
      } catch (err) { toast(err.message, 'err'); }
    }
  });

  $('#chat-form').addEventListener('submit', (e) => { e.preventDefault(); send($('#chat-text').value); });
  $('#quick').addEventListener('click', (e) => { if (e.target.tagName === 'BUTTON') send(e.target.textContent); });
  $('#agent-reset').addEventListener('click', () => {
    sessionId = null;
    $('#chat-body').innerHTML = '';
    greet();
  });

  function greet() {
    addMsg('bot', `我是值班助手。可以问我：某间房能不能入住、还有哪些可售房、待查房队列、当班指标，或者制度口径。<br>
      <span class="hint">改房态的动作我都会先生成「待确认」，你点了才执行。</span>`);
  }

  /* ---------------- 启动 ---------------- */
  $('#state-filter').addEventListener('click', (e) => {
    const b = e.target.closest('button[data-s]');
    if (!b) return;
    $('#state-filter').querySelectorAll('button').forEach((x) => x.classList.toggle('active', x === b));
    STATE.filter = b.dataset.s;
    renderBoard();
  });
  $('#refresh-board').addEventListener('click', () => loadBoard());
  $('#d-close').addEventListener('click', closeDrawer);
  $('#drawer-mask').addEventListener('click', closeDrawer);

  document.addEventListener('view:change', (e) => {
    if (e.detail === 'tasks') loadTasks();
    if (e.detail === 'handover') loadHandover();
    if (e.detail === 'checkin') loadAvailable();
    if (e.detail === 'agent' && !$('#chat-body').children.length) greet();
  });

  async function initStatus() {
    try {
      const s = await api.get('/api/agent/status');
      const el = $('#llm-badge');
      el.textContent = s.llm_ready ? `助手 · ${s.model}` : '助手 · 规则模式';
      el.className = 'llm-badge ' + (s.llm_ready ? 'on' : 'off');
    } catch (e) { /* ignore */ }
  }

  loadBoard();
  initStatus();
  setInterval(() => { if ($('#view-board').classList.contains('active')) loadBoard(true); }, 20000);
})();
