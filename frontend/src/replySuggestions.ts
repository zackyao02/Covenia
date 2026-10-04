import type { CustomerState, DemoServiceEventType, OpenObligation } from "./api/contracts";

export interface ReplySuggestion {
  id: "direct" | "empathetic";
  label: string;
  text: string;
}

export function canRefreshSuggestedDraft(currentDraft: string, previousSuggestion: string | null): boolean {
  return !currentDraft.trim() || currentDraft === previousSuggestion;
}

// Safe, case-scoped reply copy. JEV may change the ordering, never the service facts.
export function replySuggestionsFor(caseId: string, state: CustomerState | null, latestConsumerText = "", nextUpdateLabel: string | null = null, serviceEvent: DemoServiceEventType | null = null, fulfillment: Pick<OpenObligation, "milestone" | "status"> | null = null): ReplySuggestion[] {
  const message = latestConsumerText.replace(/\s+/g, "");
  let options: ReplySuggestion[] = caseId === "DEMO_001"
    ? [
        { id: "direct", label: "说明下一步", text: "您之前提交的泵头照片已经收到，不用再发。我会先核实换货单是否已被物流揽收，并在约定更新时间前主动告诉您核实结果。" },
        { id: "empathetic", label: "先回应顾虑", text: "让您反复询问换货进度，抱歉。泵头照片我们已经收到，不需要重复提交。我会继续核实物流揽收状态，并在约定更新时间前主动反馈。" },
      ]
    : caseId === "DEMO_002"
      ? [
          { id: "direct", label: "精准说明材料", text: "您已提交的赠品照片已经收到，不用重传整单。当前问题是精华瓶口，请只补这件精华瓶口裂痕的近照；收到后我们会继续核实。" },
          { id: "empathetic", label: "先回应顾虑", text: "抱歉让您不清楚该补哪张照片。您发过的赠品照片已记录，不用重复上传；只需补当前这件精华瓶口裂痕的近照，我们收到后继续核实。" },
        ]
      : [
          { id: "direct", label: "说明人工处理", text: "已记录您使用后脸部泛红的反馈。请先暂停使用；目前不要求提交面部照片，也不会在聊天中判断原因。我会交由专人核实，接手人与回复时间确认后再告诉您。" },
          { id: "empathetic", label: "先回应顾虑", text: "您担心专人何时接手，我理解。请先暂停使用，不必先发面部照片；我们会交由专人核实，确认接手人与下一次回复时间后主动告知您。若不适明显或持续，请及时咨询医生。" },
        ];
  if (caseId === "DEMO_001" && /什么时候|什么时间|下次更新/.test(message)) {
    options = [
      { id: "direct", label: "确认更新时间", text: nextUpdateLabel
        ? `我会在${nextUpdateLabel}前核实换货件是否揽收，并主动告诉您；如果物流节点仍未更新，我会继续跟进并说明原因。`
        : "您不需要再重复询问；我会以已经记录的下次更新时间为准，先核实换货件是否揽收，再主动向您反馈。如果节点仍未更新，我会继续跟进并说明原因。" },
      { id: "empathetic", label: "先回应等待", text: nextUpdateLabel
        ? `让您一直等进度，抱歉。泵头照片已经收到，无需再发；我会在${nextUpdateLabel}前核实揽收情况，并主动告知您。`
        : "让您一直等进度，抱歉。泵头照片已经收到，无需再发；我会在已约定的更新时间前核实揽收情况，并主动告知您，不让您反复来问。" },
    ];
  } else if (caseId === "DEMO_002" && /不用重传|不用再传|不需要重传/.test(message)) {
    options = [
      { id: "direct", label: "确认只补一张", text: "对，不用重传整单。已经收到的赠品照片会保留；当前只需补这件精华瓶口裂痕的近照，收到后我们会按这件商品继续核实。" },
      { id: "empathetic", label: "先回应顾虑", text: "您担心重复提交，我理解。现有赠品照片已经收到了，不用重传订单；只补精华瓶口裂痕这一张近照即可，我们收到后继续处理。" },
    ];
  } else if (caseId === "DEMO_002" && /发过去以后|继续处理|核实结果/.test(message)) {
    options = [
      { id: "direct", label: "确认后续处理", text: "会的。您只需补当前这件精华瓶口裂痕的近照；收到后我们会继续核实并告知下一步，不需要重新提交整单材料。" },
      { id: "empathetic", label: "先回应顾虑", text: "您补完这一张后，我们会继续按精华瓶口的问题处理，不会让您从头重来。现有赠品照片已记录，后续结果会再反馈给您。" },
    ];
  } else if (caseId === "DEMO_003" && /什么时候|谁接手|下一步回复/.test(message)) {
    options = [
      { id: "direct", label: "说明接手安排", text: "您的反馈已记录，先暂停使用，也不用先发面部照片。目前接手人和回复时间仍待确认；我会交由专人核实，确认后主动告诉您，不会在这里判断原因。" },
      { id: "empathetic", label: "先回应等待", text: "让您不确定何时得到回复，抱歉。我们先记录您使用后泛红的情况并交由专人核实；接手人与下一次回复时间确认后会主动告知。面部照片暂不需要提交。" },
    ];
  }
  if (caseId === "DEMO_001" && fulfillment?.milestone === "DELIVERED") {
    options = [
      { id: "direct", label: "确认已送达", text: "换货件已显示送达，这次换货进度已完成。请您确认收到的商品；若还有问题，可以直接告诉我们。" },
      { id: "empathetic", label: "确认收到情况", text: "让您一直等进度，抱歉。换货件现在已显示送达，请您确认收到的商品；如仍有问题，我们会继续协助。" },
    ];
  } else if (caseId === "DEMO_001" && fulfillment?.milestone === "IN_TRANSIT") {
    options = [
      { id: "direct", label: "同步揽收进度", text: "换货件已由物流揽收，正在运输。我会继续跟进直到送达，并在约定的下次更新时间前主动告诉您进展。" },
      { id: "empathetic", label: "回应等待顾虑", text: "您一直在等换货进度，抱歉。现在物流已揽收换货件；我们会继续跟进到送达，并在约定的下次更新时间前主动更新。" },
    ];
  } else if (caseId === "DEMO_001" && fulfillment?.status === "AT_RISK") {
    options = [
      { id: "direct", label: "说明催办进度", text: "核对后发现换货件仍未被物流揽收，我们已升级催办；会在约定的下次更新时间前主动告诉您结果，不需要您反复追问。" },
      { id: "empathetic", label: "先回应延迟", text: "抱歉，换货件还没有被物流揽收。我们已升级催办，并会在约定的下次更新时间前主动更新处理进度。" },
    ];
  } else if (caseId === "DEMO_002" && serviceEvent === "CURRENT_SCOPE_EVIDENCE_SUBMITTED") {
    options = [
      { id: "direct", label: "确认已收材料", text: `精华瓶口近照已经收到，赠品材料不用重传。现在由我们按这件精华继续核验${nextUpdateLabel ? `，${nextUpdateLabel}前主动更新` : "并主动更新"}。` },
      { id: "empathetic", label: "说明不会重来", text: `谢谢您补这张照片。精华瓶口的材料已记入当前问题，不会让您重传整单；后续由我们继续处理${nextUpdateLabel ? `，${nextUpdateLabel}前告诉您进展` : "并告诉您进展"}。` },
    ];
  } else if (caseId === "DEMO_003" && serviceEvent === "SPECIALIST_ASSIGNED") {
    options = [
      { id: "direct", label: "确认接手安排", text: `售后专员已经接手您使用后的反馈；不用先上传面部照片。${nextUpdateLabel ? `我们会在${nextUpdateLabel}前主动联系您` : "我们会主动联系您"}，目前不在聊天中判断原因。` },
      { id: "empathetic", label: "先回应等待", text: `让您等待回复，抱歉。现在已有售后专员负责跟进${nextUpdateLabel ? `，会在${nextUpdateLabel}前主动联系您` : "，会主动联系您"}；请先暂停使用，如不适明显或持续请及时咨询医生。` },
    ];
  } else if (caseId === "DEMO_003" && serviceEvent === "SPECIALIST_FOLLOWED_UP") {
    options = [
      { id: "direct", label: "确认专人反馈", text: `售后专员已记录您的反馈，后续仍由我们跟进${nextUpdateLabel ? `，${nextUpdateLabel}前再更新` : "并主动更新"}。目前不会自动判断不适原因。` },
      { id: "empathetic", label: "说明后续责任", text: `您的情况已有专人接手和记录；后续由品牌负责持续跟进${nextUpdateLabel ? `，${nextUpdateLabel}前主动反馈` : "并主动反馈"}，不用重复描述或上传面部照片。` },
    ];
  }
  const advisory = state?.decision_advisory ?? state?.decision.decision_advisory;
  const jevWorsening = advisory?.source === "JEV" && advisory.jev_call.succeeded && advisory.emotion.trend === "WORSENING";
  return jevWorsening ? [options[1], options[0]] : options;
}
