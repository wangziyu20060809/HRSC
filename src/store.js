/* 本地存储：练习记录、阶段成果、ROI、Demo 数据全部落在 localStorage */
const KEY = 'fde-travel-hotel-v1';

const Store = {
  load() {
    try {
      const raw = localStorage.getItem(KEY);
      if (raw) return JSON.parse(raw);
    } catch (e) { /* 损坏则重置 */ }
    return this.blank();
  },
  blank() {
    return {
      version: 1,
      attempts: [{ id: 'a-' + Date.now(), name: '练习 1', createdAt: new Date().toISOString() }],
      activeAttempt: null,
      stages: {},
      roi: { rows: [], budget: 130000, months: 12 }
    };
  },
  save(state) {
    localStorage.setItem(KEY, JSON.stringify(state));
    if (window.FDEHooks && window.FDEHooks.onSave) window.FDEHooks.onSave(state);
  },
  reset() { localStorage.removeItem(KEY); },
  exportJSON(state) {
    return JSON.stringify(state, null, 2);
  }
};

function attemptOf(state) {
  if (!state.attempts.length) state.attempts.push({ id: 'a-' + Date.now(), name: '练习 1', createdAt: new Date().toISOString() });
  if (!state.activeAttempt || !state.attempts.some(a => a.id === state.activeAttempt)) {
    state.activeAttempt = state.attempts[0].id;
  }
  return state.attempts.find(a => a.id === state.activeAttempt);
}

/* 阶段成果：按 练习ID / 阶段 / 步骤 三级存 */
function getStep(state, stageId, stepId) {
  const a = attemptOf(state);
  return (state.stages[a.id] && state.stages[a.id][stageId] && state.stages[a.id][stageId][stepId]) || { text: '', done: false, updatedAt: null };
}

function setStep(state, stageId, stepId, patch) {
  const a = attemptOf(state);
  state.stages[a.id] = state.stages[a.id] || {};
  state.stages[a.id][stageId] = state.stages[a.id][stageId] || {};
  const prev = state.stages[a.id][stageId][stepId] || { text: '', done: false };
  state.stages[a.id][stageId][stepId] = { ...prev, ...patch, updatedAt: new Date().toISOString() };
  Store.save(state);
}

function stageProgress(state, stage, steps) {
  const a = attemptOf(state);
  const bag = (state.stages[a.id] && state.stages[a.id][stage.id]) || {};
  const done = steps.filter(s => bag[s.id] && bag[s.id].done).length;
  return { done, total: steps.length, pct: Math.round((done / steps.length) * 100) };
}

/* 闸门评审：阶段通过需人工签字 */
function getGate(state, stageId) {
  const a = attemptOf(state);
  return (state.gates && state.gates[a.id] && state.gates[a.id][stageId]) || { status: '未评审', reviewer: '', note: '', at: null };
}

function setGate(state, stageId, patch) {
  const a = attemptOf(state);
  state.gates = state.gates || {};
  state.gates[a.id] = state.gates[a.id] || {};
  state.gates[a.id][stageId] = { ...(state.gates[a.id][stageId] || {}), ...patch, at: new Date().toISOString() };
  Store.save(state);
}

window.Store = Store;
window.StateUtil = { attemptOf, getStep, setStep, stageProgress, getGate, setGate };
