const state = { cases: [], selectedCaseId: null, analysis: null };

const $ = (selector) => document.querySelector(selector);
const $$ = (selector) => [...document.querySelectorAll(selector)];
const escapeHtml = (value = "") => String(value).replace(/[&<>'"]/g, (char) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", "'": "&#39;", '"': "&quot;" })[char]);
const formatTime = (iso) => new Intl.DateTimeFormat("zh-CN", { month: "numeric", day: "numeric", hour: "2-digit", minute: "2-digit" }).format(new Date(iso));

async function api(path, options = {}) {
  const response = await fetch(path, { headers: { "content-type": "application/json" }, ...options });
  const payload = await response.json();
  if (!response.ok || payload.error) throw new Error(payload.error?.message ?? "请求失败");
  return payload.data;
}

function toast(message) {
  const node = $("#toast");
  node.textContent = message;
  node.classList.add("show");
  clearTimeout(toast.timer);
  toast.timer = setTimeout(() => node.classList.remove("show"), 2200);
}

function riskClass(level) { return level.toLowerCase(); }
function emotionLabel(emotion) { return ({ CALM: "平静", CONCERNED: "担忧", FRUSTRATED: "受挫", ANGRY: "愤怒" })[emotion] ?? emotion; }

async function loadRadar(selectFirst = false) {
  const data = await api("/api/risk/cases");
  state.cases = data.cases;
  $("#summary-total").textContent = data.summary.total;
  $("#summary-critical").textContent = data.summary.critical;
  $("#summary-overdue").textContent = data.summary.overdue;
  $("#summary-effort").textContent = data.summary.average_effort;
  const select = $("#case-select");
  select.innerHTML = state.cases.map((item) => `<option value="${escapeHtml(item.case_id)}">${escapeHtml(item.case_id)} · Risk ${item.risk.score}</option>`).join("");
  if (!state.selectedCaseId || !state.cases.some((item) => item.case_id === state.selectedCaseId)) state.selectedCaseId = state.cases[0]?.case_id;
  select.value = state.selectedCaseId;
  renderRiskTable();
  if (selectFirst && state.selectedCaseId) await selectCase(state.selectedCaseId);
}

function renderRiskTable() {
  $("#risk-table").innerHTML = state.cases.map((item) => {
    const promise = item.effort.promise_overdue_hours > 0 ? `超时 ${item.effort.promise_overdue_hours}h` : item.promise.active.length ? "进行中" : "—";
    return `<tr data-case="${escapeHtml(item.case_id)}" class="${item.case_id === state.selectedCaseId ? "selected" : ""}">
      <td><strong>${escapeHtml(item.case_id)}</strong><br><small>${escapeHtml(item.product.slice(0, 15))}</small></td>
      <td><span class="risk-pill ${riskClass(item.risk.level)}">${item.risk.score} ${item.risk.level}</span></td>
      <td>${escapeHtml(emotionLabel(item.emotion.current))} ${item.emotion.trend === "ESCALATING" ? "↑" : "→"}</td>
      <td>${escapeHtml(item.effort.level)} · ${item.effort.score}</td>
      <td>${escapeHtml(promise)}</td>
      <td>${escapeHtml(item.next_best_action.label)}</td>
    </tr>`;
  }).join("");
  $$("#risk-table tr").forEach((row) => row.addEventListener("click", () => selectCase(row.dataset.case)));
}

async function selectCase(caseId) {
  state.selectedCaseId = caseId;
  $("#case-select").value = caseId;
  $("#copilot-loading").classList.remove("hidden");
  $("#copilot-content").classList.add("hidden");
  try {
    state.analysis = await api("/api/cases/analyze", { method: "POST", body: JSON.stringify({ case_id: caseId }) });
    renderCopilot();
    renderDetail();
    renderRiskTable();
  } catch (error) { toast(error.message); }
  finally { $("#copilot-loading").classList.add("hidden"); $("#copilot-content").classList.remove("hidden"); }
}

function renderConversation() {
  const timeline = state.analysis.timeline.filter((item) => ["CONTACT", "SERVICE"].includes(item.type));
  $("#conversation").innerHTML = timeline.map((item) => `<div class="message ${item.type === "CONTACT" ? "consumer" : "agent"}">${escapeHtml(item.detail)}<time>${formatTime(item.at)}</time></div>`).join("");
  $("#conversation").scrollTop = $("#conversation").scrollHeight;
}

function renderCopilot() {
  const data = state.analysis;
  const cs = data.customer_state;
  $("#story-title").textContent = data.consumer_story.what_happened;
  $("#story-latest").textContent = `“${data.consumer_story.latest_message}”`;
  $("#risk-score").textContent = cs.risk.score;
  $("#risk-orb").title = cs.risk.level;
  const journey = cs.emotion.events.map((item) => emotionLabel(item.inference.label)).join(" → ");
  $("#emotion-value").textContent = `${journey || emotionLabel(cs.emotion.current)} ${cs.emotion.trend === "ESCALATING" ? "↑" : ""}`;
  $("#emotion-causes").textContent = cs.emotion.causes.join(" · ") || "无明显升级原因";
  $("#effort-value").textContent = `${cs.effort.level} · ${cs.effort.score}`;
  $("#effort-detail").textContent = `${cs.effort.contact_count} 次联系 · 等待 ${cs.effort.waiting_hours}h`;
  $("#promise-value").textContent = cs.effort.promise_overdue_hours > 0 ? `已超时 ${cs.effort.promise_overdue_hours}h` : cs.promises.active.length ? "进行中" : "无有效承诺";
  $("#promise-detail").textContent = cs.promises.raw?.raw_text ?? "—";
  $("#emotion-evidence").innerHTML = cs.emotion.events.slice(-3).map((item) => `<div class="emotion-source"><q>${escapeHtml(item.quote)}</q><small>${escapeHtml(item.source_id)} · ${formatTime(item.at)} · 线索：${escapeHtml(item.observed_cues.join("、") || "无显式词语")}</small><span class="inference-badge">推断：${escapeHtml(emotionLabel(item.inference.label))} · ${Math.round(item.inference.confidence * 100)}%</span></div>`).join("");
  $("#emotion-actions").innerHTML = cs.emotion.action_support.map((item) => `<div class="emotion-action">${escapeHtml(item.suggestion)}</div>`).join("") || '<div class="emotion-action">保持正常服务，不因情绪标签改变规则或权限。</div>';
  $("#known-facts").innerHTML = data.consumer_story.what_we_know.map((item) => `<div class="fact-row"><span>${escapeHtml(item.label)}</span><strong>${escapeHtml(item.value)}</strong></div>`).join("");
  $("#do-not-ask").innerHTML = data.consumer_story.do_not_ask_again.map((item) => `<span class="guardrail">× ${escapeHtml(item.label)}</span>`).join("") || '<span class="guardrail">当前无禁止动作</span>';
  $("#nba-label").textContent = data.consumer_story.next_best_action.label;
  $("#nba-reason").textContent = data.consumer_story.next_best_action.reason;
  $("#suggested-reply").textContent = data.consumer_story.suggested_response;
  const obligation = data.accountability_state.open_obligation;
  $("#obligation-card").classList.toggle("hidden", !obligation);
  $("#approve-button").disabled = Boolean(obligation) || cs.resolution.status === "RESOLVED";
  if (obligation) {
    $("#obligation-status").textContent = `${obligation.status} · ${obligation.milestone}`;
    $("#obligation-detail").innerHTML = `执行方：<strong>${escapeHtml(obligation.executor)}</strong><br>截止时间：${formatTime(obligation.deadline)}<br>完成条件：${escapeHtml(obligation.resolution_condition)}`;
  }
  renderConversation();
}

function renderDetail() {
  const data = state.analysis;
  if (!data) return;
  $("#detail-title").textContent = `${data.case_id} · Risk ${data.customer_state.risk.score}`;
  $("#risk-factors").innerHTML = data.customer_state.risk.factors.map((factor) => `<div class="factor"><strong>${escapeHtml(factor.label)}</strong><span>+${factor.weight}</span><small>${escapeHtml(factor.evidence ?? "")}</small></div>`).join("") || '<p class="story-latest">当前无明显风险驱动因素。</p>';
  $("#timeline").innerHTML = data.timeline.slice(-8).reverse().map((item) => `<div class="timeline-item"><strong>${escapeHtml(item.title)}</strong><p>${escapeHtml(item.detail)}</p><time>${formatTime(item.at)}</time></div>`).join("");
  const resolution = data.customer_state.resolution;
  $("#resolution-status").innerHTML = `<div class="resolution-box"><strong>${escapeHtml(resolution.status)}</strong><p>责任方：${escapeHtml(resolution.owner)}<br>完成条件：${escapeHtml(resolution.completion_condition)}</p><span class="status-pill risk-pill ${riskClass(data.customer_state.risk.level)}">${escapeHtml(data.customer_state.risk.level)}</span></div>`;
}

async function evaluateAction() {
  try {
    const data = await api("/api/actions/evaluate", { method: "POST", body: JSON.stringify({ case_id: state.selectedCaseId, prepared_action: { action_id: `web-${Date.now()}`, action_type: "ASK_EVIDENCE", requested_scope: state.analysis.accountability_state.current_scope, requires_human_approval: false } }) });
    toast(`${data.decision} · ${data.rule_id}：${data.reason}`);
  } catch (error) { toast(error.message); }
}

async function approve() {
  try {
    const now = new Date();
    const data = await api("/api/resolutions/approve", { method: "POST", body: JSON.stringify({ case_id: state.selectedCaseId, candidate_type: "CHECK_REPLACEMENT_FULFILLMENT", approver_id: "demo-agent-001", idempotency_key: `approve-${state.selectedCaseId}-${Date.now()}`, human_edits: { executor: "WAREHOUSE", next_check_at: new Date(now.getTime() + 2 * 3_600_000).toISOString(), recovery_if_missed: "超时后自动进入 Risk Radar 并提交主管升级候选。" } }) });
    toast("责任已创建，Promise-to-Action 开始运行");
    await selectCase(data.case_id);
    await loadRadar();
  } catch (error) { toast(error.message); }
}

async function shipment(eventType) {
  try {
    const data = await api("/api/events/shipment", { method: "POST", body: JSON.stringify({ case_id: state.selectedCaseId, event_id: `evt-${Date.now()}`, event_type: eventType, event_time: new Date().toISOString(), idempotency_key: `ship-${eventType}-${Date.now()}` }) });
    toast(`${eventType} 已处理 · ${data.customer_state.resolution.status}`);
    await selectCase(data.case_id);
    await loadRadar();
  } catch (error) { toast(error.message); }
}

function switchView(view) {
  $$(".tab").forEach((tab) => tab.classList.toggle("active", tab.dataset.view === view));
  $$(".view").forEach((node) => node.classList.toggle("active", node.id === `${view}-view`));
}

$$('.tab').forEach((tab) => tab.addEventListener("click", () => switchView(tab.dataset.view)));
$("#case-select").addEventListener("change", (event) => selectCase(event.target.value));
$("#evaluate-button").addEventListener("click", evaluateAction);
$("#approve-button").addEventListener("click", approve);
$("#copy-reply").addEventListener("click", async () => { await navigator.clipboard.writeText(state.analysis.consumer_story.suggested_response); toast("回复已复制"); });
$("#refresh-radar").addEventListener("click", async () => { await loadRadar(); toast("风险状态已刷新"); });
$$('[data-event]').forEach((button) => button.addEventListener("click", () => shipment(button.dataset.event)));

loadRadar(true).catch((error) => toast(error.message));
