# BATCH-30 实施报告｜跨链反硬编码、注入与 PII 回归

> **本批由辅助调度器实现，非独立实现方；验收须由他方完成。**
>
> Implemented by the auxiliary dispatcher, not by an independent implementer; acceptance must be
> performed by another party.

| 项目 | 值 |
|---|---|
| 批次 | BATCH-30 |
| 分支 | `codex/covenia-batch-30-aux` |
| 基线集成 SHA | `b22cc46f43d9995ab196511562aa3e6e007dc565` |
| 实现提交 SHA | `9860ddc4bcd8dc0c368766ca0a358fbc3ca6a664` |
| 报告提交 | 本文件所在提交（按 MASTER_PLAN 5.3-4 不自引用自身 SHA） |
| 状态 | IMPLEMENTED（**不是** VERIFIED） |
| RUN_DIR / 解释器 | `C:\cv30` / `C:\cv30\venv\Scripts\python.exe` |
| 依赖锁 | `backend/requirements-dev.lock` — **UNCHANGED**，blob sha256 `602C268B684D60E2D1B8BBFC6820663A622EB24093144A87C111F43D3C06FDAE` |

## 1 交付内容

1. `tools/verification/check_no_case_branches.py` — 结构化（AST）反硬编码审计器。
   七条判据 J1–J7，取代"只搜四个字符串"的字面量黑名单。
2. `integration/tests/test_security_and_generalization.py` — 387 个测试，覆盖四条验收标准、
   真实服务路径攻击、A34 全组合与负向控制。

| 判据 | 含义 |
|---|---|
| J1 | 案例/订单/证据标识符出现在实现源码中；处于分支判定时额外标注 `in-decision` |
| J2 | 文件名/声明视角/模型置信度等**非语义描述符**在"不抛错"的函数中选择业务结论 |
| J3 | 正向图像观察事实被写成字面量 |
| J4 | 决策路径模块按路径读取 fixture / ground truth |
| J5 | 隐私模块读取配置或环境来决定是否掩码 |
| J6 | 标识/描述符分支**按输入**选择 fail-closed 默认值 |
| J7 | 从请求形状对象读取不可信兼容字段 |

**A33 判据二的处理（本批判据 J2）**：文件名/视角类型**可以**用于身份、输入校验、manifest
完整性，且**非法值必须抛错**；只要外层函数含 `raise`，该分支即便选择业务结论也被允许，
并逐条记录到 `static-scan.json:suppressed`（当前 0 条）。把"允许"做成可审计的显式清单，
而不是靠黑名单漏洞。

**fail-closed 豁免**：`UNKNOWN`/`LOW`/`False`/`0.0` 是安全方向，不作为"观察结果"（J3）；
但按输入挑选它们仍违反 J6。

## 2 验收标准证据映射

### 标准 1｜随机扰动 + 三决策矩阵，扫描不止搜四个字符串
- 108 格矩阵（证据状态 × 问题类型 × 动作 × 禁止项）逐格比对**契约推导**真值表；
  INTERVENE / ALLOW / HUMAN_REVIEW 三决策全部出现。
- 种子 `30001`，每格 6 次扰动（共 648 次）：重命名 case/action/order/sku/item/
  source ID、打乱 `prohibited_actions` 顺序。决策签名、匹配规则、被抑制规则、`fact_trace`、
  `reason` 全部不变；并从 JSON 重新解析后复算一致。
- 反空洞对照：`test_changed_facts_do_change_the_decision` 证明事实变化仍改变结果。
- 扫描行为性证据：审计器自检植入 9 个捷径；**其中只有 1 个含四个禁用字面量**；
  测试断言"四字面量黑名单只命中 1 个，而审计器判定 ≥6 个"。

### 标准 2｜PII 关闭后安全断言必败；生产配置不能绕过掩码
- 真实 `AnalyzeService` 路径：手机号 `[PHONE_REDACTED]`，`pii_masked_count ≥ 1`，
  数字不出现在 provider 入参、`redacted_trace()` 或响应 JSON。
- `Settings(pii_safety_checks_enabled=False)` 与默认设置掩码行为一致；
  `privacy/` 两个模块源码中不含该开关名；设置 `COVENIA_PII_SAFETY_CHECKS_ENABLED=false` 无影响。
- **负向控制**（`-m mutation`）：
  1. 禁用 `redact_text` → 原始号码真的到达 provider → 内层断言
     `PII must never reach the provider` 抛 `AssertionError`；
  2. 移除投影溯源校验 + 纵深文本探针 → 伪造投影真的到达 provider →
     `the privacy boundary must refuse a forged projection` 抛错；
  3. 同上两闸门驱动"被替换的 model_input" → `so this test cannot pass vacuously` 抛错。
  三者均在 `monkeypatch.context()` 退出后验证原行为恢复。**如实说明：控制 2/3 同时移除两层
  防御，因为任一单独存在仍会拦截；报告不暗示"一处改动即可泄漏"。**

### 标准 3｜伪造承诺不增 active_commitments；来源冲突不被 AI 置信度洗白；A34 全组合通过
- 消费者消息永不成为 active 承诺（`IGNORED` / `SOURCE_NOT_AGENT`），在纯编译器与真实
  AnalyzeService 两条路径上均验证；`active_commitments` 保持为空。
- `ModelCommitmentHint(activation_recommendation="ACTIVE")` 对编译结果**无任何影响**
  （逐字段相等）。
- 两个来源就 SKU 互相冲突时，`declared_evidence_valid ∈ {False,True} × confidence ∈ {0,0.5,1.0}`
  六种组合全部为 `NEED_HUMAN_REVIEW` → `CONFLICTING_SOURCE_FACTS` → H1 → HUMAN_REVIEW。
- A34：108 格全部"存在 `challenge_overrides` 但 `challenge_mode` 为 false → 结果与无覆盖一致"；
  并在真实 `EvaluateService` 上给出**使能对照**：同一覆盖载荷在 `challenge_mode=true` 时确实生效，
  证明"忽略"由标志位决定而非载荷无效。

### 标准 4｜本批绝对隔离 venv；依赖只增不改；pip check 退出 0
- `environment.json`：`C:\cv30\venv\Scripts\python.exe`、Python 3.13.5、`sys.prefix != sys.base_prefix`、
  `include-system-site-packages=false`、venv 最长路径 144 < 250、34 个已安装包。
- 依赖锁 `UNCHANGED`：前后 blob sha256 均为 `602C268B684D60E2D1B8BBFC6820663A622EB24093144A87C111F43D3C06FDAE`，无追加行；
  本批未新增任何第三方依赖（审计器与测试仅用标准库 + 已钉版本）。
- `pip check` 退出码 0（`No broken requirements found.`）；导入预检退出码 0。

## 3 提交前必须执行的命令（逐条退出码）

| 命令 | 退出码 |
|---|---|
| `C:\cv30\venv\Scripts\python.exe -c "import sys; from pathlib import Path; assert Path(sys.executable).resolve() == Path(sys.argv[1]).resolve() and sys.prefix != sys.base_prefix; print(sys.executable); print(sys.version)" C:\cv30\venv\Scripts\python.exe` | 0 |
| `C:\cv30\venv\Scripts\python.exe -m pip install --no-deps -r backend/requirements-dev.lock` | 0 |
| `C:\cv30\venv\Scripts\python.exe -m pip install --no-deps --no-build-isolation -e backend` | 0 |
| `C:\cv30\venv\Scripts\python.exe -c "import pytest, jsonschema; print('pytest/jsonschema import OK')"` | 0 |
| `C:\cv30\venv\Scripts\python.exe tools/verification/check_no_case_branches.py --strict` | 0 |
| `C:\cv30\venv\Scripts\python.exe tools/verification/check_no_case_branches.py --strict --json reports/batches/BATCH-30/static-scan.json` | 0 |
| `C:\cv30\venv\Scripts\python.exe tools/verification/check_no_case_branches.py --git b22cc46f43d9995ab196511562aa3e6e007dc565 --strict` | 0 |
| `C:\cv30\venv\Scripts\python.exe -m pytest integration/tests/test_security_and_generalization.py -q` | 0 |
| `C:\cv30\venv\Scripts\python.exe -m pytest integration/tests/test_security_and_generalization.py -q -m mutation` | 0 |
| `C:\cv30\venv\Scripts\python.exe -m pytest integration/tests/test_security_and_generalization.py --collect-only` | 0 |
| `C:\cv30\venv\Scripts\python.exe -m pytest backend/tests -q` | 0 |
| `C:\cv30\venv\Scripts\python.exe reports/batches/BATCH-30/negative-control/planted_mutation_demo.py --repo . --python C:\cv30\venv\Scripts\python.exe` | 0 |
| `C:\cv30\venv\Scripts\python.exe -m pip list --format=json` | 0 |
| `C:\cv30\venv\Scripts\python.exe -m pip check` | 0 |
| `git diff --check` | 0 |
| `git status --short` | 0 |
| `git rev-parse HEAD` | 0 |
| `git branch --show-current` | 0 |
| `git ls-files --eol backend/requirements-dev.lock` | 0 |
| `git config --show-origin core.autocrlf` | 0 |
| `C:\cv30\venv\Scripts\python.exe -c "import hashlib,subprocess;print(hashlib.sha256(subprocess.run(['git','show','HEAD:backend/requirements-dev.lock'],capture_output=True).stdout).hexdigest().upper())"` | 0 |
| `C:\cv30\venv\Scripts\python.exe tools/preflight/shortpath_check.py --repo . --run-dir C:\cv30` | 0 |

完整 stdout/stderr 见 `commands.json`；原始记录见 `raw-commands.json`。

## 4 pytest rootdir 与 marker 行为的**实测**说明

- 实测 `rootdir: C:\Users\WONG Tsun Ming\Desktop\欧莱雅黑客松\w30`，**没有** `configfile:` 行。
- 原因：仓库根既无 `pytest.ini` 也无带 `[tool.pytest.ini_options]` 的 `pyproject.toml`，
  而 `backend/pyproject.toml` 不在参数路径上。因此 `backend/pyproject.toml` 中注册的
  `mutation` marker **对本文件未生效**。
- 后果：全量运行出现 3 条 `PytestUnknownMarkWarning`；但 marker 仍被应用与选择，
  `-q -m mutation` 实测 `3 passed, 384 deselected`。
- 本批**不谎称** marker 已注册，也**不**新增仓库根 pytest 配置（不在 allowed_paths）。
- 建议：BATCH-34 用 `-c backend/pyproject.toml` / `-o markers=...` 运行集成套件，
  或取得批准的仓库根 pytest 配置；在那之前该 warning 应视为预期现象而非失败。

## 5 负向演示（植入 → 报错 → 完全还原）

驱动：`reports/batches/BATCH-30/negative-control/planted_mutation_demo.py`

| 步骤 | 观测 |
|---|---|
| 前置校验 | 两个目标文件的 LF 归一化 sha256 == `git show HEAD:<path>` blob sha256，且 `git status --porcelain` 为空 |
| 植入 | `rules/engine.py`：DEMO_001 分支 + 文件名分支 + 硬编码正向观察；`services/analyze.py`：请求兼容字段读取 + ground-truth 读取（均为惰性定义，不影响导入） |
| 扫描 | `--strict` 退出码 **1**，共 9 处命中，判据 `J1_CASE_LITERAL_IN_DECISION, J2_DESCRIPTOR_DECIDES_VERDICT, J3_OBSERVED_RESULT_HARDCODED, J4_GROUND_TRUTH_INGRESS, J7_REQUEST_STATE_REACHES_RULES` |
| 四字面量对照 | 五类判据中只有 DEMO_001 一类会被四字面量黑名单发现 |
| 还原 | `finally` 从内存写回；两文件字节一致、归一化 sha256 == blob sha256、`git status --porcelain` 为空 |
| 提交面证明 | `git diff --name-status b22cc46..9860ddc` 只有 6 条 `A`（新增），无任何实现文件被修改 |

## 6 退出码语义（handoff）

`check_no_case_branches.py`
- `0` 全部判据干净、扫描了声明目录、内置负向控制复现；
- `1` 至少一处判据违规，或某个植入自检用例未被按预期判定；
- `2` 工具错误（参数错误、根目录不存在、git ref 未知、源码无法解析）——工具错误**永不**视为产品通过。

`pytest`
- `0` 全部通过；`-m mutation` 子集同样 `0`（负向控制内部断言"失败"已被外层捕获并断言）。

## 7 边界与遗留

- **哈希口径（MASTER_PLAN 5.5-8）**：`IMPLEMENTATION_REPORT.json:artifact_hashes` 中的
  `report_artifacts_governed_lf_sha256` 为 **CRLF→LF 归一化**后的 sha256，与报告提交中的
  blob 哈希一致，验收方可直接用 `git show <报告提交>:<path>` 复算；同节的
  `report_artifacts_raw_worktree_sha256` 只是 CRLF 工作副本的对照值，**不得**用于核验
  （本机 `core.autocrlf=true`，blob 为 LF、检出为 CRLF）。
- **真实模型**：本批全部为替身（test double）。像素级图片注入配对的真实模型验证是
  **BATCH-32** 使用 A 素材的义务，**不被本批替代**。
- 未添加任何可公开访问的后门；未开放 docs/redoc/openapi；组合根仍只挂载冻结的四条 POST 路由。
- 未写 `VERIFICATION_REPORT.json`，未写 `verification-evidence/**`。
- 未 `git add .`，未 push，未触碰 `integration/covenia-b` 或其他 worktree。

## 8 回滚

按逆序 `git revert` 两次提交（先报告提交，再代码/测试/扫描器提交）。无生产源码、schema、
fixture、前端或其他批次产物受影响；无临时 mutation 残留。
