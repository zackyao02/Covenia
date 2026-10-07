# H1–H4 假设验证

该目录只验证当前代码和赛事模拟数据能够支持的部分，不把机制测试包装成业务效果。

## 运行

```bash
python -m venv .venv
.venv/bin/pip install -r backend/requirements-dev.txt
.venv/bin/python validation/run_hypothesis_validation.py
```

结果写入：

- `validation/results/hypothesis-validation.latest.json`：机器可读结果。
- `validation/results/hypothesis-validation.latest.md`：答辩和产品汇报可读摘要。

## 当前验证边界

- H1：验证 Customer State 完整性、稳定性和本地技术耗时。实际客服节省时间需要真人对照。
- H2：计算 3 个设计案例的规则精确匹配和重复索证混淆矩阵。样本不足以宣称生产准确率。
- H3：验证 JEV 失败安全、来源追踪和不覆盖服务规则。模型准确率与提前量需要独立人工标签。
- H4：验证 Deadline Monitor、单次升级和主动通知草稿。业务主动更新率需要真实发送日志。
