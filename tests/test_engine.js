/* 业务核心单测：三态投影 / 交接单校验 / 脱敏 / 占用统计
   运行：node tests/test_engine.js（无需安装依赖） */
'use strict';

const fs = require('fs');
const path = require('path');
const assert = require('assert');

// engine.js 面向浏览器编写（挂载到 window.FDE），这里提供 window 桩后加载
global.window = {};
const code = fs.readFileSync(path.join(__dirname, '..', 'src', 'engine.js'), 'utf8');
new Function('window', code)(global.window);
const FDE = global.window.FDE;

let passed = 0;
function test(name, fn) {
  try {
    fn();
    passed += 1;
    console.log('  ok  ' + name);
  } catch (e) {
    console.error('FAIL  ' + name);
    console.error(e.message);
    process.exitCode = 1;
  }
}

/* ---------- 三态投影 ---------- */

test('VI：已查房且空房 → 可售', () => {
  const s = FDE.projectStatus({ occupied: false, clean: 'inspected' });
  assert.strictEqual(s.code, 'VI');
  assert.strictEqual(s.sellable, true);
});

test('VC：已清扫未查房 → 不可售（前台不得标可入住）', () => {
  const s = FDE.projectStatus({ occupied: false, clean: 'clean' });
  assert.strictEqual(s.code, 'VC');
  assert.strictEqual(s.sellable, false);
});

test('VD：脏房 → 不可售', () => {
  const s = FDE.projectStatus({ occupied: false, clean: 'dirty' });
  assert.strictEqual(s.code, 'VD');
  assert.strictEqual(s.sellable, false);
});

test('OOO：维修房 → 不可售（库存扣减，不是普通标签）', () => {
  const s = FDE.projectStatus({ occupied: false, clean: 'inspected', block: { type: 'OOO' } });
  assert.strictEqual(s.code, 'OOO');
  assert.strictEqual(s.sellable, false);
});

test('OOS：停用房 → 保留在库存中但仍可展示', () => {
  const s = FDE.projectStatus({ occupied: false, clean: 'inspected', block: { type: 'OOS' } });
  assert.strictEqual(s.code, 'OOS');
  assert.strictEqual(s.sellable, true);
});

test('OD/OC：在住房的清洁态只影响展示，不影响可售', () => {
  assert.strictEqual(FDE.projectStatus({ occupied: true, clean: 'dirty' }).code, 'OD');
  assert.strictEqual(FDE.projectStatus({ occupied: true, clean: 'clean' }).code, 'OC');
});

/* ---------- 三态缺口 ---------- */

test('threeStateGap：已清扫未查房 → 含 NO_INSPECT 缺口（客房与前台脱节）', () => {
  const r = FDE.threeStateGap({ occupied: false, clean: 'clean' });
  assert.ok(r.gaps.some(g => g.code === 'NO_INSPECT'));
  assert.strictEqual(r.status.code, 'VC');
});

/* ---------- 交接单校验（确定性，不交给模型） ---------- */

const baseRoom = { no: '1023', occupied: false, clean: 'clean' };
const baseFields = [
  { key: 'receiver', label: '接收人', required: true },
  { key: 'note', label: '备注', required: false },
];

test('缺必填字段 → 校验不通过', () => {
  const v = FDE.validateHandoff(baseRoom, { state: '不可售', note: 'ok' }, baseFields);
  assert.strictEqual(v.ok, false);
  assert.ok(v.errors.some(e => e.includes('接收人')));
});

test('VC 房写成可售 → 校验拦截（R1 口径）', () => {
  const v = FDE.validateHandoff(baseRoom, { state: '可售', receiver: '前台·秦芮' }, baseFields);
  assert.strictEqual(v.ok, false);
  assert.ok(v.errors.some(e => e.includes('状态冲突')));
});

test('OOO 房写成可售 → 校验拦截（R3 硬拦截）', () => {
  const room = { ...baseRoom, block: { type: 'OOO', reason: '异味', until: '周六' } };
  const v = FDE.validateHandoff(room, { state: '可售', receiver: '客房·唐映秋' }, baseFields);
  assert.strictEqual(v.ok, false);
  assert.ok(v.errors.some(e => e.includes('维修房')));
});

test('字段齐全且无冲突 → 校验通过', () => {
  const v = FDE.validateHandoff(baseRoom, { state: '不可售', receiver: '前台·林亦舟' }, baseFields);
  assert.strictEqual(v.ok, true);
  assert.deepStrictEqual(v.errors, []);
});

test('下一步动作超 40 字 → 拦截', () => {
  const v = FDE.validateHandoff(baseRoom, { state: '不可售', receiver: '前台·林亦舟', nextAction: '长'.repeat(41) }, baseFields);
  assert.strictEqual(v.ok, false);
});

/* ---------- 脱敏与审计 ---------- */

test('redact：房号、工号、手机号均被替换', () => {
  const out = FDE.redact('1023 房由工号 E1023 的张三打扫，电话 13812345678');
  assert.ok(!out.includes('1023'), '房号应被脱敏');
  assert.ok(!out.includes('E1023'), '工号应被脱敏');
  assert.ok(!out.includes('13812345678'), '手机号应被脱敏');
});

test('auditEntry：只记岗位与动作，可重建（含哈希），不留姓名', () => {
  const e = FDE.auditEntry('客房调度', '起草交接单', { no: '1023' });
  assert.strictEqual(e.actorRole, '客房调度');
  assert.ok(e.hash && /^[0-9a-f]{8}$/.test(e.hash), '审计应含可验证哈希');
  assert.ok(!('actorName' in e), '审计不得包含姓名字段');
});

test('simpleHash：同输入同输出，不同输入不同输出', () => {
  assert.strictEqual(FDE.simpleHash('abc'), FDE.simpleHash('abc'));
  assert.notStrictEqual(FDE.simpleHash('abc'), FDE.simpleHash('abd'));
});

/* ---------- 占用统计 ---------- */

test('occupancySummary：分母为全部房间，可售只含 VI', () => {
  const rooms = [
    { id: '1', occupied: false, clean: 'inspected' },
    { id: '2', occupied: false, clean: 'clean' },
    { id: '3', occupied: false, clean: 'dirty' },
    { id: '4', occupied: true, clean: 'clean', block: { type: 'OOO' } },
  ];
  const s = FDE.occupancySummary(rooms);
  assert.strictEqual(s.total, 4);
  assert.strictEqual(s.sellable, 1);
});

console.log('\n' + passed + ' 项测试通过' + (process.exitCode ? '（存在失败）' : ''));
