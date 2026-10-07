# Covenia 4H 初赛材料包

本目录集中存放 Covenia 的 H1–H4 初赛展示材料。

## 交付文件

- `Covenia-23-54-含4H初赛版.pptx`：在原答辩稿中保留“验证与落地路线”，并新增“从可运行原型到可验证产品”页面。
- `Covenia-4H-初赛产品展示方案.md`：说明 4H 的产品化表达、初赛展示顺序、答辩口径、证据边界和下一阶段验证计划。

## 可复现验证

- 验证入口：`validation/run_hypothesis_validation.py`
- 使用说明：`validation/README.md`
- 最新结果：`validation/results/hypothesis-validation.latest.md`
- 机器可读结果：`validation/results/hypothesis-validation.latest.json`

## 4H 定义

| H | 产品阶段 | 当前结论 |
|---|---|---|
| H1 | REMEMBER / Customer State | 机制已验证，业务效率待真人验证 |
| H2 | PROTECT / Experience Firewall | 设计边界案例得到支持，生产准确率待验证 |
| H3 | ANTICIPATE / JEV Decision Layer | 治理与可追溯性已验证，模型准确率与提前量待验证 |
| H4 | ENSURE / Promise Monitor | 监控与通知草稿链路已验证，真实业务提升待验证 |

当前证据来自赛事 Mock 数据和团队设计案例，只支持机制与安全边界结论，不代表生产环境效果。
