const state = { cases: [], selectedCaseId: null, analysis: null, jev: null, emergingIssues: [], monitorStatus: null, focusCardKey: null, storyCards: [], priorityMode: false, priorityOpen: false, conversationHistoryOpen: false };

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
function compactDateRange(items) {
  if (!items.length) return "此前";
  return `${formatTime(items[0].at)}–${formatTime(items.at(-1).at)}`;
}

function priorityScore(item) {
  const emotionBoost = item.emotion.trend === "ESCALATING" ? 8 : 0;
  const promiseBoost = Math.min((item.effort.promise_overdue_hours ?? 0) * 3, 24);
  const waitingBoost = Math.min((item.effort.waiting_hours ?? 0) / 3, 18);
  const contactBoost = Math.min((item.effort.contact_count ?? 0) * 2, 12);
  const activePromiseBoost = item.promise.active.length ? 6 : 0;
  return Math.round(item.risk.score + emotionBoost + promiseBoost + waitingBoost + contactBoost + activePromiseBoost);
}

function priorityBand(item) {
  const score = priorityScore(item);
  if (score >= 120 || item.effort.promise_overdue_hours > 0) return "red";
  if (score >= 95 || item.risk.level === "HIGH") return "orange";
  return "yellow";
}

function priorityReasons(item) {
  const reasons = [];
  if (item.effort.promise_overdue_hours > 0) reasons.push(`承诺超时 ${item.effort.promise_overdue_hours}h`);
  if (item.emotion.trend === "ESCALATING") reasons.push("情绪上升");
  if (item.effort.contact_count >= 3) reasons.push(`重复联系 ${item.effort.contact_count} 次`);
  if (item.promise.active.length) reasons.push("已有承诺待闭环");
  if (!reasons.length) reasons.push("风险与等待时间综合靠前");
  return reasons;
}

function queueCases() {
  const items = [...state.cases];
  if (!state.priorityMode) return items;
  return items.sort((a, b) => priorityScore(b) - priorityScore(a));
}

function renderQueueControls() {
  if (!state.cases.length) return;
  const ordered = queueCases();
  const currentIndex = Math.max(0, ordered.findIndex((item) => item.case_id === state.selectedCaseId));
  const counts = state.cases.reduce((acc, item) => {
    acc[priorityBand(item)] += 1;
    return acc;
  }, { red: 0, orange: 0, yellow: 0 });
  const selected = ordered[currentIndex] ?? ordered[0];
  $("#case-position").textContent = selected ? `${state.priorityMode ? "Priority" : "Current"} · ${currentIndex + 1}/${ordered.length}` : "—";
  $("#priority-counts").textContent = `${counts.red}R / ${counts.orange}O / ${counts.yellow}Y`;
  $("#priority-toggle").classList.toggle("active", state.priorityMode);
  $("#priority-toggle").setAttribute("aria-expanded", String(state.priorityOpen));
  $("#priority-mode-label").textContent = state.priorityMode ? "按 Covenia Priority 排序" : "按当前会话顺序";
  $("#priority-panel").classList.toggle("hidden", !state.priorityOpen);
  $("#priority-list").innerHTML = ordered.slice(0, 6).map((item, index) => {
    const band = priorityBand(item);
    const selectedClass = item.case_id === state.selectedCaseId ? "selected" : "";
    const whyLabel = index === 0 ? "Why #1" : "Why";
    return `<button type="button" class="priority-item ${band} ${selectedClass}" data-case="${escapeHtml(item.case_id)}">
      <span>${index + 1}</span>
      <strong>${escapeHtml(item.case_id)} · ${priorityScore(item)}</strong>
      <small>${escapeHtml(whyLabel)}：${escapeHtml(priorityReasons(item).join(" · "))}</small>
    </button>`;
  }).join("");
  $$("#priority-list [data-case]").forEach((button) => button.addEventListener("click", () => selectCase(button.dataset.case)));
}

function moveCase(step) {
  const ordered = queueCases();
  if (!ordered.length) return;
  const currentIndex = Math.max(0, ordered.findIndex((item) => item.case_id === state.selectedCaseId));
  const nextIndex = (currentIndex + step + ordered.length) % ordered.length;
  selectCase(ordered[nextIndex].case_id);
}

function scrollStateTiles(direction) {
  const deck = $("#story-deck");
  const cardWidth = deck.querySelector(".state-tile")?.getBoundingClientRect().width ?? 220;
  deck.scrollBy({ left: direction * (cardWidth + 12), behavior: "smooth" });
}

async function loadRadar(selectFirst = false) {
  const [data, emerging] = await Promise.all([api("/api/risk/cases"), api("/api/emerging-issues")]);
  state.cases = data.cases;
  state.emergingIssues = emerging.issues;
  $("#summary-total").textContent = data.summary.total;
  $("#summary-critical").textContent = data.summary.critical;
  $("#summary-overdue").textContent = data.summary.overdue;
  $("#summary-effort").textContent = data.summary.average_effort;
  $("#summary-emerging").textContent = emerging.issues.length;
  $("#emerging-issues").innerHTML = emerging.issues.map((issue) => `<div class="emerging-issue"><div><strong>${escapeHtml(issue.fingerprint.product_name)} · ${escapeHtml(issue.fingerprint.affected_component)}</strong><p>${escapeHtml(issue.explanation)} ${issue.growth_percent === null ? "无前序基线" : `较前一窗口 ${issue.growth_percent >= 0 ? "+" : ""}${issue.growth_percent}%`} · ${escapeHtml(issue.source_coverage.join(" + "))}</p></div><div class="issue-count">${issue.unique_consumer_count}<small>独立消费者</small></div></div>`).join("") || '<p class="story-latest">当前窗口未达到聚类阈值。</p>';
  $("#emerging-disclosure").textContent = emerging.disclosure;
  const select = $("#case-select");
  select.innerHTML = state.cases.map((item) => `<option value="${escapeHtml(item.case_id)}">${escapeHtml(item.case_id)} · Risk ${item.risk.score}</option>`).join("");
  if (!state.selectedCaseId || !state.cases.some((item) => item.case_id === state.selectedCaseId)) state.selectedCaseId = state.cases[0]?.case_id;
  select.value = state.selectedCaseId;
  renderQueueControls();
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
  state.focusCardKey = null;
  state.conversationHistoryOpen = false;
  $("#case-select").value = caseId;
  renderQueueControls();
  $("#copilot-loading").classList.remove("hidden");
  $("#copilot-content").classList.add("hidden");
  try {
    const body = JSON.stringify({ case_id: caseId });
    const [analysis, jevResult] = await Promise.all([
      api("/api/cases/analyze", { method: "POST", body }),
      api("/api/jev/cases/analyze", { method: "POST", body }).catch((error) => ({ jev: { status: "ERROR", reason: error.message, signals: null, governance: { disclaimer: "JEV 暂不可用，现有规则链继续工作。" } } })),
    ]);
    state.analysis = analysis;
    state.jev = jevResult.jev;
    renderCopilot();
    renderDetail();
    renderRiskTable();
    renderQueueControls();
  } catch (error) { toast(error.message); }
  finally { $("#copilot-loading").classList.add("hidden"); $("#copilot-content").classList.remove("hidden"); }
}

function renderJev() {
  const jev = state.jev;
  if (!jev || jev.status !== "READY") {
    $("#jev-status").textContent = jev?.status ?? "UNAVAILABLE";
    $("#jev-signals").innerHTML = `<p class="story-latest">JEV 信号不可用：${escapeHtml(jev?.reason ?? "未配置")}。Covenia 继续使用现有确定性规则。</p>`;
    $("#jev-governance").textContent = jev?.governance?.disclaimer ?? "软信号失败不得阻断客服工作流。";
    return;
  }
  const emotion = jev.signals.emotion_change;
  const human = jev.signals.needs_human_review;
  const urgency = jev.signals.service_urgency;
  const preview = jev.decision_support.experimental_formula_preview;
  $("#jev-status").textContent = `${jev.provider} · ${jev.model}`;
  $("#jev-signals").innerHTML = `
    <div class="jev-signal"><span>P(情绪恶化)</span><strong>${Math.round((emotion.probabilities.worsening ?? 0) * 100)}%</strong><small>Choice · ${escapeHtml(emotion.selected)} · confidence ${Math.round(emotion.confidence * 100)}%</small></div>
    <div class="jev-signal"><span>P(需人工复核)</span><strong>${Math.round(human.probability * 100)}%</strong><small>Noul · 阈值 ${Math.round(human.threshold * 100)}% · ${human.candidate ? "候选" : "未触发"}</small></div>
    <div class="jev-signal"><span>服务紧迫度</span><strong>${Number(urgency.score).toFixed(1)} / 3</strong><small>Score · confidence ${Math.round(urgency.confidence * 100)}%</small></div>
    <div class="jev-signal experimental"><span>软信号公式预览</span><strong>${preview.soft_signal_points}</strong><small>${escapeHtml(preview.expression)} · 不计入当前 Risk</small></div>`;
  $("#jev-governance").innerHTML = `<strong>${jev.mode === "live" ? "LIVE JEV" : "CONTRACT MOCK"}</strong> · ${escapeHtml(jev.governance.disclaimer)}`;
}

function renderConversation() {
  const timeline = state.analysis.timeline.filter((item) => ["CONTACT", "SERVICE"].includes(item.type));
  const history = timeline.slice(0, -1);
  const today = timeline.slice(-1);
  $("#conversation").innerHTML = `
    ${history.length ? `<article class="history-summary">
      <span>Earlier conversation</span>
      <strong>${history.length} 条消息已由 Covenia 总结</strong>
      <p>${compactDateRange(history)} · 已完成问题说明 · 已提交证据 · 已形成服务承诺</p>
      <button id="history-toggle" type="button" aria-expanded="${state.conversationHistoryOpen}">${state.conversationHistoryOpen ? "收起历史" : "展开历史"}</button>
    </article>` : ""}
    ${state.conversationHistoryOpen ? `<div class="history-thread">
      ${history.map((item) => `<div class="message ${item.type === "CONTACT" ? "consumer" : "agent"}">${escapeHtml(item.detail)}<time>${formatTime(item.at)}</time></div>`).join("")}
    </div>` : ""}
    <div class="today-divider"><span>Today</span></div>
    ${today.map((item) => `<div class="message ${item.type === "CONTACT" ? "consumer" : "agent"}">${escapeHtml(item.detail)}<time>${formatTime(item.at)}</time></div>`).join("")}
  `;
  $("#history-toggle")?.addEventListener("click", () => {
    state.conversationHistoryOpen = !state.conversationHistoryOpen;
    renderConversation();
  });
  $("#conversation").scrollTop = state.conversationHistoryOpen ? 0 : $("#conversation").scrollHeight;
}

function buildStoryCards(data) {
  const cs = data.customer_state;
  const known = data.consumer_story.what_we_know;
  const emotionJourney = cs.emotion.events.map((item) => emotionLabel(item.inference.label)).join(" → ") || emotionLabel(cs.emotion.current);
  const promiseText = cs.promises.raw?.raw_text ?? "尚无有效承诺";
  const evidenceItems = known.map((item) => `${item.label}：${item.value}`);
  const evidenceSummary = evidenceItems.slice(0, 3);
  const evidenceStatus = data.accountability_state.evidence_status;
  const scope = data.accountability_state.current_scope;
  const missingEvidence = evidenceStatus === "VALID"
    ? ["暂无待补充证据。"]
    : evidenceStatus === "MISMATCHED"
      ? [`只补当前范围缺失材料：${scope.sku_id} · ${scope.issue_type}。不要重复索要已提交证据。`]
      : ["图片或事实需要人工复核；先转人工判断，不要求消费者重复解释。"];
  return [
    {
      key: "story",
      eyebrow: "Consumer Story",
      title: data.consumer_story.what_happened,
      body: `她正在问：“${data.consumer_story.latest_message}”`,
      tags: ["历史已总结", `${cs.effort.contact_count} 次联系`, cs.risk.level],
      focusTitle: "发生了什么",
      points: [
        ["01", data.consumer_story.what_happened],
        ["02", data.consumer_story.latest_message],
        ["03", data.consumer_story.next_best_action.reason],
      ],
    },
    {
      key: "emotion",
      eyebrow: "Emotion & Effort",
      title: `${emotionJourney}${cs.emotion.trend === "ESCALATING" ? " ↑" : ""}`,
      body: `当前 effort ${cs.effort.score}，已等待 ${cs.effort.waiting_hours}h。情绪只作为沟通上下文，不参与 Risk Score。`,
      tags: [cs.effort.level, `${cs.effort.contact_count} 次联系`, "Advisory only"],
      focusTitle: "为什么体验恶化",
      points: [
        ["情绪", cs.emotion.causes.join("；") || "没有明显恶化线索"],
        ["努力", `${cs.effort.contact_count} 次联系 · 等待 ${cs.effort.waiting_hours}h`],
        ["边界", "情绪不覆盖体验防线规则，也不单独决定风险分数。"],
      ],
    },
    {
      key: "evidence",
      eyebrow: "Evidence",
      title: `${cs.evidence.count} 项证据 · ${cs.evidence.status}`,
      body: evidenceStatus === "VALID" ? "已知证据足够，禁止重复索证。" : "只列当前缺口，不让消费者重复提交已有材料。",
      tags: ["来源可追溯", "避免重复索证", "Raw Chat = Evidence"],
      focusTitle: "证据状态",
      knownEvidence: evidenceItems,
      missingEvidence,
      doNotAsk: data.consumer_story.do_not_ask_again.map((item) => item.label),
    },
    {
      key: "journey",
      eyebrow: "Journey",
      title: `${cs.effort.contact_count} 次联系 · 已等待 ${cs.effort.waiting_hours}h`,
      body: `当前链路从咨询、举证到服务承诺已经连起来，优先避免让消费者重新解释。`,
      tags: ["Timeline", `${cs.effort.level} effort`, "不中断上下文"],
      focusTitle: "服务旅程断点",
      points: data.timeline.slice(-4).reverse().map((item) => [formatTime(item.at), `${item.title}：${item.detail}`]),
    },
    {
      key: "promise",
      eyebrow: "Promise",
      title: cs.effort.promise_overdue_hours > 0 ? `承诺已超时 ${cs.effort.promise_overdue_hours}h` : cs.promises.active.length ? "承诺正在运行" : "承诺需要确认",
      body: promiseText,
      tags: [cs.promises.active.length ? "Active" : "No active promise", "Promise-to-Action", cs.resolution.status],
      focusTitle: "承诺如何运行",
      points: [
        ["来源", promiseText],
        ["状态", `Resolution ${cs.resolution.status} · owner ${cs.resolution.owner}`],
        ["完成", `完成条件：${cs.resolution.completion_condition}`],
      ],
    },
    {
      key: "action",
      eyebrow: "Next Best Action",
      title: data.consumer_story.next_best_action.label,
      body: data.consumer_story.next_best_action.reason,
      tags: ["Decision", "One clear next step", "低打扰"],
      focusTitle: "现在应该做什么",
      points: [
        ["做", data.consumer_story.next_best_action.label],
        ["不做", data.consumer_story.do_not_ask_again.map((item) => item.label).join("；") || "当前无禁止动作"],
        ["回复", data.consumer_story.suggested_response],
      ],
    },
  ];
}

function renderStoryDeck() {
  const cards = state.storyCards;
  if (!cards.length) return;
  const focus = state.focusCardKey ? cards.find((card) => card.key === state.focusCardKey) : null;
  const deck = $("#story-deck");
  const slider = deck.closest(".state-slider");
  const focusView = $("#focus-view");
  const cardClasses = ["card-story", "card-emotion", "card-evidence", "card-journey", "card-promise", "card-action"];
  slider.classList.toggle("hidden", Boolean(focus));
  focusView.classList.toggle("hidden", !focus);
  focusView.classList.remove(...cardClasses);
  if (focus) {
    focusView.classList.add(`card-${focus.key}`);
    $("#focus-eyebrow").textContent = focus.eyebrow;
    $("#focus-title").textContent = focus.focusTitle;
    if (focus.key === "evidence") {
      $("#focus-points").innerHTML = `
        <div class="evidence-focus">
          <section>
            <h3>已知证据</h3>
            ${focus.knownEvidence.map((item) => `<p class="evidence-line known">✓ ${escapeHtml(item)}</p>`).join("") || '<p class="evidence-line">暂无已知证据。</p>'}
          </section>
          <section>
            <h3>待补充证据</h3>
            ${focus.missingEvidence.map((item) => `<p class="evidence-line pending">● ${escapeHtml(item)}</p>`).join("")}
          </section>
          <section class="do-not-ask-chart">
            <h3>❌ 不要再问</h3>
            ${focus.doNotAsk.map((item) => `<p class="evidence-line blocked">❌ ${escapeHtml(item)}</p>`).join("") || '<p class="evidence-line">暂无禁止动作。</p>'}
          </section>
        </div>`;
    } else {
      $("#focus-points").innerHTML = focus.points.map(([label, text]) => `<div><span>${escapeHtml(label)}</span><p>${escapeHtml(text)}</p></div>`).join("");
    }
    return;
  }
  const entryCards = cards.filter((card) => ["emotion", "evidence", "journey", "promise"].includes(card.key));
  deck.innerHTML = entryCards.map((card) => `<button class="state-tile card-${escapeHtml(card.key)}" type="button" data-focus-key="${escapeHtml(card.key)}">
    <span>${escapeHtml(card.eyebrow)}</span>
    <strong>${escapeHtml(card.title)}</strong>
    <p>${escapeHtml(card.body)}</p>
    <em>查看判断依据 →</em>
  </button>`).join("");
  $$("#story-deck [data-focus-key]").forEach((button) => button.addEventListener("click", () => { state.focusCardKey = button.dataset.focusKey; renderStoryDeck(); }));
}

function renderCopilot() {
  const data = state.analysis;
  const cs = data.customer_state;
  renderJev();
  $("#story-title").textContent = data.consumer_story.what_happened;
  $("#story-latest").textContent = `“${data.consumer_story.latest_message}”`;
  $("#story-tags").innerHTML = [`${cs.effort.contact_count} 次联系`, cs.effort.promise_overdue_hours > 0 ? `承诺超时 ${cs.effort.promise_overdue_hours}h` : "承诺待跟进", cs.risk.level].map((item) => `<small>${escapeHtml(item)}</small>`).join("");
  $("#risk-score").textContent = cs.risk.score;
  $("#risk-orb").title = cs.risk.level;
  state.storyCards = buildStoryCards(data);
  renderStoryDeck();
  const fusion = data.multi_source_fusion;
  $("#fusion-status").textContent = `${fusion.status} · ${Math.round(fusion.completeness * 100)}%`;
  $("#fusion-sources").innerHTML = fusion.sources.map((source) => `<div class="fusion-source"><strong>${escapeHtml(source.type)}</strong><span>${source.count}</span><small title="${escapeHtml(source.source_ids.join(" · "))}">${escapeHtml(source.authority)}</small></div>`).join("");
  $("#fusion-joins").innerHTML = fusion.joins.map((join) => `<span class="fusion-join">${escapeHtml(join.from)} → ${escapeHtml(join.to)} · ${escapeHtml(join.status)}</span>`).join("");
  $("#do-not-ask").innerHTML = data.consumer_story.do_not_ask_again.map((item) => `<span class="guardrail">❌ ${escapeHtml(item.label)}</span>`).join("") || '<span class="guardrail">当前无禁止动作</span>';
  $("#nba-label").textContent = data.consumer_story.next_best_action.label;
  $("#nba-reason").textContent = data.consumer_story.next_best_action.reason;
  $("#suggested-reply").textContent = data.consumer_story.suggested_response;
  const handoff = data.handoff_package;
  const handoffRows = [
    ["当前诉求", handoff.current_intent.current_goal],
    ["已知事实", handoff.what_we_know.map((item) => `${item.label}：${item.value}`).join("；")],
    ["已尝试", handoff.what_has_been_tried.map((item) => `${item.type} ${item.status}`).join("；") || "无"],
    ["Emotion", `${emotionLabel(handoff.emotion.current)} ${handoff.emotion.trend}`],
    ["Effort", `${handoff.effort.level} · ${handoff.effort.score}`],
    ["Promise", handoff.promise.raw?.raw_text ?? "无"],
    ["不要再问", handoff.do_not_ask_again.map((item) => item.label).join("；") || "无"],
    ["建议动作", handoff.next_best_action.label],
  ];
  $("#handoff-package").innerHTML = handoffRows.map(([label, value]) => `<div class="handoff-row"><span>${escapeHtml(label)}</span><strong>${escapeHtml(value)}</strong></div>`).join("");
  const obligation = data.accountability_state.open_obligation;
  $("#obligation-card").classList.toggle("hidden", !obligation);
  $("#approve-button").disabled = Boolean(obligation) || cs.resolution.status === "RESOLVED";
  if (obligation) {
    $("#obligation-status").textContent = `${obligation.status} · ${obligation.milestone}`;
    $("#obligation-detail").innerHTML = `执行方：<strong>${escapeHtml(obligation.executor)}</strong><br>截止时间：${formatTime(obligation.deadline)}<br>完成条件：${escapeHtml(obligation.resolution_condition)}`;
    const monitor = cs.promises.monitoring;
    $("#deadline-monitor").textContent = `Deadline Monitor：${monitor.status}${monitor.last_checked_at ? ` · 最近检查 ${formatTime(monitor.last_checked_at)}` : " · 等待首次检查"}${monitor.escalation_reason ? ` · ${monitor.escalation_reason}` : ""}`;
  }
  renderConversation();
}

function renderDetail() {
  const data = state.analysis;
  if (!data) return;
  $("#detail-title").textContent = `${data.case_id} · Risk ${data.customer_state.risk.score}`;
  $("#risk-factors").innerHTML = data.customer_state.risk.factors.map((factor) => `<div class="factor"><strong>${escapeHtml(factor.label)}</strong><span>+${factor.weight}</span><small>${escapeHtml(factor.evidence ?? "")}</small></div>`).join("") || '<p class="story-latest">当前无明显风险驱动因素。</p>';
  $("#timeline").innerHTML = data.timeline.slice(-10).reverse().map((item) => `<div class="timeline-item"><strong>${escapeHtml(item.title)}<span class="timeline-source">${escapeHtml(item.source_type)}</span></strong><p>${escapeHtml(item.detail)}</p><time>${formatTime(item.at)} · ${escapeHtml(item.source_ids.join("、"))}</time></div>`).join("");
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

async function pollDeadlineMonitor() {
  if (!state.analysis?.accountability_state.open_obligation) return;
  try {
    const data = await api("/api/monitor/deadlines");
    const current = data.cases.find((item) => item.case_id === state.selectedCaseId);
    if (!current?.monitor) return;
    const fingerprint = `${current.monitor.status}:${current.monitor.last_checked_at}`;
    if (state.monitorStatus && state.monitorStatus !== fingerprint && current.monitor.status === "ESCALATED") {
      toast("承诺已超时，Deadline Monitor 已自动升级风险");
      await selectCase(state.selectedCaseId);
      await loadRadar();
    }
    state.monitorStatus = fingerprint;
    if (!$("#deadline-monitor").classList.contains("hidden")) $("#deadline-monitor").textContent = `Deadline Monitor：${current.monitor.status}${current.monitor.last_checked_at ? ` · 最近检查 ${formatTime(current.monitor.last_checked_at)}` : ""}${current.monitor.escalation_reason ? ` · ${current.monitor.escalation_reason}` : ""}`;
  } catch { /* 后台轮询失败不打断客服输入 */ }
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
$("#prev-case").addEventListener("click", () => moveCase(-1));
$("#next-case").addEventListener("click", () => moveCase(1));
$("#state-prev").addEventListener("click", () => scrollStateTiles(-1));
$("#state-next").addEventListener("click", () => scrollStateTiles(1));
$("#priority-toggle").addEventListener("click", () => {
  const shouldExitPriority = state.priorityMode && state.priorityOpen;
  state.priorityMode = !shouldExitPriority;
  state.priorityOpen = !shouldExitPriority;
  renderQueueControls();
});
$("#priority-refresh").addEventListener("click", async () => {
  await loadRadar();
  state.priorityMode = true;
  state.priorityOpen = true;
  renderQueueControls();
  toast("Priority Queue 已刷新");
});
$("#focus-back").addEventListener("click", () => { state.focusCardKey = null; renderStoryDeck(); });
$$('[data-event]').forEach((button) => button.addEventListener("click", () => shipment(button.dataset.event)));

loadRadar(true).catch((error) => toast(error.message));
setInterval(pollDeadlineMonitor, 5_000);
