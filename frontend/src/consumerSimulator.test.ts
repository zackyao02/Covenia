import { describe, expect, it } from "vitest";
import { simulateConsumerReply } from "./consumerSimulator";

describe("local consumer conversation", () => {
  it("tracks the case-specific next question", () => {
    expect(simulateConsumerReply("DEMO_001", "已核实换货进度，待物流揽收后主动更新。", 0)).toContain("揽收");
    expect(simulateConsumerReply("DEMO_002", "只需补充精华瓶口的一张近照。", 0)).toContain("精华瓶口");
    expect(simulateConsumerReply("DEMO_003", "不用提供面部照片，交由专人复核。", 0)).toContain("专人");
  });

  it("does not mistake a refusal to resubmit for a request to resubmit", () => {
    const answer = simulateConsumerReply("DEMO_002", "对，不用重传整单。您只要补一张精华瓶口近照。", 1);
    expect(answer).toContain("只拍精华瓶口");
    expect(answer).not.toContain("不要整单重传");
  });

  it("stops the scripted consumer after two turns instead of repeating closing lines", () => {
    expect(simulateConsumerReply("DEMO_002", "好的，继续核实。", 2)).toBeNull();
    expect(simulateConsumerReply("DEMO_003", "我接手", 5)).toBeNull();
  });
});
