import { useEffect, useMemo, useRef, useState } from "react";
import {
  AlertCircle,
  AlertTriangle,
  Bell,
  Check,
  CheckCircle2,
  ChevronDown,
  ChevronLeft,
  ChevronRight,
  ClipboardCheck,
  Clock3,
  Headphones,
  HelpCircle,
  Image as ImageIcon,
  Inbox,
  Loader2,
  Menu,
  MessageCircleMore,
  MoreHorizontal,
  PackageCheck,
  Paperclip,
  RefreshCw,
  Search,
  Send,
  ShieldCheck,
  Smile,
  Sparkles,
  Store,
  Truck,
  UserRoundCheck,
  WandSparkles,
  X,
} from "lucide-react";
import type {
  AccountabilityState,
  ApproveResolutionRequest,
  Decision,
  DecisionResult,
  ExtractedJourney,
  PreparedAction,
  ServiceProgressReceipt,
  ShipmentEventType,
  EvaluateActionRequest,
  FollowUpCandidate,
  SupervisorEscalationCandidate,
  RuntimeMetrics,
} from "./api/contracts";
import { api } from "./api/client";
import { decisionLabels, demoCases, formatClock, type DemoCase } from "./demoData";
import { configureMockMode, type MockMode } from "./mockApi";

type PluginPhase = "overview" | "decision" | "resolution" | "approved";

interface AddedMessage {
  id: string;
  kind: "agent" | "receipt" | "status";
  text?: string;
  receipt?: ServiceProgressReceipt;
  time: string;
}

type StoryCardKey = "story" | "emotion" | "evidence" | "journey" | "promise" | "action";

interface StoryCard {
  key: StoryCardKey;
  eyebrow: string;
  title: string;
  body: string;
  tags: string[];
  focusTitle: string;
  focusPoints: Array<{ label: string; text: string }>;
  knownEvidence?: string[];
  missingEvidence?: string[];
  doNotAsk?: string[];
}

const decisionIcon = {
  INTERVENE: ShieldCheck,
  ALLOW: CheckCircle2,
  HUMAN_REVIEW: UserRoundCheck,
};

function buildEvaluateRequest(
  demoCase: DemoCase,
  preparedAction = demoCase.preparedAction,
): EvaluateActionRequest {
  const base: EvaluateActionRequest = {
    case_id: demoCase.id,
    prepared_action: preparedAction,
    evaluation_time: demoCase.input.evaluation_time,
  };
  if (demoCase.id === "DEMO_002") {
    return {
      ...base,
      challenge_mode: true,
      challenge_overrides: {
        requested_scope: {
          ...preparedAction.requested_scope!,
          fulfillment_item_id: "6920185815517983396-GIFT-B5-MASK-2",
          sku_id: "GIFT-B5-MASK-2",
        },
      },
    };
  }
  if (demoCase.id === "DEMO_003") {
    return {
      ...base,
      challenge_mode: true,
      challenge_overrides: {
        image_observation_overrides: [
          {
            evidence_id: "S00001_BLURRED_IMG",
            readability: "LOW",
            sku_match: "UNKNOWN",
            issue_visible: false,
          },
        ],
      },
    };
  }
  return base;
}

function initialKnownFacts(caseId: string) {
  if (caseId === "DEMO_002") {
    return [
      "当前问题是正装粉底液泵头",
      "已收到的图片属于赠品面膜",
      "订单内同时包含正装与赠品",
    ];
  }
  if (caseId === "DEMO_003") {
    return [
      "消费者描述粉底液泵头失效",
      "已收到一张泵头细节图",
      "图片未对焦，商品与问题不可确认",
    ];
  }
  return [
    "粉底液正装 · XC33003",
    "泵头损坏图片已提交并确认",
    "换货单已创建 · 承诺 48 小时发出",
  ];
}

function prohibitedCopy(caseId: string) {
  if (caseId === "DEMO_002") {
    return "不要把赠品图片当作正装泵头证据";
  }
  if (caseId === "DEMO_003") {
    return "不要基于模糊图片直接判断责任";
  }
  return "不要再次索取相同的破损图片";
}

function useCountdown(target?: string) {
  const [now, setNow] = useState(Date.now());
  useEffect(() => {
    const timer = window.setInterval(() => setNow(Date.now()), 1000);
    return () => window.clearInterval(timer);
  }, []);

  if (!target) return { label: "未设置", overdue: false };
  const difference = new Date(target).getTime() - now;
  const absoluteSeconds = Math.max(0, Math.floor(Math.abs(difference) / 1000));
  const hours = Math.floor(absoluteSeconds / 3600);
  const minutes = Math.floor((absoluteSeconds % 3600) / 60);
  const seconds = absoluteSeconds % 60;
  const label = `${hours.toString().padStart(2, "0")}:${minutes
    .toString()
    .padStart(2, "0")}:${seconds.toString().padStart(2, "0")}`;
  return { label, overdue: difference < 0 };
}

function App() {
  const [selectedId, setSelectedId] = useState("DEMO_001");
  const [accountability, setAccountability] = useState<AccountabilityState | null>(null);
  const [journey, setJourney] = useState<ExtractedJourney | null>(null);
  const [decision, setDecision] = useState<DecisionResult | null>(null);
  const [phase, setPhase] = useState<PluginPhase>("overview");
  const [draft, setDraft] = useState("");
  const [loading, setLoading] = useState(true);
  const [acting, setActing] = useState(false);
  const [detailsOpen, setDetailsOpen] = useState(false);
  const [approvalOpen, setApprovalOpen] = useState(false);
  const [approvalReply, setApprovalReply] = useState("");
  const [extraMessages, setExtraMessages] = useState<AddedMessage[]>([]);
  const [shipmentChoice, setShipmentChoice] = useState<ShipmentEventType | null>(null);
  const [toast, setToast] = useState<string | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [cachedResult, setCachedResult] = useState(false);
  const [runtimeMetrics, setRuntimeMetrics] = useState<RuntimeMetrics | null>(null);
  const [followUpCandidate, setFollowUpCandidate] = useState<FollowUpCandidate | null>(null);
  const [supervisorCandidate, setSupervisorCandidate] = useState<SupervisorEscalationCandidate | null>(null);
  const [mockMode, setMockMode] = useState<MockMode>("normal");
  const [reloadKey, setReloadKey] = useState(0);

  const selectedCase = useMemo(
    () => demoCases.find((item) => item.id === selectedId) ?? demoCases[0],
    [selectedId],
  );

  useEffect(() => {
    let active = true;
    async function loadCase() {
      setLoading(true);
      setLoadError(null);
      setCachedResult(false);
      setRuntimeMetrics(null);
      setFollowUpCandidate(null);
      setSupervisorCandidate(null);
      setAccountability(null);
      setJourney(null);
      setDecision(null);
      setPhase("overview");
      setDetailsOpen(false);
      setExtraMessages([]);
      setShipmentChoice(null);
      setDraft(selectedCase.composerText);

      const result = await api.analyzeCase({
        case_id: selectedCase.id,
        evaluation_time: selectedCase.input.evaluation_time,
        ...(selectedCase.id !== "DEMO_001"
          ? { challenge_mode: true, case_input: selectedCase.input }
          : {}),
      });
      if (!active) return;
      if (result.error) {
        setLoadError(result.error.message);
        setLoading(false);
        return;
      }
      setCachedResult(result.data.model_metadata.cached_result === true);
      setRuntimeMetrics(result.data.runtime_metrics);
      setAccountability(result.data.accountability_state);
      setJourney(result.data.extracted_journey);

      if (selectedCase.id !== "DEMO_001") {
        const evaluated = await api.evaluateAction(buildEvaluateRequest(selectedCase));
        if (!active) return;
        if (evaluated.error) {
          setLoadError(evaluated.error.message);
          setLoading(false);
          return;
        }
        setDecision(evaluated.data);
        setRuntimeMetrics(evaluated.data.runtime_metrics);
        setPhase("decision");
      }
      setLoading(false);
    }
    void loadCase();
    return () => {
      active = false;
    };
  }, [selectedCase, reloadKey]);

  useEffect(() => {
    if (!toast) return;
    const timer = window.setTimeout(() => setToast(null), 2800);
    return () => window.clearTimeout(timer);
  }, [toast]);

  async function evaluateAction(action?: PreparedAction) {
    if (!accountability) return null;
    setActing(true);
    const result = await api.evaluateAction(buildEvaluateRequest(selectedCase, action));
    setActing(false);
    if (result.error) {
      setToast(result.error.message);
      return null;
    }
    setDecision(result.data);
    setRuntimeMetrics(result.data.runtime_metrics);
    return result.data;
  }

  async function handleAttemptSend() {
    if (!draft.trim()) return;
    if (phase === "resolution" && decision) {
      setApprovalReply(draft);
      setApprovalOpen(true);
      return;
    }

    const result = await evaluateAction();
    if (!result) return;
    setPhase("decision");
    if (result.decision === "INTERVENE") {
      setToast("消息已暂停，未发送给消费者");
    } else if (result.decision === "ALLOW") {
      setExtraMessages((items) => [
        ...items,
        { id: `MSG_${Date.now()}`, kind: "agent", text: draft, time: "现在" },
      ]);
      setDraft("");
      setToast("已按当前问题范围发送");
    } else {
      setToast("已转人工复核，消息暂未发送");
    }
  }

  async function handleQueryProgress() {
    const queryAction: PreparedAction = {
      ...selectedCase.preparedAction,
      action_id: `CHECK_${Date.now()}`,
      action_type: "CHECK_REPLACEMENT_PROGRESS",
      requires_human_approval: true,
    };
    // 查询补发进度必须按当前动作重新评估，不能复用上一次“发送消息”的判断。
    const result = await evaluateAction(queryAction);
    if (!result) return;
    setPhase("resolution");
    setApprovalReply(result.resolution_path.consumer_reply_draft);
    setToast("已找到现有换货工单和待处理节点");
  }

  async function handleGenerateReply() {
    const result = decision ?? (await evaluateAction());
    if (!result) return;
    if (result.decision === "ALLOW") {
      setDraft(result.resolution_path.consumer_reply_draft);
      setToast("精准索证回复已放入输入框，可直接发送");
      return;
    }
    if (result.decision === "HUMAN_REVIEW") {
      if (extraMessages.some((message) => message.id.startsWith("REVIEW_"))) {
        setToast("人工复核任务已经提交，请等待复核结果");
        return;
      }
      setExtraMessages((items) => [
        ...items,
        {
          id: `REVIEW_${Date.now()}`,
          kind: "status",
          text: "人工证据复核任务已创建。复核完成前不会要求消费者重复上传。",
          time: "现在",
        },
      ]);
      setDraft(result.resolution_path.consumer_reply_draft);
      setToast("已提交人工复核，安抚回复已准备");
      return;
    }
    setPhase("resolution");
    setDraft(result.resolution_path.consumer_reply_draft);
    setApprovalReply(result.resolution_path.consumer_reply_draft);
    setToast("解决回复已放入输入框，确认后发送");
  }

  function handleSelectCase(caseId: string) {
    // 案例切换后的分析是异步的；先同步清除旧决策，避免旧案例短暂影响新案例的操作路径。
    setSelectedId(caseId);
    setDecision(null);
    setPhase("overview");
    setLoading(true);
    setRuntimeMetrics(null);
  }

  async function handleApprove() {
    if (!decision) return;
    setActing(true);
    const input: ApproveResolutionRequest = {
      case_id: selectedCase.id,
      candidate_type: decision.resolution_path.candidate_type,
      approver_id: "AGENT_ZHOU",
      idempotency_key: `approve-${selectedCase.id}-${crypto.randomUUID()}`,
      human_edits: {
        executor: "WAREHOUSE",
      },
    };
    const result = await api.approveResolution(input);
    setActing(false);
    if (result.error) {
      setToast(result.error.message);
      return;
    }
    setAccountability(result.data.accountability_state);
    setPhase("approved");
    setApprovalOpen(false);
    setDraft("");
    const receipt = result.data.accountability_state.service_progress_receipt;
    setExtraMessages([
      {
        id: `AGENT_${Date.now()}`,
        kind: "agent",
        text: approvalReply,
        time: "现在",
      },
      ...(receipt
        ? [
            {
              id: `RECEIPT_${Date.now()}`,
              kind: "receipt" as const,
              receipt,
              time: "现在",
            },
          ]
        : []),
    ]);
    setToast("解决路径已确认，服务责任开始运行");
  }

  async function handleShipment(eventType: ShipmentEventType) {
    if (!accountability) return;
    setActing(true);
    setShipmentChoice(eventType);
    const result = await api.pushShipmentEvent({
      case_id: selectedCase.id,
      event_id: `EVT_${crypto.randomUUID()}`,
      event_type: eventType,
      event_time:
        eventType === "SHIPMENT_PICKED_UP"
          ? "2026-05-07T10:10:00+08:00"
          : eventType === "SHIPMENT_NOT_PICKED_UP"
            ? "2026-05-07T11:35:00+08:00"
            : "2026-05-08T15:20:00+08:00",
      idempotency_key: `shipment-${selectedCase.id}-${crypto.randomUUID()}`,
    });
    setActing(false);
    if (result.error) {
      setToast(result.error.message);
      return;
    }
    setAccountability(result.data.accountability_state);
    setFollowUpCandidate(result.data.follow_up_candidate);
    setSupervisorCandidate(result.data.supervisor_escalation_candidate);
    const receipt = result.data.accountability_state.service_progress_receipt;
    if (receipt) {
      setExtraMessages((items) => [
        ...items,
        {
          id: `STATUS_${Date.now()}`,
          kind: "status",
          text: result.data.proactive_notification_draft?.text ?? receipt.brand_action,
          receipt,
          time: "现在",
        },
      ]);
    }
    setToast(
      eventType === "SHIPMENT_PICKED_UP"
        ? "物流已揽收，服务责任继续跟踪"
        : eventType === "SHIPMENT_DELIVERED"
          ? "换货件已送达，服务责任已闭环"
          : "责任已升级，催办与主动通知已生成",
    );
  }

  function handleRetry() {
    setReloadKey((value) => value + 1);
  }

  function handleMockModeChange(mode: MockMode) {
    configureMockMode(mode);
    setMockMode(mode);
    setReloadKey((value) => value + 1);
  }

  return (
    <div className="app-shell">
      <TopBar />
      <main className="workbench">
        <ConversationRail
          cases={demoCases}
          selectedId={selectedId}
          onSelect={handleSelectCase}
        />
        <ChatWorkspace
          demoCase={selectedCase}
          draft={draft}
          setDraft={setDraft}
          onSend={handleAttemptSend}
          acting={acting}
          phase={phase}
          addedMessages={extraMessages}
        />
        <CoveniaPlugin
          demoCase={selectedCase}
          selectedId={selectedId}
          onSelectCase={handleSelectCase}
          accountability={accountability}
          journey={journey}
          decision={decision}
          phase={phase}
          loading={loading}
          acting={acting}
          detailsOpen={detailsOpen}
          onToggleDetails={() => setDetailsOpen((value) => !value)}
          onQuery={handleQueryProgress}
          onGenerate={handleGenerateReply}
          onApprove={() => {
            if (decision) {
              setApprovalReply(decision.resolution_path.consumer_reply_draft);
            }
            setApprovalOpen(true);
          }}
          onShipment={handleShipment}
          shipmentChoice={shipmentChoice}
          runtimeMetrics={runtimeMetrics}
          followUpCandidate={followUpCandidate}
          supervisorCandidate={supervisorCandidate}
          loadError={loadError}
          cachedResult={cachedResult}
          mockMode={mockMode}
          onRetry={handleRetry}
          onMockModeChange={handleMockModeChange}
          reviewSubmitted={extraMessages.some((message) => message.id.startsWith("REVIEW_"))}
        />
      </main>
      {approvalOpen && decision ? (
        <ApprovalDialog
          decision={decision}
          reply={approvalReply}
          setReply={setApprovalReply}
          acting={acting}
          onClose={() => setApprovalOpen(false)}
          onConfirm={handleApprove}
        />
      ) : null}
      {toast ? (
        <div className="toast" role="status">
          <CheckCircle2 size={17} />
          {toast}
        </div>
      ) : null}
    </div>
  );
}

function TopBar() {
  return (
    <header className="topbar">
      <div className="brand-mark" aria-label="千牛工作台">
        <span className="qianniu-logo">千</span>
        <span>千牛工作台</span>
        <span className="topbar-divider" />
        <span className="shop-name">测试美妆官方旗舰店</span>
      </div>
      <div className="topbar-actions">
        <span className="online-pill"><span /> 在线接待中</span>
        <button aria-label="通知"><Bell size={17} /></button>
        <button aria-label="帮助"><HelpCircle size={17} /></button>
        <div className="agent-avatar">周</div>
      </div>
    </header>
  );
}

function ConversationRail({
  cases,
  selectedId,
  onSelect,
}: {
  cases: DemoCase[];
  selectedId: string;
  onSelect: (id: string) => void;
}) {
  return (
    <aside className="conversation-rail">
      <div className="rail-nav">
        <button className="rail-icon active" aria-label="接待消息"><MessageCircleMore size={19} /></button>
        <button className="rail-icon" aria-label="工单"><ClipboardCheck size={19} /></button>
        <button className="rail-icon" aria-label="店铺"><Store size={19} /></button>
        <div className="rail-spacer" />
        <button className="rail-icon" aria-label="菜单"><Menu size={19} /></button>
      </div>
      <div className="sessions-panel">
        <div className="sessions-heading">
          <div>
            <span className="section-kicker">接待中心</span>
            <h2>进行中的会话</h2>
          </div>
          <button aria-label="更多"><MoreHorizontal size={19} /></button>
        </div>
        <label className="search-box">
          <Search size={15} />
          <input placeholder="搜索消费者或订单" />
        </label>
        <div className="session-filter">
          <button className="active">全部 <span>3</span></button>
          <button>未回复 <span>1</span></button>
        </div>
        <div className="session-list">
          {cases.map((item, index) => (
            <button
              className={`session-item ${item.id === selectedId ? "selected" : ""}`}
              key={item.id}
              onClick={() => onSelect(item.id)}
            >
              <div className={`customer-avatar avatar-${index + 1}`}>
                {item.title.slice(0, 1)}
                <span className="channel-dot" />
              </div>
              <div className="session-copy">
                <div className="session-line">
                  <strong>{item.title}</strong>
                  <time>{item.time}</time>
                </div>
                <div className="session-preview">
                  <span>{item.preview}</span>
                  {item.unread ? <b>{item.unread}</b> : null}
                </div>
                <div className="case-tag-row">
                  <span>{item.sourceLabel}</span>
                  <i className={`decision-dot decision-${item.expectedDecision.toLowerCase()}`} />
                  <small>{decisionLabels[item.expectedDecision].compact}</small>
                </div>
              </div>
            </button>
          ))}
        </div>
      </div>
    </aside>
  );
}

function ChatWorkspace({
  demoCase,
  draft,
  setDraft,
  onSend,
  acting,
  phase,
  addedMessages,
}: {
  demoCase: DemoCase;
  draft: string;
  setDraft: (value: string) => void;
  onSend: () => void;
  acting: boolean;
  phase: PluginPhase;
  addedMessages: AddedMessage[];
}) {
  const [historyOpen, setHistoryOpen] = useState(false);
  const historicalMessages = demoCase.input.conversation.slice(0, -1);
  const todayMessages = demoCase.input.conversation.slice(-1);
  const historyStart = historicalMessages[0]?.timestamp;
  const historyEnd = historicalMessages[historicalMessages.length - 1]?.timestamp;

  useEffect(() => {
    setHistoryOpen(false);
  }, [demoCase.id]);

  const renderConversationMessage = (message: DemoCase["input"]["conversation"][number], index: number, scope: "history" | "today") => (
    <div
      key={message.message_id}
      className={`message-row ${message.speaker === "AGENT" ? "agent" : "consumer"}`}
    >
      {message.speaker === "CONSUMER" ? (
        <div className="message-avatar">{demoCase.title.slice(0, 1)}</div>
      ) : null}
      <div className="message-stack">
        <div className="message-bubble">{message.text}</div>
        {demoCase.id === "DEMO_001" && scope === "history" && index === 2 ? <EvidenceGallery /> : null}
        {demoCase.id !== "DEMO_001" && scope === "today" && index === 0 ? (
          <EvidenceGallery variant={demoCase.id === "DEMO_002" ? "gift" : "blurred"} />
        ) : null}
        <time>{formatClock(message.timestamp)}</time>
      </div>
      {message.speaker === "AGENT" ? <div className="message-avatar agent-avatar-chat">周</div> : null}
    </div>
  );

  return (
    <section className="chat-workspace">
      <header className="chat-header">
        <div>
          <div className="chat-title-row">
            <h1>{demoCase.title}</h1>
            <span className="buyer-badge">消费者</span>
          </div>
          <p>订单 6920185815517983396 · 天猫</p>
        </div>
        <div className="chat-header-actions">
          <button><Clock3 size={16} /> 服务记录</button>
          <button aria-label="更多"><MoreHorizontal size={19} /></button>
        </div>
      </header>
      <div className="context-strip">
        <div className="product-thumb"><span /></div>
        <div>
          <strong>测试轻透粉底液 30ml</strong>
          <p>#N02 自然色 · SKU XC33003</p>
        </div>
        <div className="context-price">¥329.00</div>
        <button>查看订单 <ChevronRight size={14} /></button>
      </div>
      <div className="messages story-messages" key={demoCase.id}>
        {historicalMessages.length > 0 ? (
          <section className="history-summary-card">
            <div>
              <span>Earlier conversation</span>
              <strong>{historicalMessages.length} 条消息已由 Covenia 总结</strong>
              <p>{historyStart ? formatClock(historyStart) : "此前"}–{historyEnd ? formatClock(historyEnd) : "现在"} · 已完成问题说明 · 已提交图片 · 已创建换货单</p>
            </div>
            <button type="button" onClick={() => setHistoryOpen((value) => !value)} aria-expanded={historyOpen}>
              {historyOpen ? "收起历史" : "展开历史"}
            </button>
          </section>
        ) : null}
        {historyOpen ? (
          <div className="history-thread">
            {historicalMessages.map((message, index) => renderConversationMessage(message, index, "history"))}
          </div>
        ) : null}
        <div className="message-day"><span>Today</span></div>
        {todayMessages.map((message, index) => renderConversationMessage(message, index, "today"))}
        {addedMessages.map((message) => {
          if (message.kind === "receipt" && message.receipt) {
            return <ReceiptMessage key={message.id} receipt={message.receipt} />;
          }
          if (message.kind === "status") {
            return (
              <div className="system-update" key={message.id}>
                <span><Sparkles size={13} /> Covenia 主动更新</span>
                <p>{message.text}</p>
              </div>
            );
          }
          return (
            <div className="message-row agent" key={message.id}>
              <div className="message-stack">
                <div className="message-bubble">{message.text}</div>
                <time>{message.time}</time>
              </div>
              <div className="message-avatar agent-avatar-chat">周</div>
            </div>
          );
        })}
      </div>
      <div className="composer">
        <div className="composer-tools">
          <button aria-label="表情"><Smile size={18} /></button>
          <button aria-label="附件"><Paperclip size={18} /></button>
          <button aria-label="图片"><ImageIcon size={18} /></button>
          <span />
          <button className="smart-copy"><WandSparkles size={14} /> 智能润色</button>
        </div>
        <textarea
          aria-label="客服回复内容"
          value={draft}
          onChange={(event) => setDraft(event.target.value)}
          placeholder="输入回复内容…"
        />
        <div className="composer-footer">
          <span>按 Enter 发送 · Shift + Enter 换行</span>
          <button className="send-button" onClick={onSend} disabled={acting || !draft.trim()}>
            {acting ? <Loader2 size={15} className="spin" /> : <Send size={15} />}
            {phase === "resolution" ? "确认后发送" : "发送"}
          </button>
        </div>
      </div>
    </section>
  );
}

function EvidenceGallery({ variant = "hero" }: { variant?: "hero" | "gift" | "blurred" }) {
  if (variant === "gift") {
    return (
      <div className="evidence-grid single">
        <EvidenceCard fileName="s00001-gift-evidence.jpg" className="gift-evidence" label="赠品外盒" fallbackClass="mask-shape" />
      </div>
    );
  }
  if (variant === "blurred") {
    return (
      <div className="evidence-grid single">
        <EvidenceCard fileName="s00001-blurred-pump.jpg" className="blurred-evidence" label="泵头近照 · 模糊" fallbackClass="bottle-shape" />
      </div>
    );
  }
  return (
    <div className="evidence-grid">
      <EvidenceCard fileName="s00001-product-overview.jpg" className="overview-evidence" label="商品全貌" fallbackClass="bottle-shape" />
      <EvidenceCard fileName="s00001-pump-detail.jpg" className="detail-evidence" label="泵头破损" fallbackClass="pump-shape" />
      <EvidenceCard fileName="s00001-package-context.jpg" className="package-evidence" label="外包装" fallbackClass="box-shape" />
    </div>
  );
}

function EvidenceCard({
  fileName,
  className,
  label,
  fallbackClass,
}: {
  fileName: string;
  className: string;
  label: string;
  fallbackClass: string;
}) {
  const [imageAvailable, setImageAvailable] = useState(true);
  return (
    <div className={`evidence-card ${className}`}>
      {imageAvailable ? (
        <img
          src={`/evidence/${fileName}`}
          alt={label}
          onError={() => setImageAvailable(false)}
        />
      ) : (
        <span className={fallbackClass} />
      )}
      <small>{label}</small>
    </div>
  );
}

function ReceiptMessage({ receipt }: { receipt: ServiceProgressReceipt }) {
  return (
    <div className="receipt-message">
      <div className="receipt-message-head">
        <span><ShieldCheck size={15} /> 服务进度回执</span>
        <small>消费者可见</small>
      </div>
      <p><b>已收到</b> {receipt.received_evidence[0]}，无需再次提交</p>
      <p><b>正在处理</b> {receipt.brand_action}</p>
      <p><b>下次更新</b> {formatClock(receipt.next_update_by)} 前</p>
      <div><Check size={14} /> 消费者当前无需操作</div>
    </div>
  );
}

function buildStoryCards(
  demoCase: DemoCase,
  accountability: AccountabilityState,
  journey: ExtractedJourney | null,
  decision: DecisionResult | null,
): StoryCard[] {
  const commitment = accountability.active_commitments[0];
  const evidenceCount = journey?.image_observations.length ?? demoCase.input.evidence_images.length;
  const knownEvidence = initialKnownFacts(demoCase.id);
  const missingEvidence =
    demoCase.expectedDecision === "INTERVENE"
      ? ["暂无待补充证据。"]
      : demoCase.expectedDecision === "ALLOW"
        ? ["只补当前范围缺失材料：正装粉底液泵头近照。不要重复索要赠品图片。"]
        : ["图片需要人工复核；复核前不要要求消费者立刻重传。"];
  const doNotAsk = [prohibitedCopy(demoCase.id)];
  const decisionText = decision
    ? decisionLabels[decision.decision].title
    : demoCase.expectedDecision === "ALLOW"
      ? "当前范围需要新证据"
      : demoCase.expectedDecision === "HUMAN_REVIEW"
        ? "事实不足，先人工复核"
        : "优先核查换货进度";

  if (demoCase.id === "DEMO_002") {
    return [
      {
        key: "emotion",
        eyebrow: "沟通状态",
        title: "她说明这是另一件商品。",
        body: "赠品和正装需要分开核实。",
        tags: ["商品范围变化"],
        focusTitle: "商品范围",
        focusPoints: [
          { label: "情绪", text: "消费者并非拒绝配合，而是在说明“这是另一件商品”。" },
          { label: "努力", text: "若继续围绕赠品图片处理，会让她重新解释问题。" },
          { label: "边界", text: "只请求当前正装泵头缺失材料。" },
        ],
      },
      {
        key: "evidence",
        eyebrow: "已交材料",
        title: "赠品照片已收到。",
        body: "只补正装泵头照片，不重复索取赠品材料。",
        tags: ["赠品已收到", "正装待补"],
        focusTitle: "证据状态",
        focusPoints: [],
        knownEvidence,
        missingEvidence,
        doNotAsk,
      },
      {
        key: "journey",
        eyebrow: "当前问题",
        title: "转为核实正装泵头。",
        body: "赠品照片不能用于判断正装问题。",
        tags: ["粉底液正装"],
        focusTitle: "服务旅程断点",
        focusPoints: [
          { label: "已知", text: "赠品外盒图片已经收到。" },
          { label: "变化", text: "当前诉求转到正装粉底液泵头。" },
          { label: "下一步", text: decision?.reason ?? "只请求当前范围缺失材料。" },
        ],
      },
      {
        key: "promise",
        eyebrow: "下一步",
        title: "等待补充正装照片。",
        body: "收到后再确认后续处理时间。",
        tags: ["暂未承诺"],
        focusTitle: "承诺状态",
        focusPoints: [
          { label: "状态", text: "还没有可执行服务承诺。" },
          { label: "条件", text: "确认正装泵头问题后才能生成解决路径。" },
          { label: "边界", text: "不能把赠品证据当作正装责任依据。" },
        ],
      },
    ];
  }

  if (demoCase.id === "DEMO_003") {
    return [
      {
        key: "emotion",
        eyebrow: "沟通状态",
        title: "图片看不清。",
        body: "先交人工复核，不要求立即重传。",
        tags: ["等待人工复核"],
        focusTitle: "人工复核",
        focusPoints: [
          { label: "01", text: "图片未对焦，商品与问题不可确认。" },
          { label: "02", text: "不能直接判断责任或关闭问题。" },
          { label: "03", text: "先复核，再决定是否需要补充材料。" },
        ],
      },
      {
        key: "evidence",
        eyebrow: "已交材料",
        title: "图片已收到，暂不能确认。",
        body: "内部复核后再决定是否需要补充。",
        tags: ["需人工确认"],
        focusTitle: "证据状态",
        focusPoints: [],
        knownEvidence,
        missingEvidence,
        doNotAsk,
      },
      {
        key: "journey",
        eyebrow: "当前问题",
        title: "照片清晰度不足。",
        body: "不要直接判定责任或关闭问题。",
        tags: ["需要复核"],
        focusTitle: "服务旅程断点",
        focusPoints: [
          { label: "已知", text: "消费者已提交泵头图片。" },
          { label: "断点", text: "图片清晰度不足，自动判断会放大误判风险。" },
          { label: "处理", text: decision?.reason ?? "先提交人工证据复核。" },
        ],
      },
      {
        key: "promise",
        eyebrow: "下一步",
        title: "先由人工复核。",
        body: "复核后再回复是否需要补充材料。",
        tags: ["不自动索证"],
        focusTitle: "承诺状态",
        focusPoints: [
          { label: "状态", text: "还没有可执行服务承诺。" },
          { label: "条件", text: "人工复核确认责任后，再进入解决路径。" },
          { label: "体验", text: "复核前先安抚，不要求重复上传。" },
        ],
      },
    ];
  }

  return [
    {
      key: "story",
      eyebrow: "案件摘要",
      title: "她已交过照片，正在等换货进度。",
      body: "照片已收到 · 48 小时换货承诺待跟进",
      tags: ["已收到照片", "等待换货"],
      focusTitle: "发生了什么",
      focusPoints: [
        { label: "01", text: "消费者已说明粉底液泵头损坏。" },
        { label: "02", text: `已提交 ${evidenceCount} 张可追踪证据。` },
        { label: "03", text: "客服已承诺换货单 48 小时内发出。" },
      ],
    },
    {
      key: "emotion",
      eyebrow: "沟通状态",
      title: "再次追问换货进度。",
      body: "先回应进度，避免让她重复说明。",
      tags: ["多次沟通"],
      focusTitle: "为什么体验恶化",
      focusPoints: [
        { label: "承诺", text: commitment ? `${commitment.raw_text}，当前状态 ${commitment.status}。` : "已有服务承诺等待确认。" },
        { label: "打扰", text: "重复索证会让消费者感觉历史材料被忽略。" },
        { label: "等待", text: accountability.experience_gap_diagnosis.deterioration_cause },
      ],
    },
    {
      key: "evidence",
      eyebrow: "已交材料",
      title: `照片已收到（${evidenceCount}）`,
      body: "查看已收到的照片和仍缺的材料。",
      tags: [`${evidenceCount} 张照片`],
      focusTitle: "证据状态",
      focusPoints: [],
      knownEvidence,
      missingEvidence,
      doNotAsk,
    },
    {
      key: "journey",
      eyebrow: "服务进度",
      title: "换货进度待确认。",
      body: "已有换货工单，需核查物流状态。",
      tags: ["已有工单"],
      focusTitle: "服务旅程断点",
      focusPoints: [
        { label: "已完成", text: "消费者已经说明问题并提交图片。" },
        { label: "已形成", text: "客服已承诺 48 小时内发出换货。" },
        { label: "当前", text: "消费者再次进线追问是否发出。" },
      ],
    },
    {
      key: "promise",
      eyebrow: "服务承诺",
      title: commitment ? "48 小时内换货承诺" : "尚无有效承诺",
      body: commitment ? `截止 ${formatClock(commitment.deadline)}，由店铺继续跟进。` : "确认责任后再建立服务承诺。",
      tags: [commitment?.status === "ACTIVE" ? "跟进中" : "待确认"],
      focusTitle: "承诺如何运行",
      focusPoints: [
        { label: "来源", text: commitment?.raw_text ?? "来自客服侧承诺与既有换货工单。" },
        { label: "责任", text: "消费者输入已完整，当前应由品牌侧跟进。" },
        { label: "完成", text: "不是建单即完成，必须追踪到换货商品送达。" },
      ],
    },
    {
      key: "action",
      eyebrow: "Next Best Action",
      title: decisionText,
      body: "先核查换货进度，再把可见进展回执给消费者。",
      tags: [decision?.decision ?? "READY", decision?.rule_id ?? "E1", "无需消费者操作"],
      focusTitle: "现在应该做什么",
      focusPoints: [
        { label: "做", text: "查询既有换货工单和物流揽收状态。" },
        { label: "不做", text: prohibitedCopy(demoCase.id) },
        { label: "回复", text: decision?.resolution_path.consumer_reply_draft ?? "告知证据已收到，正在核实换货进度。" },
      ],
    },
  ];
}

function StoryDeck({
  demoCase,
  accountability,
  journey,
  decision,
  phase,
  acting,
  loading,
  onQuery,
  onGenerate,
  onApprove,
  reviewSubmitted,
}: {
  demoCase: DemoCase;
  accountability: AccountabilityState;
  journey: ExtractedJourney | null;
  decision: DecisionResult | null;
  phase: PluginPhase;
  acting: boolean;
  loading: boolean;
  onQuery: () => void;
  onGenerate: () => void;
  onApprove: () => void;
  reviewSubmitted: boolean;
}) {
  const cards = useMemo(
    () => buildStoryCards(demoCase, accountability, journey, decision),
    [demoCase, accountability, journey, decision],
  );
  const [focusKey, setFocusKey] = useState<StoryCardKey | null>(null);
  const sliderRef = useRef<HTMLDivElement | null>(null);
  const entryCards = cards.filter((card) => ["emotion", "evidence", "journey", "promise"].includes(card.key));

  useEffect(() => {
    setFocusKey(null);
  }, [demoCase.id, phase]);

  const focusCard = focusKey ? cards.find((card) => card.key === focusKey) ?? null : null;
  const move = (direction: -1 | 1) => {
    const slider = sliderRef.current;
    const cardWidth = slider?.querySelector(".story-card")?.getBoundingClientRect().width ?? 220;
    slider?.scrollBy({ left: direction * (cardWidth + 10), behavior: "smooth" });
  };

  if (focusCard) {
    return (
      <section className="focus-view">
        <button className="focus-back" onClick={() => setFocusKey(null)} type="button">
          <ChevronLeft size={15} /> 返回 Customer Snapshot
        </button>
        <span className="story-eyebrow">{focusCard.eyebrow}</span>
        <h2>{focusCard.focusTitle}</h2>
        {focusCard.key === "evidence" ? (
          <div className="evidence-focus-grid">
            <section>
              <h3>已知证据</h3>
              {(focusCard.knownEvidence ?? []).map((item) => <p className="evidence-line known" key={item}>✓ {item}</p>)}
            </section>
            <section>
              <h3>待补充证据</h3>
              {(focusCard.missingEvidence ?? []).map((item) => <p className="evidence-line pending" key={item}>● {item}</p>)}
            </section>
            <section className="do-not-ask-chart">
              <h3>❌ 不要再问</h3>
              {(focusCard.doNotAsk ?? []).map((item) => <p className="evidence-line blocked" key={item}>❌ {item}</p>)}
            </section>
          </div>
        ) : (
          <div className="focus-points">
            {focusCard.focusPoints.map((point) => (
              <div key={point.label}>
                <span>{point.label}</span>
                <p>{point.text}</p>
              </div>
            ))}
          </div>
        )}
      </section>
    );
  }

  return (
    <section className="story-deck">
      <div className="story-hero">
        <span>案件摘要</span>
        <h2>{cards[0].title}</h2>
        <p>{cards[0].body}</p>
        <div>
          {cards[0].tags.map((tag) => <small key={tag}>{tag}</small>)}
        </div>
      </div>

      <div className="card-carousel" aria-label="Customer state cards">
        <button className="carousel-nav" onClick={() => move(-1)} type="button" aria-label="上一张">
          <ChevronLeft size={18} />
        </button>
        <div className="story-card-strip" ref={sliderRef}>
          {entryCards.map((card) => (
            <button className={`story-card card-${card.key}`} key={card.key} onClick={() => setFocusKey(card.key)} type="button">
              <span>{card.eyebrow}</span>
              <strong>{card.title}</strong>
              <p>{card.body}</p>
              <em aria-label="查看详情"><ChevronRight size={13} /></em>
            </button>
          ))}
        </div>
        <button className="carousel-nav" onClick={() => move(1)} type="button" aria-label="下一张">
          <ChevronRight size={18} />
        </button>
      </div>

      <StoryActionPanel
        demoCase={demoCase}
        decision={decision}
        phase={phase}
        acting={acting}
        loading={loading}
        onQuery={onQuery}
        onGenerate={onGenerate}
        onApprove={onApprove}
        reviewSubmitted={reviewSubmitted}
      />
    </section>
  );
}

function StoryActionPanel({
  demoCase,
  decision,
  phase,
  acting,
  loading,
  onQuery,
  onGenerate,
  onApprove,
  reviewSubmitted,
}: {
  demoCase: DemoCase;
  decision: DecisionResult | null;
  phase: PluginPhase;
  acting: boolean;
  loading: boolean;
  onQuery: () => void;
  onGenerate: () => void;
  onApprove: () => void;
  reviewSubmitted: boolean;
}) {
  const decisionType = decision?.decision;
  return (
    <section className="story-action-panel">
      <span>建议下一步</span>
      <h3>{decision ? decisionLabels[decision.decision].title : "优先核查换货进度"}</h3>
      <p>{decision?.reason ?? "消费者已经交过材料，此刻应该先查进度，而不是重复索证。"}</p>
      {phase === "resolution" ? (
        <button className="primary-action" onClick={onApprove} disabled={acting || loading}>
          <ClipboardCheck size={16} /> 人工确认解决路径 <ChevronRight size={16} />
        </button>
      ) : decisionType === "ALLOW" ? (
        <button className="primary-action allow-action" onClick={onGenerate} disabled={acting}>
          生成精准索证回复 <ChevronRight size={16} />
        </button>
      ) : decisionType === "HUMAN_REVIEW" ? (
        <button className="primary-action review-action" onClick={onGenerate} disabled={acting || reviewSubmitted}>
          {reviewSubmitted ? "人工复核已提交" : "提交人工证据复核"} <UserRoundCheck size={16} />
        </button>
      ) : (
        <div className="action-stack">
          <button className="primary-action" onClick={onQuery} disabled={acting}>
            {acting ? <Loader2 size={16} className="spin" /> : <Search size={16} />}
            查询补发进度 <ChevronRight size={16} />
          </button>
          <button className="secondary-action" onClick={onGenerate} disabled={acting}>
            <WandSparkles size={15} /> 生成解决回复
          </button>
        </div>
      )}
      <small>{prohibitedCopy(demoCase.id)}</small>
    </section>
  );
}

function priorityScore(caseItem: DemoCase) {
  const base = caseItem.expectedDecision === "INTERVENE" ? 110 : caseItem.expectedDecision === "HUMAN_REVIEW" ? 86 : 72;
  const contactBoost = Math.min(caseItem.input.conversation.length * 4, 18);
  const evidenceBoost = Math.min(caseItem.input.evidence_images.length * 5, 15);
  const ticketBoost = caseItem.input.service_tickets.length ? 8 : 0;
  return base + contactBoost + evidenceBoost + ticketBoost;
}

function priorityBand(caseItem: DemoCase) {
  const score = priorityScore(caseItem);
  if (score >= 120) return "red";
  if (score >= 95) return "orange";
  return "yellow";
}

function priorityReasons(caseItem: DemoCase) {
  if (caseItem.expectedDecision === "INTERVENE") return ["承诺待兑现", "重复索证风险", "已有工单未闭环"];
  if (caseItem.expectedDecision === "HUMAN_REVIEW") return ["证据不确定", "需人工复核", "避免误判"];
  return ["问题范围变化", "只补当前缺口", "避免重复材料"];
}

function PriorityQueue({
  selectedId,
  onSelectCase,
}: {
  selectedId: string;
  onSelectCase: (caseId: string) => void;
}) {
  const [open, setOpen] = useState(false);
  const ordered = useMemo(() => [...demoCases].sort((a, b) => priorityScore(b) - priorityScore(a)), []);
  const currentIndex = Math.max(0, ordered.findIndex((item) => item.id === selectedId));
  const current = ordered[currentIndex] ?? ordered[0];
  const move = (direction: -1 | 1) => {
    const nextIndex = (currentIndex + direction + ordered.length) % ordered.length;
    onSelectCase(ordered[nextIndex].id);
  };

  return (
    <section className="priority-queue-card">
      <div className="priority-queue-top">
        <button type="button" onClick={() => move(-1)} aria-label="上一位消费者"><ChevronLeft size={15} /></button>
        <div>
          <span>优先处理 · {currentIndex + 1}/{ordered.length}</span>
          <strong>{current?.title ?? "—"}</strong>
        </div>
        <button type="button" onClick={() => move(1)} aria-label="下一位消费者"><ChevronRight size={15} /></button>
        <button className="priority-toggle-button" type="button" onClick={() => setOpen((value) => !value)} aria-expanded={open}>
          待处理案件 <small>{ordered.length} 位消费者</small>
        </button>
      </div>
      {open ? (
        <div className="priority-list-panel">
          <div className="priority-list-head">
            <span>待处理案件</span>
            <small>按紧急程度排序</small>
          </div>
          {ordered.map((item, index) => (
            <button
              type="button"
              className={`priority-list-item ${priorityBand(item)} ${item.id === selectedId ? "selected" : ""}`}
              key={item.id}
              onClick={() => onSelectCase(item.id)}
            >
              <b>{index + 1}</b>
              <strong>{item.title}</strong>
              <small>主要原因：{priorityReasons(item).slice(0, 2).join("、")}</small>
            </button>
          ))}
        </div>
      ) : null}
    </section>
  );
}

function fusionRows(demoCase: DemoCase, journey: ExtractedJourney | null) {
  return [
    {
      label: "Conversation",
      count: demoCase.input.conversation.length,
      ids: demoCase.input.conversation.map((item) => item.message_id),
    },
    {
      label: "Image",
      count: journey?.image_observations.length ?? demoCase.input.evidence_images.length,
      ids: (journey?.image_observations ?? []).map((item) => item.evidence_id)
        .concat(journey ? [] : demoCase.input.evidence_images.map((item) => item.evidence_id)),
    },
    {
      label: "Order",
      count: 1,
      ids: [demoCase.input.order.order_id],
    },
    {
      label: "Ticket",
      count: demoCase.input.service_tickets.length,
      ids: demoCase.input.service_tickets.map((item) => item.ticket_id),
    },
  ];
}

function timelineRows(demoCase: DemoCase, accountability: AccountabilityState) {
  const firstMessage = demoCase.input.conversation[0];
  const firstEvidence = demoCase.input.evidence_images[0];
  const firstTicket = demoCase.input.service_tickets[0];
  const commitment = accountability.active_commitments[0];
  return [
    {
      time: firstMessage ? formatClock(firstMessage.timestamp) : "—",
      source: "CONVERSATION",
      title: "消费者说明当前诉求",
      detail: firstMessage?.message_id ?? "暂无消息 ID",
    },
    {
      time: firstEvidence ? formatClock(firstEvidence.submitted_at) : "—",
      source: "IMAGE",
      title: "证据进入可追踪状态",
      detail: firstEvidence?.evidence_id ?? "暂无图片证据",
    },
    {
      time: firstTicket ? formatClock(firstTicket.created_at) : "派生",
      source: "TICKET",
      title: firstTicket ? "已有服务工单" : "当前无已建工单",
      detail: firstTicket?.ticket_id ?? "仅使用当前案例上下文",
    },
    {
      time: commitment ? formatClock(commitment.deadline) : "待定",
      source: "PROMISE",
      title: commitment ? "承诺进入责任账本" : "尚未形成可执行承诺",
      detail: commitment?.raw_text ?? "需先完成人工确认或证据复核",
    },
  ];
}

function riskFactors(demoCase: DemoCase, accountability: AccountabilityState) {
  const score = priorityScore(demoCase);
  const factors = [
    {
      label: "Experience Risk",
      value: accountability.experience_risk,
      weight: accountability.experience_risk === "HIGH" ? "+40" : "+20",
      evidence: accountability.experience_gap_diagnosis.deterioration_cause,
    },
    {
      label: "Consumer Effort",
      value: `${demoCase.input.conversation.length} contacts`,
      weight: `+${Math.min(demoCase.input.conversation.length * 4, 18)}`,
      evidence: accountability.experience_gap_diagnosis.latent_need,
    },
    {
      label: "Promise",
      value: accountability.active_commitments[0]?.status ?? "NONE",
      weight: accountability.active_commitments.length ? "+8" : "+0",
      evidence: accountability.active_commitments[0]?.raw_text ?? "当前没有可执行服务承诺",
    },
  ];
  return { score, factors };
}

function V11Workspace({
  demoCase,
  selectedId,
  onSelectCase,
  accountability,
  journey,
  decision,
  phase,
}: {
  demoCase: DemoCase;
  selectedId: string;
  onSelectCase: (caseId: string) => void;
  accountability: AccountabilityState;
  journey: ExtractedJourney | null;
  decision: DecisionResult | null;
  phase: PluginPhase;
}) {
  const fusion = fusionRows(demoCase, journey);
  const timeline = timelineRows(demoCase, accountability);
  const { score, factors } = riskFactors(demoCase, accountability);
  const effortScore = Math.min(100, 38 + demoCase.input.conversation.length * 9 + demoCase.input.evidence_images.length * 7);
  const hasCompleteFusion = fusion.every((item) => item.count > 0);
  const orderedCases = useMemo(() => [...demoCases].sort((a, b) => priorityScore(b) - priorityScore(a)), []);
  const commitment = accountability.active_commitments[0];
  const deadlineStatus =
    phase === "approved"
      ? accountability.case_status === "AT_RISK"
        ? "AT_RISK"
        : accountability.case_status === "RESOLVED"
          ? "CLOSED"
          : "SCHEDULED"
      : commitment
        ? "READY_AFTER_APPROVAL"
        : "NO_ACTIVE_PROMISE";
  const emergingSignals = demoCases.filter((item) => item.input.current_issue.issue_type === demoCase.input.current_issue.issue_type).length;
  const coreItems = [
    { label: "Experience Ledger", value: accountability.case_status },
    { label: "Evidence", value: accountability.evidence_status },
    { label: "Promise", value: commitment?.status ?? "NONE" },
    { label: "Firewall", value: decision?.decision ?? "READY" },
    { label: "Resolution", value: phase === "approved" ? "RUNNING" : "DRAFT" },
  ];
  const extensionItems = [
    {
      id: "Intent",
      title: "Current Intent",
      status: journey?.journey_understanding.cooperation_willingness ?? "UNKNOWN",
      text: journey?.journey_understanding.consumer_intent ?? accountability.experience_gap_diagnosis.consumer_expression,
    },
    {
      id: "Emotion",
      title: "Emotion / Trend",
      status: journey?.journey_understanding.cooperation_willingness ?? "UNKNOWN",
      text: journey?.journey_understanding.experience_expression ?? "等待抽取情绪表达与原因。",
    },
    {
      id: "Effort",
      title: "Consumer Effort",
      status: `${effortScore}/100`,
      text: accountability.experience_gap_diagnosis.latent_need,
    },
    {
      id: "Risk",
      title: "Risk State",
      status: `${score}`,
      text: "单个消费者服务风险；不把情绪推断写入风险分。",
    },
    {
      id: "Decision",
      title: "Decision",
      status: decision?.decision ?? "READY",
      text: decision?.reason ?? "先评估动作，避免把责任倒流给消费者。",
    },
    {
      id: "Deadline",
      title: "Deadline State",
      status: deadlineStatus,
      text: commitment ? `${commitment.raw_text} · ${formatClock(commitment.deadline)} 前` : "暂无可监控承诺。",
    },
  ];

  return (
    <section className="v11-workspace" aria-label="V1.1 新版工作区">
      <div className="v11-workspace-head">
        <div>
          <span>V1.1 Workspace</span>
          <h2>连续服务新版工作区</h2>
          <p>BC Core 不破坏；新增能力按 Customer Extension、Operational State、Model Governance 分层展示。</p>
        </div>
        <b>新版区</b>
      </div>

      <div className="v11-layer-label">BC Core · 不破坏</div>
      <div className="v11-core-strip">
        {coreItems.map((item) => (
          <div key={item.label}>
            <span>{item.label}</span>
            <b>{item.value}</b>
          </div>
        ))}
      </div>

      <div className="v11-layer-label">Customer Extension · 新增</div>
      <div className="v11-capability-grid">
        {extensionItems.map((item) => (
          <article className="v11-capability-card" key={item.id}>
            <div><span>{item.id}</span><b>{item.status}</b></div>
            <strong>{item.title}</strong>
            <p>{item.text}</p>
          </article>
        ))}
      </div>

      <section className="v11-fusion-card">
        <div className="v11-card-title">
          <span>Multi-source Fusion</span>
          <small>{hasCompleteFusion ? "COMPLETE · 100%" : "PARTIAL · 待补齐"}</small>
        </div>
        <div className="fusion-source-grid">
          {fusion.map((item) => (
            <div key={item.label} title={item.ids.join(" / ") || "暂无来源 ID"}>
              <b>{item.count}</b>
              <span>{item.label}</span>
            </div>
          ))}
        </div>
        <p className="fusion-link-line">Conversation → Order → Image → Ticket 均保留来源 ID；冲突时先进入人工复核。</p>
      </section>

      <section className="v11-two-column">
        <div className="v11-card">
          <div className="v11-card-title"><span>Journey Timeline</span><small>来源可追溯</small></div>
          <div className="v11-timeline">
            {timeline.map((item) => (
              <div key={`${item.source}-${item.title}`}>
                <b>{item.time}</b>
                <span>{item.source}</span>
                <p>{item.title}<small>{item.detail}</small></p>
              </div>
            ))}
          </div>
        </div>
        <div className="v11-card">
          <div className="v11-card-title"><span>Handoff Package</span><small>人工可接手</small></div>
          <ul className="handoff-list">
            <li>当前诉求：{journey?.journey_understanding.consumer_intent ?? "等待恢复"}</li>
            <li>已知事实：{initialKnownFacts(demoCase.id).slice(0, 2).join("；")}</li>
            <li>不要再问：{prohibitedCopy(demoCase.id)}</li>
            <li>建议动作：{decision?.resolution_path.task_prefill.summary ?? "先查询既有责任状态"}</li>
          </ul>
        </div>
      </section>

      <div className="v11-layer-label">Aggregate / Operational State · 独立</div>
      <section className="v11-risk-card">
        <div className="v11-card-title">
          <span>Risk Radar</span>
          <small>运营分流 · 非预测</small>
        </div>
        <div className="risk-score-row">
          <b>{score}</b>
          <div>
            {factors.map((factor) => (
              <p key={factor.label}><span>{factor.weight}</span>{factor.label} · {factor.value}</p>
            ))}
          </div>
        </div>
        <div className="risk-list-mini">
          {orderedCases.map((item, index) => (
            <button
              type="button"
              key={item.id}
              className={item.id === selectedId ? "selected" : ""}
              onClick={() => onSelectCase(item.id)}
            >
              <b>{index + 1}</b>
              <span>{item.title}</span>
              <small>{priorityScore(item)}</small>
            </button>
          ))}
        </div>
        <p className="risk-footnote">情绪只用于沟通语气；分数来自等待、承诺、重复沟通和工单状态。</p>
      </section>

      <section className="v11-monitor-row">
        <div>
          <span>Priority Queue</span>
          <strong>{orderedCases.findIndex((item) => item.id === selectedId) + 1}/{orderedCases.length}</strong>
          <p>按 Risk、Deadline、等待和人工复核需求排序；只决定先处理谁。</p>
        </div>
        <div>
          <span>Emerging Issue</span>
          <strong>{emergingSignals >= 3 ? "CANDIDATE" : "WATCHING"}</strong>
          <p>{emergingSignals} 个同类案例信号；固定标注为测试数据，不做质量结论。</p>
        </div>
      </section>

      <div className="v11-layer-label">Model Governance · 独立</div>
      <section className="v11-governance-row">
        <div><span>JEV Decision</span><b>Typed choices only</b></div>
        <div><span>Confidence</span><b>解释，不直接动作</b></div>
        <div><span>Threshold</span><b>低于阈值回退</b></div>
        <div><span>Fallback / Audit</span><b>Human Review + log</b></div>
      </section>
    </section>
  );
}

function CoveniaPlugin({
  demoCase,
  selectedId,
  onSelectCase,
  accountability,
  journey,
  decision,
  phase,
  loading,
  acting,
  detailsOpen,
  onToggleDetails,
  onQuery,
  onGenerate,
  onApprove,
  onShipment,
  shipmentChoice,
  runtimeMetrics,
  followUpCandidate,
  supervisorCandidate,
  loadError,
  cachedResult,
  mockMode,
  onRetry,
  onMockModeChange,
  reviewSubmitted,
}: {
  demoCase: DemoCase;
  selectedId: string;
  onSelectCase: (caseId: string) => void;
  accountability: AccountabilityState | null;
  journey: ExtractedJourney | null;
  decision: DecisionResult | null;
  phase: PluginPhase;
  loading: boolean;
  acting: boolean;
  detailsOpen: boolean;
  onToggleDetails: () => void;
  onQuery: () => void;
  onGenerate: () => void;
  onApprove: () => void;
  onShipment: (event: ShipmentEventType) => void;
  shipmentChoice: ShipmentEventType | null;
  runtimeMetrics: RuntimeMetrics | null;
  followUpCandidate: FollowUpCandidate | null;
  supervisorCandidate: SupervisorEscalationCandidate | null;
  loadError: string | null;
  cachedResult: boolean;
  mockMode: MockMode;
  onRetry: () => void;
  onMockModeChange: (mode: MockMode) => void;
  reviewSubmitted: boolean;
}) {
  const decisionType = decision?.decision;
  if (loadError) {
    return (
      <aside className="plugin-panel">
        <PluginHeader mockMode={mockMode} onMockModeChange={onMockModeChange} />
        <div className="plugin-error">
          <div className="error-symbol"><AlertCircle size={22} /></div>
          <span>分析暂时没有完成</span>
          <h2>案例内容和客服草稿已保留</h2>
          <p>{loadError}</p>
          <button onClick={onRetry}><RefreshCw size={15} /> 重新分析</button>
          <small>可在右上角演示设置中恢复正常模式</small>
        </div>
      </aside>
    );
  }
  if (loading || !accountability) {
    return (
      <aside className="plugin-panel">
        <PluginHeader mockMode={mockMode} onMockModeChange={onMockModeChange} />
        <div className="plugin-loading">
          <div className="loading-orbit"><Sparkles size={20} /></div>
          <strong>正在恢复这次服务旅程</strong>
          <p>核对聊天、订单、图片和已有工单…</p>
          <div className="loading-lines"><span /><span /><span /></div>
        </div>
      </aside>
    );
  }

  return (
    <aside className="plugin-panel">
      <PluginHeader mockMode={mockMode} onMockModeChange={onMockModeChange} />
      <div className="plugin-scroll">
        {decision?.challenge_mode ? (
          <div className="challenge-notice">挑战案例</div>
        ) : null}
        {phase === "approved" && accountability.service_progress_receipt ? (
          <ProgressView
            accountability={accountability}
            acting={acting}
            onShipment={onShipment}
            shipmentChoice={shipmentChoice}
            runtimeMetrics={runtimeMetrics}
            followUpCandidate={followUpCandidate}
            supervisorCandidate={supervisorCandidate}
          />
        ) : (
          <>
            {cachedResult ? (
              <div className="cached-notice"><RefreshCw size={13} /> 当前使用缓存抽取结果，后续规则仍实时运行</div>
            ) : null}
            <PriorityQueue selectedId={selectedId} onSelectCase={onSelectCase} />
            <StoryDeck
              demoCase={demoCase}
              accountability={accountability}
              journey={journey}
              decision={decision}
              phase={phase}
              acting={acting}
              loading={loading}
              onQuery={onQuery}
              onGenerate={onGenerate}
              onApprove={onApprove}
              reviewSubmitted={reviewSubmitted}
            />

            <button className="details-toggle" onClick={onToggleDetails} aria-expanded={detailsOpen}>
              <span><Inbox size={15} /> 更多案件信息</span>
              <ChevronDown size={16} className={detailsOpen ? "rotated" : ""} />
            </button>
            {detailsOpen ? (
              <>
                {decision ? <DecisionBanner decision={decision} /> : null}
                <DiagnosisDetails accountability={accountability} journey={journey} />
                <V11Workspace
                  demoCase={demoCase}
                  selectedId={selectedId}
                  onSelectCase={onSelectCase}
                  accountability={accountability}
                  journey={journey}
                  decision={decision}
                  phase={phase}
                />
                {runtimeMetrics ? <RuntimeCostBar metrics={runtimeMetrics} /> : null}
              </>
            ) : null}
          </>
        )}
      </div>
    </aside>
  );
}

function PluginHeader({
  mockMode,
  onMockModeChange,
}: {
  mockMode: MockMode;
  onMockModeChange: (mode: MockMode) => void;
}) {
  const [open, setOpen] = useState(false);
  const modeOptions: Array<{ value: MockMode; label: string; note: string }> = [
    { value: "normal", label: "正常响应", note: "标准演示" },
    { value: "slow", label: "慢响应", note: "观察加载状态" },
    { value: "cached", label: "缓存结果", note: "模型灾备" },
    { value: "model_timeout", label: "模型超时", note: "观察可重试错误" },
    { value: "state_conflict", label: "状态冲突", note: "关键动作报错" },
  ];
  return (
    <header className="plugin-header">
      <div className="covenia-symbol"><span>C</span></div>
      <div>
        <strong>Covenia</strong>
        <small>体验责任副驾</small>
      </div>
      <span className="simulation-badge">
        {import.meta.env.VITE_API_MODE === "http" ? "本地服务" : "模拟演示"}
      </span>
      {import.meta.env.VITE_API_MODE !== "http" ? (
        <button aria-label="插件设置" onClick={() => setOpen((value) => !value)}><MoreHorizontal size={18} /></button>
      ) : null}
      {open && import.meta.env.VITE_API_MODE !== "http" ? (
        <div className="demo-settings">
          <div><span>接口状态演示</span><small>仅影响本地 Mock</small></div>
          {modeOptions.map((option) => (
            <button
              key={option.value}
              className={mockMode === option.value ? "active" : ""}
              onClick={() => {
                onMockModeChange(option.value);
                setOpen(false);
              }}
            >
              <span>{option.label}<small>{option.note}</small></span>
              {mockMode === option.value ? <Check size={14} /> : null}
            </button>
          ))}
        </div>
      ) : null}
    </header>
  );
}

function DecisionBanner({ decision }: { decision: DecisionResult }) {
  const Icon = decisionIcon[decision.decision];
  const copy = decisionLabels[decision.decision];
  return (
    <div className={`decision-banner state-${decision.decision.toLowerCase()}`}>
      <div className="decision-icon"><Icon size={19} /></div>
      <div>
        <span>{copy.eyebrow} · {decision.decision}</span>
        <strong>{copy.title}</strong>
        <p>{decision.reason}</p>
      </div>
    </div>
  );
}

function ResolutionPreview({ decision, onApprove }: { decision: DecisionResult; onApprove: () => void }) {
  return (
    <section className="resolution-preview">
      <div className="resolution-head">
        <span><Sparkles size={15} /> 解决路径已准备</span>
        <small>需要人工确认</small>
      </div>
      <div className="route-line">
        <span className="route-node done"><Check size={12} /></span>
        <div><b>沿用已有换货单</b><small>{decision.resolution_path.task_prefill.existing_ticket_id}</small></div>
      </div>
      <div className="route-line">
        <span className="route-node"><PackageCheck size={12} /></span>
        <div><b>查询仓库与揽收状态</b><small>已有物流单号，不重复建单</small></div>
      </div>
      <div className="route-line">
        <span className="route-node"><MessageCircleMore size={12} /></span>
        <div><b>主动回复消费者</b><small>明确下次更新时间</small></div>
      </div>
      <button className="approve-inline" onClick={onApprove}>查看并确认 <ChevronRight size={15} /></button>
    </section>
  );
}

function DiagnosisDetails({ accountability, journey }: { accountability: AccountabilityState; journey: ExtractedJourney | null }) {
  return (
    <div className="diagnosis-details">
      <div><span>体验断层</span><p>{accountability.experience_gap_diagnosis.deterioration_cause}</p></div>
      <div><span>潜在需要</span><p>{accountability.experience_gap_diagnosis.latent_need}</p></div>
      <div><span>责任判断</span><p>{accountability.accountable_side === "BRAND" ? "消费者输入已完整，当前由品牌负责" : accountability.accountable_side === "CONSUMER" ? "当前范围仍需消费者补充输入" : "事实不足，等待人工确认"}</p></div>
      <div className="fact-chips">
        <span>证据 {accountability.evidence_status}</span>
        <span>{journey?.image_observations.length ?? 0} 张图片</span>
        <span>{accountability.active_commitments.length} 条承诺</span>
      </div>
    </div>
  );
}

function AccountabilitySummary({ accountability }: { accountability: AccountabilityState }) {
  const commitment = accountability.active_commitments[0];
  return (
    <section className="accountability-summary">
      <div><span>案件状态</span><b>{accountability.case_status}</b></div>
      {commitment ? <>
        <div><span>承诺原文</span><b>{commitment.raw_text}</b></div>
        <div><span>当前义务</span><b>{commitment.status} · {formatClock(commitment.deadline)} 前</b></div>
        <div><span>执行方</span><b>{accountability.open_obligation?.executor ?? "待人工确认"}</b></div>
      </> : <div><span>当前义务</span><b>尚未激活</b></div>}
    </section>
  );
}

function RuntimeCostBar({ metrics }: { metrics: RuntimeMetrics }) {
  return <section className="runtime-cost-bar" aria-label="本次运行成本">
    <span>本次运行</span><b>{metrics.input_tokens + metrics.output_tokens} tokens</b>
    <b>{metrics.inference_latency_ms} ms</b><b>规则替代 {metrics.rule_substitution_count}</b>
  </section>;
}

function ProgressView({
  accountability,
  acting,
  onShipment,
  shipmentChoice,
  runtimeMetrics,
  followUpCandidate,
  supervisorCandidate,
}: {
  accountability: AccountabilityState;
  acting: boolean;
  onShipment: (event: ShipmentEventType) => void;
  shipmentChoice: ShipmentEventType | null;
  runtimeMetrics: RuntimeMetrics | null;
  followUpCandidate: FollowUpCandidate | null;
  supervisorCandidate: SupervisorEscalationCandidate | null;
}) {
  const receipt = accountability.service_progress_receipt!;
  const pickedUp = accountability.open_obligation?.milestone === "IN_TRANSIT";
  const delivered = accountability.open_obligation?.milestone === "DELIVERED";
  const atRisk = accountability.case_status === "AT_RISK";
  const countdown = useCountdown(accountability.open_obligation?.deadline);
  return (
    <div className="progress-view">
      <div className={`progress-hero ${pickedUp || delivered ? "on-track" : atRisk ? "at-risk" : ""}`}>
        <div className="progress-hero-top">
          <span className="progress-icon">{delivered ? <PackageCheck size={20} /> : pickedUp ? <Truck size={20} /> : <Clock3 size={20} />}</span>
          <div>
            <small>{delivered ? "服务责任已完成" : "服务责任正在运行"}</small>
            <h2>{delivered ? "换货件已送达" : pickedUp ? "换货件已揽收" : atRisk ? "承诺节点需要补救" : "等待物流揽收"}</h2>
          </div>
          <span className="status-word">{delivered ? "已闭环" : pickedUp ? "正常" : atRisk ? "有风险" : "进行中"}</span>
        </div>
        <p>{receipt.brand_action}</p>
        {!pickedUp && !delivered ? (
          <div className={`countdown-strip ${countdown.overdue ? "overdue" : ""}`}>
            <span>{countdown.overdue ? "承诺已超时" : "距承诺节点"}</span>
            <b>{countdown.label}</b>
            <small>{countdown.overdue ? "补救计时中" : "系统持续检查"}</small>
          </div>
        ) : null}
        <div className="responsibility-line"><span /> <b>{delivered ? "换货送达已核验，责任闭环" : "品牌继续负责，直至换货商品送达"}</b></div>
      </div>

      <section className="receipt-card">
        <div className="receipt-card-title"><span><ShieldCheck size={16} /> 服务进度回执</span><small>已同步至聊天</small></div>
        <dl>
          <div><dt>已收到</dt><dd>{receipt.received_evidence[0]}，无需再次提交</dd></div>
          <div><dt>正在处理</dt><dd>{receipt.brand_action}</dd></div>
          <div><dt>下次更新</dt><dd>{formatClock(receipt.next_update_by)} 前</dd></div>
          <div><dt>未完成时</dt><dd>{receipt.recovery_if_missed}</dd></div>
        </dl>
        <div className="no-action"><CheckCircle2 size={16} /> 消费者当前无需操作</div>
      </section>

      <section className="timeline-card">
        <div className="timeline-title"><span>责任进度</span><small>{delivered ? "已完成" : pickedUp ? "运输中" : "等待揽收"}</small></div>
        <div className="mini-timeline">
          <div className="complete"><span><Check size={11} /></span><small>工单创建</small></div>
          <i />
          <div className={pickedUp ? "complete" : atRisk ? "risk" : "current"}><span>{pickedUp ? <Check size={11} /> : "2"}</span><small>物流揽收</small></div>
          <i />
          <div className={delivered ? "complete" : ""}><span>{delivered ? <Check size={11} /> : "3"}</span><small>商品送达</small></div>
        </div>
        <p><AlertCircle size={14} /> 工单创建和物流单号生成都不等于问题已解决</p>
      </section>

      <section className="shipment-simulator">
        <div className="simulator-title">
          <div><span>演示物流事件</span><small>按钮调用 /api/events/shipment</small></div>
          <RefreshCw size={15} className={acting ? "spin" : ""} />
        </div>
        <div className="shipment-buttons">
          <button
            className={shipmentChoice === "SHIPMENT_PICKED_UP" ? "selected" : ""}
            onClick={() => onShipment("SHIPMENT_PICKED_UP")}
            disabled={acting}
          ><Truck size={16} /><span><b>已揽收</b><small>保持正常，不催办</small></span></button>
          <button
            className={shipmentChoice === "SHIPMENT_NOT_PICKED_UP" ? "selected risk-choice" : ""}
            onClick={() => onShipment("SHIPMENT_NOT_PICKED_UP")}
            disabled={acting}
          ><AlertTriangle size={16} /><span><b>仍未揽收</b><small>升级风险并催办</small></span></button>
          <button
            className={shipmentChoice === "SHIPMENT_DELIVERED" ? "selected" : ""}
            onClick={() => onShipment("SHIPMENT_DELIVERED")}
            disabled={acting || !pickedUp}
          ><PackageCheck size={16} /><span><b>已送达</b><small>揽收后可闭环</small></span></button>
        </div>
      </section>
      <section className="supervisor-zone">
        <div className="timeline-title"><span>主管跟踪区</span><small>服务端候选</small></div>
        {followUpCandidate ? <p>催办：{followUpCandidate.summary}</p> : <p>当前没有仓库催办候选</p>}
        {supervisorCandidate ? <p>升级：{supervisorCandidate.summary}</p> : <p>当前没有主管升级候选</p>}
      </section>
      {runtimeMetrics ? <RuntimeCostBar metrics={runtimeMetrics} /> : null}
    </div>
  );
}

function ApprovalDialog({
  decision,
  reply,
  setReply,
  acting,
  onClose,
  onConfirm,
}: {
  decision: DecisionResult;
  reply: string;
  setReply: (value: string) => void;
  acting: boolean;
  onClose: () => void;
  onConfirm: () => void;
}) {
  return (
    <div className="modal-backdrop" role="presentation">
      <div className="approval-dialog" role="dialog" aria-modal="true" aria-labelledby="approval-title">
        <header>
          <div className="dialog-icon"><ClipboardCheck size={20} /></div>
          <div><span>人工确认</span><h2 id="approval-title">让这条服务承诺开始运行</h2></div>
          <button onClick={onClose} aria-label="关闭"><X size={19} /></button>
        </header>
        <div className="approval-grid">
          <label><span>责任方</span><div className="fixed-input"><ShieldCheck size={15} /> 品牌</div></label>
          <label><span>执行方</span><select defaultValue="WAREHOUSE"><option value="WAREHOUSE">测试美妆分销中心</option><option value="BRAND">品牌客服</option></select></label>
          <label><span>承诺截止</span><div className="fixed-input"><Clock3 size={15} /> 5月7日 10:27</div></label>
          <label><span>完成条件</span><div className="fixed-input"><PackageCheck size={15} /> 换货商品送达</div></label>
        </div>
        <label className="reply-editor">
          <span>消费者回复</span>
          <textarea value={reply} onChange={(event) => setReply(event.target.value)} />
          <small>不展示内部责任人、风险分数或规则术语</small>
        </label>
        <div className="approval-summary">
          <Sparkles size={16} />
          <p><b>确认后会发生什么</b><span>创建服务责任与倒计时、发送进度回执，并持续等待物流事件。</span></p>
        </div>
        <footer>
          <button className="dialog-cancel" onClick={onClose}>返回修改</button>
          <button className="dialog-confirm" onClick={onConfirm} disabled={acting || !reply.trim()}>
            {acting ? <Loader2 size={16} className="spin" /> : <Check size={16} />}
            确认并发送回执
          </button>
        </footer>
        <p className="rule-footnote">依据 {decision.rule_id} · 人工事实将成为最高优先级</p>
      </div>
    </div>
  );
}

export default App;
