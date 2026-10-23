/* 房态引擎：三态投影 + 确定性校验 + 审计留痕
   参照 voyant-travel/pms 的 dirty/clean/inspected 生命周期与 maintenance block 扣减库存。 */

const CleanLabel = { dirty: '脏房', clean: '已清扫', inspected: '已查房' };
const BlockLabel = { OOO: '维修房 OOO', OOS: '停用房 OOS' };

/* 房态不是单字段：由「占用 / 清洁 / 库存封锁」三个事实投影出展示码 */
function projectStatus(room) {
  if (room.block && room.block.type === 'OOO') return { code: 'OOO', label: '维修房', sellable: false, tone: 'danger' };
  if (room.block && room.block.type === 'OOS') return { code: 'OOS', label: '停用房', sellable: true, tone: 'warn' };
  if (room.occupied) return room.clean === 'clean'
    ? { code: 'OC', label: '在住·已整理', sellable: false, tone: 'info' }
    : { code: 'OD', label: '在住·待整理', sellable: false, tone: 'info' };
  if (room.clean === 'inspected') return { code: 'VI', label: '可售', sellable: true, tone: 'ok' };
  if (room.clean === 'clean') return { code: 'VC', label: '已清扫·待查房', sellable: false, tone: 'warn' };
  return { code: 'VD', label: '脏房', sellable: false, tone: 'muted' };
}

/* 三态一致：前台说的「可售」必须等于投影结果，否则就是误判 */
function threeStateGap(room) {
  const p = projectStatus(room);
  const gaps = [];
  if (room.clean === 'clean' && !room.occupied && p.code === 'VC') {
    gaps.push({ code: 'NO_INSPECT', text: '已清扫但未查房，不可售', owner: '客房主管' });
  }
  if (room.block && room.block.type === 'OOO') {
    gaps.push({ code: 'IN_INVENTORY', text: '维修房仍在渠道库存中', owner: 'PMS 工程师' });
  }
  if (room.block && room.block.type === 'OOS') {
    gaps.push({ code: 'SHOW_OOS', text: '停用房可售，交接须提示原因', owner: '前台' });
  }
  if (!room.owner && (p.code === 'VC' || p.code === 'VD')) {
    gaps.push({ code: 'NO_OWNER', text: '异常无具名接收人', owner: '客房调度' });
  }
  return { status: p, gaps };
}

/* 确定性校验：能算出来的不让模型判断 */
function validateHandoff(room, draft, fields) {
  const errors = [];
  const missing = fields.filter(f => f.required && !String(draft[f.key] || '').trim());
  missing.forEach(f => errors.push(`缺少必填项：${f.label}`));
  const gaps = threeStateGap(room);
  if (draft.state === '可售' && !gaps.status.sellable) {
    errors.push(`状态冲突：房态为「${gaps.status.label}」，不能写成可售`);
  }
  if (room.block && room.block.type === 'OOO' && draft.state === '可售') {
    errors.push('维修房不得出现在可售清单');
  }
  if (draft.nextAction && draft.nextAction.length > 40) {
    errors.push('下一步动作超过 40 字，高峰填写会被绕过');
  }
  return { ok: errors.length === 0, errors };
}

/* 伪脱敏：送模型前替换房间号与工号 */
function redact(text) {
  return String(text)
    .replace(/\b(1[0-9]{3})\b/g, '[房号]')
    .replace(/\b(E|S|H)\d{4}\b/g, '[工号]')
    .replace(/1[3-9]\d{9}/g, '[手机号]');
}

/* 审计链：单次处理可重建，但只留岗位不留个人信息 */
function auditEntry(actorRole, action, room, before, after) {
  return {
    at: new Date().toISOString(),
    actorRole,
    action,
    room: room.no,
    before: before || null,
    after: after || null,
    hash: simpleHash(`${actorRole}|${action}|${room.no}|${JSON.stringify(after)}`)
  };
}

function simpleHash(s) {
  let h = 0;
  for (let i = 0; i < s.length; i++) { h = (h * 31 + s.charCodeAt(i)) | 0; }
  return (h >>> 0).toString(16).padStart(8, '0');
}

/* 交接单自动起草：只生成草稿，必须人工确认 */
function draftHandoff(room) {
  const g = threeStateGap(room);
  const blocker = room.block
    ? `${BlockLabel[room.block.type]}：${room.block.reason}（预计 ${room.block.until}）`
    : (g.status.code === 'VC' ? '查房未完成' : '');
  return {
    room: room.no,
    state: g.status.sellable ? '可售' : '不可售',
    blocker,
    owner: g.gaps[0] ? g.gaps[0].owner : '',
    nextAction: g.status.code === 'VC' ? '主管查房后恢复可售' : (room.block ? '跟进维修并复审' : '正常入住'),
    eta: room.block ? room.block.until : ''
  };
}

function occupancySummary(rooms) {
  const sellable = rooms.filter(r => projectStatus(r).sellable).length;
  const ooo = rooms.filter(r => r.block && r.block.type === 'OOO').length;
  const pending = rooms.filter(r => r.clean === 'clean' && !r.occupied && !r.block).length;
  const dirty = rooms.filter(r => r.clean === 'dirty' && !r.occupied && !r.block).length;
  return {
    total: rooms.length,
    sellable, ooo, pending, dirty,
    rate: Math.round((sellable / rooms.length) * 100)
  };
}

window.FDE = { projectStatus, threeStateGap, validateHandoff, redact, auditEntry, simpleHash, draftHandoff, occupancySummary, CleanLabel, BlockLabel };
