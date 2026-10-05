# -*- coding: utf-8 -*-
"""构建 X-A-TRUTH 门凭证：handoff/a/evaluation-manifest.json"""
import hashlib, io, json, os, subprocess, sys, datetime
sys.stdout.reconfigure(encoding='utf-8')
root = r'C:\Users\WONG Tsun Ming\Desktop\欧莱雅黑客松'
repo = os.path.join(root,'work','repo2')
remote = os.path.join(root,'work','repo-remote')
REF='integration/covenia-b'
def gb(p, ref=REF, rp=None):
    o = subprocess.run(['git','-C',rp or repo,'show','%s:%s'%(ref,p)],capture_output=True)
    return o.stdout if o.returncode==0 else b''
def gj(p, ref=REF, rp=None):
    return json.loads(gb(p,ref,rp).decode('utf-8-sig'))
def sha(b): return hashlib.sha256(b).hexdigest().upper()

gt  = gj('fixtures/ground-truth.json')
dc  = gj('fixtures/demo-cases.json')
j20 = gj('A-line/A-line-FINAL/03-FIRST-BATCH-ANNOTATIONS-20-CASES.json','origin/A-line',remote)
jsel= gj('A-line/A-line-FINAL/03-CASE-SELECTION-LIST.json','origin/A-line',remote)

# --- 三个 Demo 真值：冲突同步核验 ---
demo = []
for d, g in zip(dc, gt):
    cid = d['demo_case_id']
    ci = d['case_input']
    conv = ci.get('conversation') or []
    entry = {
      "demo_case_id": cid,
      "title": d.get('title'),
      "session_id": ci.get('case_id'),
      "evaluation_time": ci.get('evaluation_time'),
      "message_count": len(conv),
      "first_message_at": conv[0].get('timestamp') if conv else None,
      "last_message_at": conv[-1].get('timestamp') if conv else None,
      "data_provenance": ci.get('data_provenance'),
      "expected": {
        "evidence_status": g.get('expected_evidence_status'),
        "decision": g.get('expected_decision'),
        "rule_id": g.get('expected_rule_id'),
        "rule_priority": g.get('expected_rule_priority'),
        "resolution_candidate": g.get('expected_resolution_candidate'),
        "creates_obligation": g.get('expected_creates_obligation'),
        "promise_deadline": (g.get('expected_promise') or {}).get('deadline'),
        "action_impacts": g.get('expected_action_impacts'),
      },
    }
    demo.append(entry)

# --- 冲突同步事实（D07）---
sync = {
  "reference": "docs/approvals/b-decisions.json T01 时间线确认 + PRODUCT-FREEZE 附录 P0-4",
  "changes_applied": [
    {"file":"fixtures/demo-cases.json","field":"DEMO_001.case_input.evaluation_time",
     "from":"2026-05-07T11:00:00+08:00","to":"2026-05-07T09:40:00+08:00",
     "reason":"11:00 晚于承诺截止 2026-05-07T10:27:37，与真值措辞「即将到期」矛盾"},
    {"file":"fixtures/demo-cases.json","field":"DEMO_001 会话补回 94357468399952.PNM",
     "from":None,"to":"2026-05-05T10:25:13+08:00 消费者「行，那尽快哈」",
     "reason":"活动 1 验收门槛：原始聊天必须全部进入同一案例链路；该消息是「模糊表达不生成截止时间」的唯一对照语料"},
    {"file":"fixtures/demo-cases.json","field":"DEMO_AUG_MSG_001.timestamp",
     "from":"2026-05-07T10:45:00+08:00","to":"2026-05-07T09:32:00+08:00",
     "reason":"冻结 P0-4 二次进线时间"},
    {"file":"fixtures/ground-truth.json","field":"DEMO_001.expected_action_impacts",
     "from":["BLOCK_REPEAT_EVIDENCE","RAISE_PRIORITY","CHECK_EXISTING_FULFILLMENT","START_PROACTIVE_UPDATE"],
     "to":["BLOCK_REPEAT_EVIDENCE","CHECK_EXISTING_FULFILLMENT","START_PROACTIVE_UPDATE"],
     "reason":"冻结 P0-4 要求移除 RAISE_PRIORITY"},
  ],
}
# 核验是否真的生效
c1 = [c for c in dc if c['demo_case_id']=='DEMO_001'][0]['case_input']
ids = [m.get('message_id') for m in c1['conversation']]
sync["verification"] = {
  "demo001_evaluation_time_is_0940": c1.get('evaluation_time') == "2026-05-07T09:40:00+08:00",
  "demo001_has_94357468399952_PNM": "94357468399952.PNM" in ids,
  "demo_aug_msg_001_timestamp": [m.get('timestamp') for m in c1['conversation'] if m.get('message_id')=='DEMO_AUG_MSG_001'],
  "demo001_action_impacts": [g.get('expected_action_impacts') for g in gt if g.get('demo_case_id')=='DEMO_001'][0],
  "no_RAISE_PRIORITY_anywhere_in_gt": "RAISE_PRIORITY" not in json.dumps(gt, ensure_ascii=False),
}

# --- 20 开发样本 ---
samples = []
for c in j20['cases']:
    ed = c.get('expected_decision') or {}
    samples.append({
      "annotation_id": c.get('annotation_id'),
      "case_id": c.get('case_id'),
      "split": c.get('split'),
      "is_hero": c.get('is_hero'),
      "source": c.get('source_trace'),
      "input_ref": {"scene": c.get('scene'), "reference_prepared_action": c.get('reference_prepared_action')},
      "expected": {
        "decision": ed.get('decision') if isinstance(ed,dict) else ed,
        "rule_id": ed.get('rule_id') if isinstance(ed,dict) else None,
        "rule_priority": ed.get('rule_priority') if isinstance(ed,dict) else None,
        "evidence_coverage": c.get('evidence_coverage'),
        "responsibility": c.get('responsibility'),
        "prohibited_actions": c.get('prohibited_actions'),
        "recommended_resolution": c.get('recommended_resolution'),
      },
      "challenge_variants": len(c.get('challenge_variants') or []),
      "expected_ledger_assertions": c.get('expected_ledger_assertions'),
      "annotation_meta": c.get('annotation_meta'),
    })

manifest = {
  "artifact": "handoff/a/evaluation-manifest.json",
  "gate": "X-A-TRUTH",
  "status": "READY_FOR_ACCEPTANCE",
  "owner": "A（数据与调研）编写；D 接收；Zack 批准政策含义",
  "produced_by": "审查方（B 线）依 A 线 2026-10-05 交付包机械转换；原始作者为 A 线",
  "produced_at": datetime.datetime.now().isoformat(timespec='seconds'),
  "purpose": "登记三个 Demo 真值的冲突同步结果、20 个开发样本的来源/输入/预期/评测口径与 hash，供 D 线接收与 BATCH-29 消费",
  "criteria_addressed_verbatim": [
    "三个 Demo 真值完成冲突同步，20 开发样本的来源/输入/预期/评测口径与 hash 就绪。",
    "10 留出样本另交 D；20/10 是评测样本划分，不等于新增 30 个产品场景。"
  ],
  "three_demo_truths": {"conflict_sync": sync, "cases": demo},
  "dev_samples": {
    "count": len(samples),
    "annotation_set_id": j20.get('annotation_set_id'),
    "version": j20.get('version'),
    "labeling_rules_version": j20.get('labeling_rules_version'),
    "coverage_summary": j20.get('coverage_summary'),
    "ground_truth_notice": j20.get('ground_truth_notice'),
    "samples": samples,
  },
  "holdout_separation": {
    "count": 10,
    "separate_manifest": "private-evaluation/holdout-manifest.json",
    "in_repository": False,
    "note": "按门要求，留出样本manifest 不入仓库、不入运行服务，仅独立验收进程可读。",
    "sample_division_is_not_new_scenarios": "20/10 是评测样本划分，不等于新增 30 个产品场景。"
  },
  "artifact_hashes": {
    "method": "SHA-256 over raw bytes streamed from git show <ref>:<path>",
    "fixtures/ground-truth.json": sha(gb('fixtures/ground-truth.json')),
    "fixtures/demo-cases.json": sha(gb('fixtures/demo-cases.json')),
    "handoff/a/cases-manifest.json": sha(gb('handoff/a/cases-manifest.json')),
    "handoff/a/data-mapping.json": sha(gb('handoff/a/data-mapping.json')),
    "A-line/A-line-FINAL/03-FIRST-BATCH-ANNOTATIONS-20-CASES.json": sha(gb('A-line/A-line-FINAL/03-FIRST-BATCH-ANNOTATIONS-20-CASES.json','origin/A-line',remote)),
    "A-line/A-line-FINAL/03-CASE-SELECTION-LIST.json": sha(gb('A-line/A-line-FINAL/03-CASE-SELECTION-LIST.json','origin/A-line',remote)),
  },
  "honest_limitations": [
    "本文件由审查角色依 A 线交付包机械转换生成，非 A 线原笔；正式接收应由 A 线或 D 线确认。",
    "20 开发样本的「评测口径」沿用 A 线 labeling_conventions（A-LABELING-1.1.0），未由审查方独立复核其标注正确性。",
    "图片相关工作簿不含图片文件，A 线约定5 说明 covered/missing 由文本与路径线索推定，涉及图片的案例 confidence 最高 MEDIUM。",
  ],
}
out = json.dumps(manifest, ensure_ascii=False, indent=2)
d = os.path.join(root,'handoff','a')
os.makedirs(d, exist_ok=True)
p = os.path.join(d,'evaluation-manifest.json')
io.open(p,'w',encoding='utf-8',newline='\n').write(out)
print('已写出 %s' % p)
print('字节: %d | SHA256: %s' % (len(out.encode()), sha(out.encode())))
print()
print('冲突同步核验:')
for k,v in sync['verification'].items(): print('  %-40s %s' % (k, v))
print()
print('20 样本:', len(samples), '| decision 分布:', j20['coverage_summary']['decision'])
print('rule 分布:', j20['coverage_summary']['rule_id'])
