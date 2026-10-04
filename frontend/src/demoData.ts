import analyzeExample from "./api/examples/01-analyze-case.json";
import type { CaseInput, PreparedAction } from "./api/contracts";

const heroInput = analyzeExample.case_input_fixture as unknown as CaseInput;

export interface DemoCase {
  id: string;
  shortId: string;
  title: string;
  preview: string;
  time: string;
  unread?: number;
  expectedDecision: "INTERVENE" | "ALLOW" | "HUMAN_REVIEW";
  sourceLabel: string;
  input: CaseInput;
  preparedAction: PreparedAction;
  composerText: string;
  productImage?: string;
  productImageIsSynthetic?: boolean;
  productShortLabel: string;
  productPrice: string;
  evidenceVariant?: "hero" | "gift";
}

const heroScope = {
  order_id: heroInput.order.order_id,
  fulfillment_item_id: heroInput.current_issue.fulfillment_item_id,
  sku_id: heroInput.current_issue.sku_id,
  issue_type: heroInput.current_issue.issue_type,
};

function scopeFor(input: CaseInput) {
  return {
    order_id: input.order.order_id,
    fulfillment_item_id: input.current_issue.fulfillment_item_id,
    sku_id: input.current_issue.sku_id,
    issue_type: input.current_issue.issue_type,
  };
}

function withOrderId(input: CaseInput, orderId: string, logisticsNumber: string): CaseInput {
  const serialized = JSON.stringify(input)
    .split(heroInput.order.order_id).join(orderId)
    .split(heroInput.order.original_logistics_number).join(logisticsNumber);
  return JSON.parse(serialized) as CaseInput;
}

const giftCase: CaseInput = {
  ...withOrderId(heroInput, "6920185815517983397", "773478190943156"),
  case_id: "DEMO_002",
  evaluation_time: "2026-05-05T11:00:00+08:00",
  data_provenance: {
    ...heroInput.data_provenance,
    source_session_id: "TEAM_SYNTH_002",
    augmentation_notes: ["消费者、订单与对话为团队构建的独立合成案例", "赠品面膜照片用于展示证据与当前问题不匹配的判断"],
  },
  conversation: [
    {
      message_id: "DEMO_AUG_MSG_002_1",
      timestamp: "2026-05-05T10:41:00+08:00",
      speaker: "CONSUMER",
      text: "刚拆开复颜精华，瓶口有一道裂痕。我怕漏出来，能帮我处理吗？",
      source_kind: "DEMO_AUGMENTATION",
    },
    {
      message_id: "DEMO_AUG_MSG_002_2",
      timestamp: "2026-05-05T10:48:00+08:00",
      speaker: "AGENT",
      text: "麻烦发一张瓶口的照片，我帮您核实。",
      source_kind: "DEMO_AUGMENTATION",
    },
    {
      message_id: "DEMO_AUG_MSG_002_3",
      timestamp: "2026-05-05T10:55:00+08:00",
      speaker: "CONSUMER",
      text: "照片发过去了，刚从相册里选的。",
      source_kind: "DEMO_AUGMENTATION",
    },
    {
      message_id: "DEMO_AUG_MSG_002_4",
      timestamp: "2026-05-05T10:57:00+08:00",
      speaker: "AGENT",
      text: "这张好像对不上。您把订单和照片都重新发一遍吧。",
      source_kind: "DEMO_AUGMENTATION",
    },
    {
      message_id: "DEMO_AUG_MSG_002_5",
      timestamp: "2026-05-05T10:58:00+08:00",
      speaker: "CONSUMER",
      text: "我刚刚发过了。到底缺哪张？别让我整单从头再传。",
      source_kind: "DEMO_AUGMENTATION",
    },
  ],
  order: {
    ...withOrderId(heroInput, "6920185815517983397", "773478190943156").order,
    items: [
      {
        fulfillment_item_id: "6920185815517983397-EL-RS30",
        sku_id: "EL-RS30",
        product_name: "复颜修护精华 30ml",
        item_role: "PRIMARY",
      },
      {
        fulfillment_item_id: "6920185815517983397-GIFT-01",
        sku_id: "GIFT-B5-MASK-2",
        product_name: "B5面膜体验装 2片",
        item_role: "GIFT",
      },
    ],
  },
  current_issue: {
    fulfillment_item_id: "6920185815517983397-EL-RS30",
    sku_id: "EL-RS30",
    issue_type: "PACKAGE_DAMAGE",
    affected_component: "BOTTLE",
  },
  service_tickets: [],
  evidence_images: [
    {
      evidence_id: "TEAM_SYNTH_002_GIFT_IMG",
      file_name: "s00001-gift-evidence.jpg",
      submitted_at: "2026-05-05T10:55:00+08:00",
      declared_view_type: "PACKAGE_CONTEXT",
      source_kind: "TEAM_SYNTHETIC_AUGMENTATION",
      source_message_id: "DEMO_AUG_MSG_002_3",
      competition_reference_path: null,
    },
  ],
};

const blurredCase: CaseInput = {
  ...withOrderId(heroInput, "6920185815517983398", "773478190943157"),
  case_id: "DEMO_003",
  evaluation_time: "2026-05-05T11:00:00+08:00",
  data_provenance: {
    ...heroInput.data_provenance,
    source_session_id: "TEAM_SYNTH_003",
    augmentation_notes: ["消费者、订单与对话为团队构建的独立合成案例", "未构造或展示健康图片；使用不适由人工谨慎核实"],
  },
  conversation: [
    {
      message_id: "DEMO_AUG_MSG_003_1",
      timestamp: "2026-05-05T10:14:00+08:00",
      speaker: "CONSUMER",
      text: "昨天用了这支防晒，脸有点泛红、刺痛。是产品的问题吗？",
      source_kind: "DEMO_AUGMENTATION",
    },
    {
      message_id: "DEMO_AUG_MSG_003_2",
      timestamp: "2026-05-05T10:21:00+08:00",
      speaker: "AGENT",
      text: "方便上传一张面部照片吗？这样我们好判断。",
      source_kind: "DEMO_AUGMENTATION",
    },
    {
      message_id: "DEMO_AUG_MSG_003_3",
      timestamp: "2026-05-05T10:58:00+08:00",
      speaker: "CONSUMER",
      text: "现在还红着。我不想在聊天里发脸部照片，能先让专人跟进吗？",
      source_kind: "DEMO_AUGMENTATION",
    },
  ],
  order: {
    ...withOrderId(heroInput, "6920185815517983398", "773478190943157").order,
    items: [{
      fulfillment_item_id: "6920185815517983398-EL-SUN40",
      sku_id: "EL-SUN40",
      product_name: "清爽防晒乳 SPF50+ 40ml",
      item_role: "PRIMARY",
    }],
  },
  current_issue: {
    fulfillment_item_id: "6920185815517983398-EL-SUN40",
    sku_id: "EL-SUN40",
    issue_type: "ADVERSE_REACTION",
    affected_component: "UNKNOWN",
  },
  service_tickets: [],
  evidence_images: [],
};

export const demoCases: DemoCase[] = [
  {
    id: "DEMO_001",
    shortId: "S00001",
    title: "林小满",
    preview: "换货到底有没有发？",
    time: "09:32",
    unread: 1,
    expectedDecision: "INTERVENE",
    sourceLabel: "换货跟进",
    input: heroInput,
    preparedAction: {
      action_id: "ACT_001",
      action_type: "ASK_EVIDENCE",
      requested_scope: heroScope,
      requires_human_approval: false,
    },
    composerText: "麻烦您再上传一次泵头破损照片，我收到后才能继续处理。",
    productImage: "/evidence/s00001-product-overview.jpg",
    productShortLabel: "粉底",
    productPrice: "¥329.00",
    evidenceVariant: "hero",
  },
  {
    id: "DEMO_002",
    shortId: "SYN-02",
    title: "周婉晴",
    preview: "我发过照片，还要整单重传？",
    time: "10:58",
    expectedDecision: "ALLOW",
    sourceLabel: "证据范围不符",
    input: giftCase,
    preparedAction: {
      action_id: "ACT_002",
      action_type: "ASK_EVIDENCE",
      requested_scope: scopeFor(giftCase),
      requires_human_approval: false,
    },
    composerText: "照片收到了。现有照片拍的是赠品面膜，不用重发订单；麻烦只补充一张精华瓶口裂痕的近照，我就按这件商品继续核实。",
    productImage: "/evidence/demo-serum-product.png",
    productImageIsSynthetic: true,
    productPrice: "订单商品",
    productShortLabel: "精华",
    evidenceVariant: "gift",
  },
  {
    id: "DEMO_003",
    shortId: "SYN-03",
    title: "陈语桐",
    preview: "脸还在发红，必须先拍照吗？",
    time: "10:58",
    expectedDecision: "HUMAN_REVIEW",
    sourceLabel: "使用不适待复核",
    input: blurredCase,
    preparedAction: {
      action_id: "ACT_003",
      action_type: "ASK_EVIDENCE",
      requested_scope: scopeFor(blurredCase),
      requires_human_approval: false,
    },
    composerText: "已记录您使用后泛红、刺痛的反馈，不用先上传面部照片。我会交给专人核实；在核实前请先暂停使用，如不适明显或持续，请及时咨询医生。",
    productImage: "/evidence/demo-sunscreen-product.png",
    productImageIsSynthetic: true,
    productPrice: "订单商品",
    productShortLabel: "防晒",
  },
];

export const decisionLabels = {
  INTERVENE: {
    eyebrow: "发送已暂停",
    title: "别让消费者再做一次",
    compact: "已拦截重复索证",
  },
  ALLOW: {
    eyebrow: "可以继续",
    title: "当前范围需要新证据",
    compact: "范围变化，合理索证",
  },
  HUMAN_REVIEW: {
    eyebrow: "等待人工确认",
    title: "事实不足，暂不自动判断",
    compact: "已转人工复核",
  },
} as const;

export function formatClock(value: string) {
  return new Intl.DateTimeFormat("zh-CN", {
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  }).format(new Date(value));
}
