/* FDE 项目工作台 · 应用层
   路由 + 六个视图。所有计算走 FDE（engine.js），所有持久化走 Store（store.js）。
   无构建步骤：直接 file:// 打开即可运行。 */

(function () {
  'use strict';

  const FDE = window.FDE;
  const Store = window.Store;
  const SU = window.StateUtil;

  /* ---------- 数据 ---------- */

  const DATA = { project: null, stages: null, rooms: null };

  /* ---------- 全局可写状态 ---------- */

  let state = Store.load();
  let ui = {
    stageId: null,      // pipeline 当前阶段
    roomNo: null,       // demo 当前选中房间
    draft: null,        // demo 交接单草稿
    queue: [],          // demo 人工复核队列
    audit: []           // demo 审计链
  };

  /* ---------- 工具 ---------- */

  const $ = (sel, root) => (root || document).querySelector(sel);
  const esc = s => String(s == null ? '' : s)
    .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');

  const money = n => '¥' + Number(n || 0).toLocaleString('zh-CN');
  const num = n => Number(n || 0).toLocaleString('zh-CN');
  const pct = (a, b) => (b ? Math.round((a / b) * 100) : 0);

  let toastTimer = null;
  function toast(msg) {
    let el = $('#toast');
    if (!el) {
      el = document.createElement('div');
      el.id = 'toast';
      document.body.appendChild(el);
    }
    el.textContent = msg;
    el.hidden = false;
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => { el.hidden = true; }, 2000);
  }

  function markSaved() {
    const el = $('#save-state');
    if (!el) return;
    el.textContent = '已保存 · ' + new Date().toLocaleTimeString('zh-CN', { hour12: false });
    el.className = 'tag ok';
    setTimeout(() => { el.className = 'hint'; }, 1600);
  }

  function persist() {
    Store.save(state);
    markSaved();
  }

  /* ---------- 数据加载 ---------- */

  function loadData() {
    return Promise.all([
      fetch('data/project.json').then(r => r.json()),
      fetch('data/stages.json').then(r => r.json()),
      fetch('data/rooms.json').then(r => r.json())
    ]).then(([project, stages, rooms]) => {
      DATA.project = project;
      DATA.stages = stages;
      DATA.rooms = rooms;
    });
  }

  /* fetch 在 file:// 下会被拦截，因此内嵌一份兜底数据 */
  function loadDataWithFallback() {
    return loadData().catch(() => {
      if (!window.FDE_FALLBACK) throw new Error('缺少内嵌数据');
      DATA.project = window.FDE_FALLBACK.project;
      DATA.stages = window.FDE_FALLBACK.stages;
      DATA.rooms = window.FDE_FALLBACK.rooms;
    });
  }

  /* ---------- 视图：项目总览 ---------- */

  function viewOverview() {
    const p = DATA.project;
    const confirmed = p.facts.filter(f => f.status === '已确认').length;
    const pending = p.facts.length - confirmed;

    const metricCards = p.metrics.map(m => {
      const delta = m.baseline === m.target ? '—'
        : (m.target < m.baseline
          ? `↓ ${num(m.baseline - m.target)}`
          : `↑ ${num(m.target - m.baseline)}`);
      return `
        <div class="stat">
          <div class="k">${esc(m.label)} · ${esc(m.owner)}</div>
          <div class="v">${num(m.baseline)} <small>${esc(m.unit)}</small></div>
          <div class="hint" style="margin-top:6px">
            目标 ${num(m.target)} ${esc(m.unit)}　<span class="tag info">${delta}</span>
          </div>
          <div class="hint">${esc(m.note)}</div>
        </div>`;
    }).join('');

    const roleRows = p.roles.map(r => `
      <tr>
        <td><strong>${esc(r.name)}</strong></td>
        <td>${esc(r.role)}</td>
        <td><span class="tag ${r.kind === '风险否决' ? 'danger' : (r.kind === '主问题提出人' ? 'info' : 'muted')}">${esc(r.kind)}</span></td>
        <td class="hint" style="margin:0">${esc(r.concern)}</td>
      </tr>`).join('');

    const factRows = p.facts.map(f => `
      <tr>
        <td style="width:52px;color:var(--ink-3)">${esc(f.id)}</td>
        <td>${esc(f.text)}</td>
        <td style="width:110px" class="hint">${esc(f.source)}</td>
        <td style="width:78px">
          <span class="tag ${f.status === '已确认' ? 'ok' : 'warn'}">${esc(f.status)}</span>
        </td>
      </tr>`).join('');

    return `
      <div class="page-title">
        <div>
          <h1>${esc(p.company)} · ${esc(p.name)}</h1>
          <p>${esc(p.summary)}</p>
        </div>
        <span class="tag muted">项目编号 ${esc(p.projectId)}</span>
      </div>

      <div class="grid c4" style="margin-top:16px">
        <div class="stat">
          <div class="k">业务事实</div>
          <div class="v">${p.facts.length}</div>
          <div class="hint">已确认 ${confirmed} · 待核实 ${pending}</div>
        </div>
        <div class="stat">
          <div class="k">参与角色</div>
          <div class="v">${p.roles.length}</div>
          <div class="hint">含 1 名风险否决人</div>
        </div>
        <div class="stat">
          <div class="k">交付阶段</div>
          <div class="v">${DATA.stages.stages.length}</div>
          <div class="hint">每阶段 3 步 · 1 个人工闸门</div>
        </div>
        <div class="stat">
          <div class="k">首期预算</div>
          <div class="v">${money(p.budget.total)}</div>
          <div class="hint">${esc(p.budget.note)}</div>
        </div>
      </div>

      <div class="panel">
        <h2>验收指标</h2>
        <p class="hint">口径未签字前，下列目标值只能作为假设使用。</p>
        <div class="grid c4" style="margin-top:12px">${metricCards}</div>
        <div class="note warn">
          指标 f00「误判定义」与 f01「等待基线起点」目前为<b>待核实</b>，
          将直接决定验收结论，须在需求定义阶段闸门前完成口径签字。
        </div>
      </div>

      <div class="panel">
        <h2>角色与关切</h2>
        <p class="hint">每个角色的约束都必须落到方案里，否则试点会被绕过。</p>
        <table style="margin-top:10px">
          <thead><tr><th>姓名</th><th>岗位</th><th>角色类型</th><th>核心关切</th></tr></thead>
          <tbody>${roleRows}</tbody>
        </table>
      </div>

      <div class="panel">
        <h2>业务事实台账</h2>
        <p class="hint">每条需求都要能追溯到这里的某一行；状态为「待核实」的不进入需求规格。</p>
        <table style="margin-top:10px">
          <thead><tr><th>编号</th><th>事实</th><th>来源</th><th>状态</th></tr></thead>
          <tbody>${factRows}</tbody>
        </table>
      </div>

      <div class="panel">
        <h2>下一步</h2>
        <p class="hint">本工作台的三条主线互为输入，建议按下列顺序推进。</p>
        <div class="grid c3" style="margin-top:12px">
          <div>
            <strong style="font-size:13px">1 · 走完九阶段</strong>
            <p class="hint">在「九阶段流程」里逐步记录成果，每个阶段结束必须由具名评审人签字才能进入下一阶段。</p>
            <a class="btn" href="#/pipeline" style="display:inline-block;text-decoration:none">进入流程</a>
          </div>
          <div>
            <strong style="font-size:13px">2 · 跑通协同 Demo</strong>
            <p class="hint">在「协同 Demo」里用 8 间演示客房复现三态脱节，验证交接单必填项与校验规则。</p>
            <a class="btn" href="#/demo" style="display:inline-block;text-decoration:none">打开 Demo</a>
          </div>
          <div>
            <strong style="font-size:13px">3 · 算清 ROI</strong>
            <p class="hint">在「ROI 测算」里把节省工时折算成成本，扣除按月发生的复核成本后再谈回收期。</p>
            <a class="btn" href="#/roi" style="display:inline-block;text-decoration:none">开始测算</a>
          </div>
        </div>
      </div>
    `;
  }

  /* ---------- 视图：九阶段流程 ---------- */

  function pipelineSidebar() {
    const st = DATA.stages.stages;
    const active = ui.stageId || st[0].id;
    return `<div class="stage-nav">${st.map((s, i) => {
      const pr = SU.stageProgress(state, s, s.steps);
      const gate = SU.getGate(state, s.id);
      const cls = [s.id === active ? 'on' : '', pr.pct === 100 ? 'done' : ''].join(' ').trim();
      const gateMark = gate.status === '通过' ? '✓ 已过闸' : `${pr.done}/${pr.total}`;
      return `<a class="${cls}" href="#/pipeline/${s.id}">
        <span class="num">${i + 1}</span>
        <span>${esc(s.title)}</span>
        <span class="mini">${gateMark}</span>
      </a>`;
    }).join('')}</div>`;
  }

  function viewPipeline(stageId) {
    const st = DATA.stages.stages;
    const stage = st.find(s => s.id === stageId) || st[0];
    ui.stageId = stage.id;

    const pr = SU.stageProgress(state, stage, stage.steps);
    const gate = SU.getGate(state, stage.id);
    const idx = st.findIndex(s => s.id === stage.id);

    const steps = stage.steps.map((s, i) => {
      const rec = SU.getStep(state, stage.id, s.id);
      return `
        <div class="step ${rec.done ? 'done' : ''}">
          <div class="step-head">
            <span class="tag ${rec.done ? 'ok' : 'muted'}">步骤 ${i + 1}</span>
            <h3>${esc(s.title)}</h3>
            <span class="out">交付物：${esc(s.output)}</span>
          </div>
          <p class="ask">动作：${esc(s.action)}</p>
          <p class="ask">要回答：<b>${esc(s.question)}</b></p>
          <label class="field">
            <span>成果记录</span>
            <textarea data-step="${esc(s.id)}" placeholder="写清结论、数据与来源。空着就等于没做。">${esc(rec.text)}</textarea>
          </label>
          <div style="display:flex;gap:8px;align-items:center">
            <button class="${rec.done ? '' : 'primary'} sm" data-toggle="${esc(s.id)}"
              data-done="${rec.done ? '1' : '0'}">${rec.done ? '取消完成' : '标记完成'}</button>
            <span class="hint">${rec.updatedAt ? '更新于 ' + new Date(rec.updatedAt).toLocaleString('zh-CN', { hour12: false }) : '尚未记录'}</span>
          </div>
        </div>`;
    }).join('');

    const gateCls = gate.status === '通过' ? 'ok' : (gate.status === '驳回' ? 'danger' : 'warn');
    const prev = st[idx - 1];
    const next = st[idx + 1];

    return `
      <div class="page-title">
        <div>
          <h1>九阶段交付流程</h1>
          <p>每个阶段 = 3 个动作 + 1 个人工闸门。闸门未签字，不进入下一阶段。</p>
        </div>
        <span class="tag info">第 ${idx + 1} / ${st.length} 阶段</span>
      </div>

      <div style="display:grid;grid-template-columns:220px minmax(0,1fr);gap:20px;margin-top:16px">
        <div>
          ${pipelineSidebar()}
          <div class="panel" style="margin-top:14px">
            <h2 style="font-size:13px">整体进度</h2>
            ${(() => {
              const all = st.reduce((acc, s) => {
                const p = SU.stageProgress(state, s, s.steps);
                return { done: acc.done + p.done, total: acc.total + p.total };
              }, { done: 0, total: 0 });
              const p = pct(all.done, all.total);
              return `
                <div class="bar" style="margin:8px 0 6px"><i style="width:${p}%"></i></div>
                <div class="hint">${all.done} / ${all.total} 步 · ${p}%</div>`;
            })()}
          </div>
        </div>

        <div>
          <div class="panel" style="margin-top:0">
            <div style="display:flex;align-items:flex-start;justify-content:space-between;gap:12px">
              <div>
                <h2>${esc(stage.title)}</h2>
                <p class="hint">${esc(stage.goal)}</p>
              </div>
              <span class="tag ${pr.pct === 100 ? 'ok' : 'muted'}">${pr.done}/${pr.total}</span>
            </div>
            <div class="bar" style="margin:12px 0 4px"><i style="width:${pr.pct}%"></i></div>
            ${steps}
          </div>

          <div class="panel">
            <h2>阶段闸门 · 人工签字</h2>
            <p class="hint">通过条件：${esc(stage.gate)}</p>
            <div class="note ${gate.status === '通过' ? '' : (gate.status === '驳回' ? 'danger' : 'warn')}">
              当前状态：<b>${esc(gate.status)}</b>
              ${gate.reviewer ? `　评审人：${esc(gate.reviewer)}` : '　尚未指定评审人'}
              ${gate.at ? `　时间：${new Date(gate.at).toLocaleString('zh-CN', { hour12: false })}` : ''}
            </div>
            <div class="grid c2" style="margin-top:12px">
              <label class="field">
                <span>评审人姓名（必填）</span>
                <input type="text" id="gate-reviewer" value="${esc(gate.reviewer)}" placeholder="例如 顾明岚">
              </label>
              <label class="field">
                <span>评审意见</span>
                <input type="text" id="gate-note" value="${esc(gate.note)}" placeholder="例如 口径已签字，可进入下一阶段">
              </label>
            </div>
            <div style="display:flex;gap:8px;flex-wrap:wrap">
              <button class="primary" data-gate="通过" ${pr.pct < 100 ? 'disabled' : ''}>通过闸门</button>
              <button data-gate="驳回">驳回</button>
              <button class="ghost" data-gate="未评审">重置</button>
              ${pr.pct < 100 ? '<span class="hint" style="align-self:center">3 个步骤全部标记完成后才可通过</span>' : ''}
            </div>
            <div class="note">
              驳回会记入评审记录；如果口径或预算发生变化，应回到本阶段重做，而不是在下一阶段补救。
            </div>
          </div>

          <div style="display:flex;justify-content:space-between;margin-top:16px">
            ${prev ? `<a class="btn" href="#/pipeline/${prev.id}" style="text-decoration:none">← ${esc(prev.title)}</a>` : '<span></span>'}
            ${next ? `<a class="btn" href="#/pipeline/${next.id}" style="text-decoration:none">${esc(next.title)} →</a>` : '<span></span>'}
          </div>
        </div>
      </div>
    `;
  }

  /* ---------- 视图：协同 Demo ---------- */

  function roomCard(room) {
    const g = FDE.threeStateGap(room);
    const sel = ui.roomNo === room.no ? 'sel' : '';
    const gapTags = g.gaps.map(x => `<span class="tag danger" title="${esc(x.text)}">${esc(x.code)}</span>`).join('');
    return `
      <div class="room ${g.status.tone} ${sel}" data-room="${esc(room.no)}">
        <div class="no">${esc(room.no)}</div>
        <div class="ty">${esc(room.type)}</div>
        <div class="st">
          <span class="tag ${g.status.tone}">${esc(g.status.code)} · ${esc(g.status.label)}</span>
          <span class="tag ${g.status.sellable ? 'ok' : 'muted'}">${g.status.sellable ? '可售' : '不可售'}</span>
        </div>
        <div class="st">${gapTags}</div>
      </div>`;
  }

  function handoffEditor() {
    const room = DATA.rooms.rooms.find(r => r.no === ui.roomNo);
    if (!room) {
      return `<div class="note">从左侧选一间客房，系统会按三态投影生成交接单草稿。</div>`;
    }
    const g = FDE.threeStateGap(room);
    const fields = DATA.rooms.handoffFields;
    const d = ui.draft;
    const v = FDE.validateHandoff(room, d, fields);

    const inputs = fields.map(f => {
      const val = d[f.key] == null ? '' : d[f.key];
      const req = f.required ? '<span style="color:var(--danger)"> *</span>' : '';
      if (f.key === 'state') {
        return `<label class="field">
          <span>${esc(f.label)}${req}</span>
          <select data-draft="${f.key}">
            <option value="可售" ${val === '可售' ? 'selected' : ''}>可售</option>
            <option value="不可售" ${val === '不可售' ? 'selected' : ''}>不可售</option>
          </select>
        </label>`;
      }
      return `<label class="field">
        <span>${esc(f.label)}${req}</span>
        <input type="text" data-draft="${f.key}" value="${esc(val)}"
          ${f.key === 'room' ? 'readonly' : ''}>
      </label>`;
    }).join('');

    const gapList = g.gaps.length
      ? g.gaps.map(x => `<div class="note warn" style="margin-top:8px">
          <b>${esc(x.code)}</b> · ${esc(x.text)}　→ 责任岗：${esc(x.owner)}
        </div>`).join('')
      : `<div class="note" style="margin-top:8px">三态一致，无阻塞项。</div>`;

    const errs = v.errors.length
      ? `<div class="note danger" id="handoff-msg">${v.errors.map(e => '· ' + esc(e)).join('<br>')}</div>`
      : `<div class="note" id="handoff-msg">校验通过，可提交人工复核。</div>`;

    return `
      <div style="display:flex;align-items:center;gap:10px;margin-bottom:10px">
        <span class="tag ${g.status.tone}">${esc(g.status.code)} · ${esc(g.status.label)}</span>
        <span class="hint" style="margin:0">${esc(room.note)}</span>
      </div>
      ${gapList}
      <div class="grid c2" style="margin-top:14px">${inputs}</div>
      <div class="hint" style="margin-bottom:10px">
        送模型前已脱敏：${esc(FDE.redact(JSON.stringify(d)).slice(0, 96))}…
      </div>
      ${errs}
      <div style="display:flex;gap:8px;flex-wrap:wrap;margin-top:12px">
        <button class="primary" data-submit ${v.ok ? '' : 'disabled'}>提交人工复核</button>
        <button data-redraft>重新生成草稿</button>
        <button class="ghost" data-clear-queue>清空复核队列</button>
      </div>
    `;
  }

  function queuePanel() {
    if (!ui.queue.length) {
      return `<div class="note">队列为空。提交的交接单会先进入这里，由具名接收人确认后才写回房态。</div>`;
    }
    const rows = ui.queue.map((q, i) => `
      <tr>
        <td><strong>${esc(q.room)}</strong></td>
        <td><span class="tag ${q.state === '可售' ? 'ok' : 'muted'}">${esc(q.state)}</span></td>
        <td>${esc(q.owner)}</td>
        <td>${esc(q.nextAction)}</td>
        <td class="hint">${esc(new Date(q.at).toLocaleTimeString('zh-CN', { hour12: false }))}</td>
        <td style="width:120px;white-space:nowrap">
          <button class="sm primary" data-approve="${i}">确认接收</button>
          <button class="sm ghost" data-drop="${i}">退回</button>
        </td>
      </tr>`).join('');
    return `
      <table>
        <thead><tr><th>房号</th><th>三态</th><th>具名接收人</th><th>下一步动作</th><th>提交时间</th><th></th></tr></thead>
        <tbody>${rows}</tbody>
      </table>`;
  }

  function auditPanel() {
    if (!ui.audit.length) {
      return `<div class="note">审计链为空。确认或退回操作都会留下不可编辑的摘要哈希。</div>`;
    }
    const rows = ui.audit.slice().reverse().map(a => `
      <tr>
        <td class="hint" style="margin:0">${esc(new Date(a.at).toLocaleTimeString('zh-CN', { hour12: false }))}</td>
        <td>${esc(a.actorRole)}</td>
        <td>${esc(a.action)}</td>
        <td><strong>${esc(a.room)}</strong></td>
        <td><code style="font-size:11.5px;color:var(--ink-2)">${esc(a.hash)}</code></td>
      </tr>`).join('');
    return `
      <table>
        <thead><tr><th>时间</th><th>岗位</th><th>动作</th><th>房号</th><th>摘要哈希</th></tr></thead>
        <tbody>${rows}</tbody>
      </table>
      <div class="hint" style="margin-top:10px">
        只记录岗位与动作，不记录姓名与个人信息；单次处理可依哈希重建。
      </div>`;
  }

  function viewDemo() {
    const rooms = DATA.rooms.rooms;
    const sum = FDE.occupancySummary(rooms);

    const rules = DATA.rooms.rules.map(r => `
      <tr>
        <td style="width:44px">${esc(r.id)}</td>
        <td>${esc(r.text)}</td>
        <td style="width:110px"><span class="tag ${r.type === '确定性校验' ? 'info' : (r.type === '人工裁决' ? 'warn' : 'muted')}">${esc(r.type)}</span></td>
      </tr>`).join('');

    return `
      <div class="page-title">
        <div>
          <h1>房态协同 Demo</h1>
          <p>${esc(DATA.rooms.hotel)} · 8 间客房覆盖全部三态组合与两类封锁。</p>
        </div>
        <button class="ghost sm" data-reset-demo>重置演示数据</button>
      </div>

      <div class="grid c4" style="margin-top:16px">
        <div class="stat"><div class="k">可售</div><div class="v">${sum.sellable}<small>间</small></div><div class="hint">占 ${sum.rate}%</div></div>
        <div class="stat"><div class="k">已清扫待查房</div><div class="v">${sum.pending}<small>间</small></div><div class="hint">前台最易误判</div></div>
        <div class="stat"><div class="k">脏房</div><div class="v">${sum.dirty}<small>间</small></div><div class="hint">需排清洁</div></div>
        <div class="stat"><div class="k">维修房 OOO</div><div class="v">${sum.ooo}<small>间</small></div><div class="hint">已扣库存</div></div>
      </div>

      <div class="panel">
        <h2>客房实况</h2>
        <p class="hint">点击任一间查看三态投影、缺口提示与自动起草的交接单。</p>
        <div class="rooms" style="margin-top:12px">${rooms.map(roomCard).join('')}</div>
        <div class="note">
          房态不是一个字段，而是三件事的投影：<b>占用</b>（前台）× <b>清洁</b>（客房：脏 / 已清扫 / 已查房）× <b>库存封锁</b>（OOO 扣减库存，OOS 仍可售）。
        </div>
      </div>

      <div class="grid c2">
        <div class="panel">
          <h2>交接单 · 人工复核</h2>
          <p class="hint">系统只起草，不自动写回；必须由具名接收人确认。</p>
          <div style="margin-top:12px">${handoffEditor()}</div>
        </div>
        <div class="panel">
          <h2>校验规则</h2>
          <p class="hint">能确定性算出来的，不交给模型判断。</p>
          <table style="margin-top:10px">
            <thead><tr><th>编号</th><th>规则</th><th>类型</th></tr></thead>
            <tbody>${rules}</tbody>
          </table>
        </div>
      </div>

      <div class="panel">
        <h2>复核队列</h2>
        <p class="hint">高峰期的真实瓶颈在这里：一条未确认的交接就是一次潜在误判。</p>
        <div style="margin-top:10px">${queuePanel()}</div>
      </div>

      <div class="panel">
        <h2>审计链</h2>
        <p class="hint">满足「可重建单次处理、不留多余个人信息」的要求。</p>
        <div style="margin-top:10px">${auditPanel()}</div>
      </div>
    `;
  }

  /* ---------- 视图：业务流程图 ---------- */

  function viewGraphs() {
    const st = DATA.stages.stages;
    const flow = st.map((s, i) => `
      <div class="node ${i === 0 || i === st.length - 1 ? 'term' : ''}">${esc(s.title)}</div>
      ${i < st.length - 1 ? '<div class="arrow"></div>' : ''}
    `).join('');

    const objects = [
      { name: '客房 Room', attrs: '房号、房型、楼层、占用、清洁、封锁', key: 'room_no' },
      { name: '清扫任务 Task', attrs: '房号、执行人岗位、开始/结束、复核结果', key: 'task_id' },
      { name: '交接单 Handoff', attrs: '房号、三态、阻塞原因、具名接收人、下一步、ETA', key: 'handoff_id' },
      { name: '闸门评审 Gate', attrs: '阶段、状态、评审人、意见、时间', key: 'gate_id' }
    ];

    const relations = [
      ['客房', '1 : 0..n', '清扫任务', '一间房每天产生多条清扫任务'],
      ['清扫任务', '1 : 0..1', '交接单', '查房未通过时必然产生交接单'],
      ['交接单', 'n : 1', '客房', '按房号回写状态'],
      ['阶段', '1 : 1', '闸门评审', '每阶段一个签字记录']
    ];

    return `
      <div class="page-title">
        <div>
          <h1>业务流程图</h1>
          <p>交付主线（左）与业务对象（右）一一对应，避免方案漂移。</p>
        </div>
      </div>

      <div class="grid c2" style="margin-top:16px">
        <div class="panel" style="margin-top:0">
          <h2>交付主线</h2>
          <p class="hint">九个阶段串行推进，每个阶段末尾都有一个闸门。</p>
          <div class="flow" style="margin-top:18px">${flow}</div>
          <div class="note">
            闸门未通过时箭头退回上一阶段，而不是带着未确认的口径往下走。
          </div>
        </div>

        <div>
          <div class="panel" style="margin-top:0">
            <h2>业务对象（Ontology）</h2>
            <p class="hint">系统只围绕这四个对象计算，其余都是视图。</p>
            <table style="margin-top:10px">
              <thead><tr><th>对象</th><th>关键属性</th><th>主键</th></tr></thead>
              <tbody>${objects.map(o => `
                <tr>
                  <td><strong>${esc(o.name)}</strong></td>
                  <td class="hint" style="margin:0">${esc(o.attrs)}</td>
                  <td><code style="font-size:11.5px">${esc(o.key)}</code></td>
                </tr>`).join('')}
              </tbody>
            </table>
          </div>

          <div class="panel">
            <h2>关系</h2>
            <table>
              <thead><tr><th>主体</th><th>基数</th><th>客体</th><th>说明</th></tr></thead>
              <tbody>${relations.map(r => `
                <tr>
                  <td>${esc(r[0])}</td>
                  <td><span class="tag muted">${esc(r[1])}</span></td>
                  <td>${esc(r[2])}</td>
                  <td class="hint" style="margin:0">${esc(r[3])}</td>
                </tr>`).join('')}
              </tbody>
            </table>
          </div>
        </div>
      </div>

      <div class="panel">
        <h2>数据边界</h2>
        <p class="hint">三个系统各自维护权限，本方案只读接入，不做生产库写入。</p>
        <div class="grid c3" style="margin-top:12px">
          <div>
            <strong style="font-size:13px">PMS</strong>
            <p class="hint">提供房号、占用与封锁事实。接口只读，回写走人工确认后的受控通道。</p>
          </div>
          <div>
            <strong style="font-size:13px">客房管家系统</strong>
            <p class="hint">提供清洁与查房结果。查房照片属于证据，按 90 天期满清理。</p>
          </div>
          <div>
            <strong style="font-size:13px">渠道 / OTA</strong>
            <p class="hint">只消费「可售」投影。OOO 必须提前扣减，否则超售。</p>
          </div>
        </div>
        <div class="note danger">
          已确认事实 f32：现有接口仅可读，不能写回生产库 —— 因此任何"自动改房态"的方案都不可行，
          必须在接线阶段设计人工确认环节。
        </div>
      </div>
    `;
  }

  /* ---------- 视图：ROI ---------- */

  const ROI_DEFAULTS = [
    { id: 'wait', label: '高峰入住等待压缩', type: 'benefit', qty: 60, unit: '次/月', per: 33, perUnit: '分钟', rate: 120, note: '每次节省分钟 × 等待人次' },
    { id: 'turn', label: '退房到可售周转', type: 'benefit', qty: 200, unit: '间/月', per: 26, perUnit: '分钟', rate: 45, note: '周转提速按客房人力成本折算' },
    { id: 'error', label: '房态误判减少', type: 'benefit', qty: 17, unit: '次/月', per: 30, perUnit: '分钟', rate: 120, note: '处理与安抚成本' },
    { id: 'integrate', label: '系统集成（一次性）', type: 'cost', qty: 1, unit: '项', per: 52000, perUnit: '元', rate: 1, note: '只读接口 + 字段映射' },
    { id: 'train', label: '培训与试点（一次性）', type: 'cost', qty: 1, unit: '项', per: 18000, perUnit: '元', rate: 1, note: '两轮班次培训' },
    { id: 'review', label: '人工复核（按月）', type: 'cost', qty: 340, unit: '单/月', per: 0.8, perUnit: '分钟', rate: 90, note: '复核成本按月发生，不能只算一次' },
    { id: 'storage', label: '证据存储与清理（按月）', type: 'cost', qty: 1, unit: '项', per: 900, perUnit: '元', rate: 1, note: '90 天保留 + 期满删除' }
  ];

  function roiRows() {
    if (!state.roi.rows || !state.roi.rows.length) {
      state.roi.rows = ROI_DEFAULTS.map(r => ({ ...r }));
    }
    return state.roi.rows;
  }

  function roiCalc(rows) {
    let monthlyBenefit = 0;
    let oneOffCost = 0;
    let monthlyCost = 0;
    rows.forEach(r => {
      // 金额 = 数量 × 单项分钟 × 分钟费率；纯金额项 rate 为 1
      const amount = r.type === 'benefit'
        ? r.qty * r.per * r.rate / 60
        : (r.unit === '单/月' ? r.qty * r.per * r.rate / 60 : r.qty * r.per * r.rate);
      if (r.type === 'benefit') monthlyBenefit += amount;
      else if (r.unit.indexOf('/月') >= 0) monthlyCost += amount;
      else oneOffCost += amount;
    });
    const net = monthlyBenefit - monthlyCost;
    const payback = net > 0 ? Math.ceil(oneOffCost / net) : null;
    return { monthlyBenefit, oneOffCost, monthlyCost, net, payback };
  }

  function viewRoi() {
    const rows = roiRows();
    const c = roiCalc(rows);
    const budget = DATA.project.budget.total;

    const body = rows.map((r, i) => `
      <tr>
        <td>${esc(r.label)}</td>
        <td><span class="tag ${r.type === 'benefit' ? 'ok' : 'muted'}">${r.type === 'benefit' ? '收益' : '成本'}</span></td>
        <td><input type="number" data-roi="${i}" data-k="qty" value="${r.qty}" style="width:80px;padding:4px 8px"></td>
        <td class="hint" style="margin:0">${esc(r.unit)}</td>
        <td><input type="number" data-roi="${i}" data-k="per" value="${r.per}" step="0.1" style="width:80px;padding:4px 8px"></td>
        <td class="hint" style="margin:0">${esc(r.perUnit)}</td>
        <td><input type="number" data-roi="${i}" data-k="rate" value="${r.rate}" style="width:80px;padding:4px 8px"></td>
        <td class="hint" style="margin:0">${esc(r.note)}</td>
      </tr>`).join('');

    return `
      <div class="page-title">
        <div>
          <h1>ROI 测算</h1>
          <p>收益必须扣除维护与复核成本后再谈回收期；复核成本按月发生。</p>
        </div>
        <button class="ghost sm" data-roi-reset>恢复默认假设</button>
      </div>

      <div class="grid c4" style="margin-top:16px">
        <div class="stat"><div class="k">月收益</div><div class="v">${money(Math.round(c.monthlyBenefit))}</div><div class="hint">节省工时折算</div></div>
        <div class="stat"><div class="k">月成本</div><div class="v">${money(Math.round(c.monthlyCost))}</div><div class="hint">复核 + 存储</div></div>
        <div class="stat"><div class="k">月净收益</div><div class="v" style="color:${c.net > 0 ? 'var(--ok)' : 'var(--danger)'}">${money(Math.round(c.net))}</div><div class="hint">净值口径</div></div>
        <div class="stat"><div class="k">回收期</div><div class="v">${c.payback ? c.payback + ' <small>个月</small>' : '—'}</div><div class="hint">一次性投入 ${money(Math.round(c.oneOffCost))}</div></div>
      </div>

      <div class="panel">
        <h2>测算明细</h2>
        <p class="hint">可直接修改数量、单位耗时与费率，结果实时刷新。</p>
        <table style="margin-top:10px">
          <thead>
            <tr><th>项目</th><th>类型</th><th>数量</th><th>单位</th><th>单项</th><th>单位</th><th>费率/元时</th><th>口径</th></tr>
          </thead>
          <tbody>${body}</tbody>
        </table>
        <div class="note ${c.net > 0 ? '' : 'danger'}">
          月净收益 ${money(Math.round(c.net))}；
          一次性投入 ${money(Math.round(c.oneOffCost))}，
          占首期预算 ${money(budget)} 的 ${pct(c.oneOffCost, budget)}%。
          ${c.net <= 0 ? '当前假设下项目不自负盈亏，应缩减范围或重谈收益口径。' : ''}
        </div>
      </div>

      <div class="panel">
        <h2>口径提醒</h2>
        <div class="grid c2" style="margin-top:10px">
          <div>
            <strong style="font-size:13px">不能做的事</strong>
            <p class="hint">把全部节省工时当成现金回款。节省的时间若没被释放为可售产能或人力，就不产生现金。</p>
          </div>
          <div>
            <strong style="font-size:13px">必须计入的事</strong>
            <p class="hint">人工复核按月发生；证据存储按 90 天保留周期计费；口径变更带来的重跑成本。</p>
          </div>
        </div>
        <div class="note warn">
          事实 f03（已确认）：收益须扣除维护及人工复核成本 —— 上表已按此口径拆分月成本。
        </div>
      </div>
    `;
  }

  /* ---------- 视图：导出 ---------- */

  function buildMarkdown() {
    const p = DATA.project;
    const st = DATA.stages.stages;
    const c = roiCalc(roiRows());
    const L = [];

    L.push(`# ${p.company} · ${p.name} —— FDE 项目工作台导出`);
    L.push('');
    L.push(`> ${p.summary}`);
    L.push('');
    L.push(`导出时间：${new Date().toLocaleString('zh-CN', { hour12: false })}`);
    L.push('');

    L.push('## 一、业务事实台账');
    L.push('');
    L.push('| 编号 | 事实 | 来源 | 状态 |');
    L.push('| --- | --- | --- | --- |');
    p.facts.forEach(f => L.push(`| ${f.id} | ${f.text} | ${f.source} | ${f.status} |`));
    L.push('');

    L.push('## 二、验收指标');
    L.push('');
    L.push('| 指标 | 现状 | 目标 | 单位 | 责任岗 | 备注 |');
    L.push('| --- | --- | --- | --- | --- | --- |');
    p.metrics.forEach(m => L.push(`| ${m.label} | ${m.baseline} | ${m.target} | ${m.unit} | ${m.owner} | ${m.note} |`));
    L.push('');

    L.push('## 三、九阶段成果');
    L.push('');
    st.forEach((s, i) => {
      const pr = SU.stageProgress(state, s, s.steps);
      const gate = SU.getGate(state, s.id);
      L.push(`### ${i + 1}. ${s.title}（${pr.done}/${pr.total}${gate.status === '通过' ? ' · 已过闸' : ''}）`);
      L.push('');
      L.push(`目标：${s.goal}`);
      L.push('');
      L.push(`闸门：${s.gate}`);
      L.push('');
      if (gate.reviewer) L.push(`评审：${gate.status} · ${gate.reviewer}${gate.note ? ' · ' + gate.note : ''}`);
      L.push('');
      s.steps.forEach((step, j) => {
        const rec = SU.getStep(state, s.id, step.id);
        L.push(`**${j + 1}. ${step.title}** ${rec.done ? '（已完成）' : '（未完成）'}`);
        L.push('');
        L.push(`- 交付物：${step.output}`);
        L.push(`- 要回答：${step.question}`);
        L.push(`- 记录：${rec.text ? rec.text.replace(/\n/g, ' ') : '_空_'}`);
        L.push('');
      });
    });

    L.push('## 四、ROI 测算');
    L.push('');
    L.push(`- 月收益：¥${Math.round(c.monthlyBenefit).toLocaleString('zh-CN')}`);
    L.push(`- 月成本：¥${Math.round(c.monthlyCost).toLocaleString('zh-CN')}`);
    L.push(`- 月净收益：¥${Math.round(c.net).toLocaleString('zh-CN')}`);
    L.push(`- 一次性投入：¥${Math.round(c.oneOffCost).toLocaleString('zh-CN')}`);
    L.push(`- 回收期：${c.payback ? c.payback + ' 个月' : '当前假设下无法回收'}`);
    L.push('');

    L.push('## 五、演示数据（房态投影）');
    L.push('');
    L.push('| 房号 | 类型 | 占用 | 清洁 | 封锁 | 展示码 | 可售 | 缺口 |');
    L.push('| --- | --- | --- | --- | --- | --- | --- | --- |');
    DATA.rooms.rooms.forEach(r => {
      const g = FDE.threeStateGap(r);
      L.push(`| ${r.no} | ${r.type} | ${r.occupied ? '在住' : '空房'} | ${FDE.CleanLabel[r.clean]} | ${r.block ? r.block.type : '—'} | ${g.status.code} ${g.status.label} | ${g.status.sellable ? '是' : '否'} | ${g.gaps.map(x => x.code).join(', ') || '—'} |`);
    });
    L.push('');

    return L.join('\n');
  }

  function viewExport() {
    const md = buildMarkdown();
    const json = Store.exportJSON(state);
    return `
      <div class="page-title">
        <div>
          <h1>导出</h1>
          <p>把工作台里的记录导成可交付的 Markdown 与 JSON，用于评审或备份。</p>
        </div>
      </div>

      <div class="panel">
        <h2>Markdown 成果包</h2>
        <p class="hint">包含事实台账、指标、九阶段记录、ROI 与演示数据，可直接贴进汇报文档。</p>
        <div style="display:flex;gap:8px;margin:12px 0">
          <button class="primary" data-dl="md">下载 .md</button>
          <button data-copy="md">复制到剪贴板</button>
        </div>
        <textarea id="md-out" readonly style="min-height:240px;font-family:ui-monospace,Consolas,monospace;font-size:12px">${esc(md)}</textarea>
      </div>

      <div class="panel">
        <h2>状态快照（JSON）</h2>
        <p class="hint">完整记录练习进度、闸门签字与 ROI 假设，可用于跨设备恢复。</p>
        <div style="display:flex;gap:8px;margin:12px 0">
          <button data-dl="json">下载 .json</button>
          <button data-copy="json">复制到剪贴板</button>
          <button class="danger" data-wipe>清空本地数据</button>
        </div>
        <textarea id="json-out" readonly style="min-height:200px;font-family:ui-monospace,Consolas,monospace;font-size:12px">${esc(json)}</textarea>
      </div>

      <div class="panel">
        <h2>参考的开源项目</h2>
        <p class="hint">房态建模参考了以下项目的领域模型，代码为本项目独立实现。</p>
        <table style="margin-top:10px">
          <thead><tr><th>项目</th><th>借鉴点</th></tr></thead>
          <tbody>
            <tr><td><strong>voyant-travel/pms</strong></td><td>dirty / clean / inspected 的清洁生命周期，以及 maintenance block 扣减库存的做法</td></tr>
            <tr><td><strong>HotelOpsManager</strong></td><td>房态看板按楼层 + 状态筛选的组织方式</td></tr>
            <tr><td><strong>hotelito</strong></td><td>单页应用 + 本地状态的管理界面结构与信息密度</td></tr>
          </tbody>
        </table>
      </div>
    `;
  }

  /* ---------- 路由 ---------- */

  const ROUTES = {
    overview: () => viewOverview(),
    pipeline: arg => viewPipeline(arg),
    demo: () => viewDemo(),
    graphs: () => viewGraphs(),
    roi: () => viewRoi(),
    export: () => viewExport()
  };

  function parseHash() {
    const h = (location.hash || '#/overview').replace(/^#\/?/, '');
    const parts = h.split('/').filter(Boolean);
    return { name: parts[0] || 'overview', arg: parts[1] || null };
  }

  function render() {
    const { name, arg } = parseHash();
    const fn = ROUTES[name] || ROUTES.overview;
    const app = $('#app');
    app.innerHTML = fn(arg);

    // 导航高亮
    document.querySelectorAll('#nav a').forEach(a => {
      const target = a.getAttribute('href').replace('#/', '');
      a.className = target === name ? 'on' : '';
    });

    window.scrollTo({ top: 0, behavior: 'instant' });
  }

  /* ---------- 事件绑定（委托） ---------- */

  function bindEvents() {
    document.addEventListener('hashchange', render);

    document.addEventListener('click', e => {
      const t = e.target.closest('[data-room],[data-toggle],[data-gate],[data-submit],[data-redraft],[data-clear-queue],[data-approve],[data-drop],[data-reset-demo],[data-roi-reset],[data-dl],[data-copy],[data-wipe]');
      if (!t) return;

      /* Demo：选房 */
      if (t.hasAttribute('data-room')) {
        ui.roomNo = t.getAttribute('data-room');
        const room = DATA.rooms.rooms.find(r => r.no === ui.roomNo);
        ui.draft = FDE.draftHandoff(room);
        render();
        return;
      }

      /* Pipeline：标记步骤完成 */
      if (t.hasAttribute('data-toggle')) {
        const stepId = t.getAttribute('data-toggle');
        const wasDone = t.getAttribute('data-done') === '1';
        SU.setStep(state, ui.stageId, stepId, { done: !wasDone });
        markSaved();
        render();
        return;
      }

      /* Pipeline：闸门 */
      if (t.hasAttribute('data-gate')) {
        const status = t.getAttribute('data-gate');
        const reviewer = ($('#gate-reviewer') || {}).value || '';
        const note = ($('#gate-note') || {}).value || '';
        if (status === '通过' && !reviewer.trim()) {
          toast('请先填写评审人姓名');
          return;
        }
        SU.setGate(state, ui.stageId, { status, reviewer: reviewer.trim(), note: note.trim() });
        markSaved();
        toast(`闸门已${status}`);
        render();
        return;
      }

      /* Demo：提交复核 */
      if (t.hasAttribute('data-submit')) {
        const room = DATA.rooms.rooms.find(r => r.no === ui.roomNo);
        const v = FDE.validateHandoff(room, ui.draft, DATA.rooms.handoffFields);
        if (!v.ok) { toast(v.errors[0]); return; }
        ui.queue.push({ ...ui.draft, at: new Date().toISOString() });
        ui.audit.push(FDE.auditEntry('前台接待员', '提交复核', room, null, ui.draft));
        toast('已进入复核队列');
        render();
        return;
      }

      if (t.hasAttribute('data-redraft')) {
        const room = DATA.rooms.rooms.find(r => r.no === ui.roomNo);
        ui.draft = FDE.draftHandoff(room);
        render();
        return;
      }

      if (t.hasAttribute('data-clear-queue')) {
        ui.queue = [];
        toast('复核队列已清空');
        render();
        return;
      }

      /* Demo：确认 / 退回 */
      if (t.hasAttribute('data-approve') || t.hasAttribute('data-drop')) {
        const i = Number(t.getAttribute('data-approve') != null ? t.getAttribute('data-approve') : t.getAttribute('data-drop'));
        const item = ui.queue[i];
        if (!item) return;
        const room = DATA.rooms.rooms.find(r => r.no === item.room);
        const approve = t.hasAttribute('data-approve');
        ui.audit.push(FDE.auditEntry(
          approve ? '客房调度员' : '客房调度员',
          approve ? '确认接收并写回' : '退回交接单',
          room || { no: item.room },
          null,
          approve ? { state: item.state, owner: item.owner } : { dropped: true }
        ));
        if (approve && room) {
          // 人工确认后按草稿口径推进演示房态
          if (item.state === '可售' && room.clean === 'clean' && !room.block) room.clean = 'inspected';
          room.owner = item.owner;
        }
        ui.queue.splice(i, 1);
        toast(approve ? '已确认写回' : '已退回');
        render();
        return;
      }

      if (t.hasAttribute('data-reset-demo')) {
        ui.roomNo = null; ui.draft = null; ui.queue = []; ui.audit = [];
        loadDataWithFallback().then(render);
        toast('演示数据已重置');
        return;
      }

      /* ROI：恢复默认 */
      if (t.hasAttribute('data-roi-reset')) {
        state.roi.rows = ROI_DEFAULTS.map(r => ({ ...r }));
        persist();
        render();
        return;
      }

      /* 导出：下载 */
      if (t.hasAttribute('data-dl')) {
        const kind = t.getAttribute('data-dl');
        const text = kind === 'md' ? buildMarkdown() : Store.exportJSON(state);
        const name = kind === 'md' ? 'FDE-山海旅居-酒店房态协同.md' : 'fde-state.json';
        download(name, text, kind === 'md' ? 'text/markdown' : 'application/json');
        return;
      }

      if (t.hasAttribute('data-copy')) {
        const kind = t.getAttribute('data-copy');
        const el = $('#' + kind + '-out');
        if (el) {
          el.removeAttribute('readonly');
          el.select();
          document.execCommand('copy');
          el.setAttribute('readonly', '');
          toast('已复制');
        }
        return;
      }

      if (t.hasAttribute('data-wipe')) {
        if (!confirm('将清空本地保存的练习记录、闸门签字与 ROI 假设，且不可恢复。继续？')) return;
        Store.reset();
        state = Store.load();
        toast('本地数据已清空');
        render();
        return;
      }
    });

    /* 输入：步骤记录 */
    document.addEventListener('input', e => {
      const ta = e.target.closest('textarea[data-step]');
      if (ta) {
        SU.setStep(state, ui.stageId, ta.getAttribute('data-step'), { text: ta.value });
        const step = ta.closest('.step');
        if (step) {
          clearTimeout(ta._t);
          ta._t = setTimeout(() => markSaved(), 300);
        }
        return;
      }

      /* 输入：交接单草稿 */
      const d = e.target.closest('[data-draft]');
      if (d) {
        ui.draft = ui.draft || {};
        ui.draft[d.getAttribute('data-draft')] = d.value;
        // 变更时只刷新校验提示，不整页重绘以免丢焦点
        refreshHandoffValidation();
        return;
      }

      /* 输入：ROI */
      const r = e.target.closest('[data-roi]');
      if (r) {
        const i = Number(r.getAttribute('data-roi'));
        const k = r.getAttribute('data-k');
        const rows = roiRows();
        rows[i][k] = Number(r.value) || 0;
        persist();
        debounceRoi();
      }
    });

    /* ROI 输入后重绘（保持滚动位置） */
    let roiTimer = null;
    function debounceRoi() {
      clearTimeout(roiTimer);
      roiTimer = setTimeout(() => {
        if (parseHash().name === 'roi') {
          const y = window.scrollY;
          render();
          window.scrollTo({ top: y, behavior: 'instant' });
        }
      }, 600);
    }
  }

  /* 只重绘交接单校验区，避免输入时丢焦点 */
  function refreshHandoffValidation() {
    const room = DATA.rooms.rooms.find(r => r.no === ui.roomNo);
    if (!room) return;
    const v = FDE.validateHandoff(room, ui.draft, DATA.rooms.handoffFields);
    const btn = document.querySelector('[data-submit]');
    if (btn) btn.disabled = !v.ok;
    let box = document.querySelector('#handoff-msg');
    if (!box) return;
    box.className = 'note' + (v.ok ? '' : ' danger');
    box.id = 'handoff-msg';
    box.innerHTML = v.ok
      ? '校验通过，可提交人工复核。'
      : v.errors.map(x => '· ' + esc(x)).join('<br>');
  }

  function download(filename, text, mime) {
    const blob = new Blob([text], { type: mime + ';charset=utf-8' });
    const a = document.createElement('a');
    a.href = URL.createObjectURL(blob);
    a.download = filename;
    document.body.appendChild(a);
    a.click();
    setTimeout(() => { URL.revokeObjectURL(a.href); a.remove(); }, 500);
    toast('已开始下载 ' + filename);
  }

  /* ---------- 启动 ---------- */

  loadDataWithFallback().then(() => {
    bindEvents();
    render();
  }).catch(err => {
    $('#app').innerHTML = `
      <div class="panel">
        <h2>数据加载失败</h2>
        <p class="hint">${esc(err.message)}</p>
        <div class="note danger">
          请确认 <code>data/</code> 目录存在，且通过本地服务器打开（不要直接双击 index.html）。
        </div>
      </div>`;
  });

})();
