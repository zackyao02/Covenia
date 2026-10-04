import { describe, expect, it } from "vitest";
import type { CustomerState } from "./api/contracts";
import { canRefreshSuggestedDraft, replySuggestionsFor } from "./replySuggestions";

describe("reply suggestions", () => {
  it("offers case-specific, editable replies without claiming a completed action", () => {
    expect(replySuggestionsFor("DEMO_001", null)[0].text).toContain("核实换货单");
    expect(replySuggestionsFor("DEMO_002", null)[0].text).toContain("不用重传整单");
    const human = replySuggestionsFor("DEMO_003", null)[0].text;
    expect(human).toContain("交由专人核实");
    expect(human).not.toContain("专人已接手");
  });

  it("uses a successful worsening judgment only to prefer an empathetic tone", () => {
    const state = { decision_advisory: { source: "JEV", jev_call: { succeeded: true }, emotion: { trend: "WORSENING" } } } as CustomerState;
    expect(replySuggestionsFor("DEMO_001", state)[0].id).toBe("empathetic");
    const fallback = { decision_advisory: { source: "RULE_FALLBACK", jev_call: { succeeded: false }, emotion: { trend: "WORSENING" } } } as CustomerState;
    expect(replySuggestionsFor("DEMO_001", fallback)[0].id).toBe("direct");
  });

  it("responds to the latest consumer question rather than repeating the initial template", () => {
    const confirmation = replySuggestionsFor("DEMO_002", null, "不用重传整个订单对吗？")[0].text;
    expect(confirmation.startsWith("对，不用重传整单。")).toBe(true);
    const handoff = replySuggestionsFor("DEMO_003", null, "请问专人什么时候联系我？")[0].text;
    expect(handoff).toContain("仍待确认");
  });

  it("answers a request for the promised update time with the recorded time", () => {
    const reply = replySuggestionsFor(
      "DEMO_001",
      null,
      "明白。下次更新时间大约是什么时候？我不想再反复来问了。",
      "10:10",
    )[0].text;
    expect(reply).toContain("10:10前");
    expect(reply).toContain("主动告诉您");
  });

  it("refreshes only an untouched automatic draft when the consumer asks a new question", () => {
    const oldSuggestion = "只需补充精华瓶口近照。";
    expect(canRefreshSuggestedDraft(oldSuggestion, oldSuggestion)).toBe(true);
    expect(canRefreshSuggestedDraft("  ", oldSuggestion)).toBe(true);
    expect(canRefreshSuggestedDraft("我自己改过的回复。", oldSuggestion)).toBe(false);
  });

  it("changes factual replies only after the corresponding service event", () => {
    const before = replySuggestionsFor("DEMO_002", null, "发过去以后会继续处理吗？")[0].text;
    expect(before).toContain("只需补");
    const after = replySuggestionsFor("DEMO_002", null, "发过去以后会继续处理吗？", "12:00", "CURRENT_SCOPE_EVIDENCE_SUBMITTED")[0].text;
    expect(after).toContain("已经收到");
    expect(after).toContain("12:00前");
    const assigned = replySuggestionsFor("DEMO_003", null, "专人什么时候联系我？", "12:00", "SPECIALIST_ASSIGNED")[0].text;
    expect(assigned).toContain("已经接手");
    expect(assigned).toContain("12:00前");
  });

  it("updates shipment replies from the recorded milestone instead of asking to recheck a known pickup", () => {
    const pickedUp = replySuggestionsFor("DEMO_001", null, "什么时候告诉我？", "10:10", null, { milestone: "IN_TRANSIT", status: "ON_TRACK" })[0].text;
    expect(pickedUp).toContain("已由物流揽收");
    expect(pickedUp).not.toContain("是否揽收");
    const delayed = replySuggestionsFor("DEMO_001", null, "现在怎么样？", "12:00", null, { milestone: "AWAITING_CARRIER_PICKUP", status: "AT_RISK" })[0].text;
    expect(delayed).toContain("升级催办");
    const delivered = replySuggestionsFor("DEMO_001", null, "现在怎么样？", null, null, { milestone: "DELIVERED", status: "COMPLETED" })[0].text;
    expect(delivered).toContain("已显示送达");
  });
});
