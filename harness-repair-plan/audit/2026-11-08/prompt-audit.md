# harness 提示词臃肿审计

审计对象：仓库 `origin/master`，提交 `2acc29b`（2026-10-25 合并 PR #6）。只读审计，未改动仓库。

## 0. 范围、方法和先要知道的几件事

**范围。** `commands/*.md` 23 个文件 10,714 行，`agents/*.md` 25 个文件 14,597 行（两个目录各含一份由 doc-sync 钩子自动生成的 README/INDEX），`CLAUDE.md` 125 行，合计 25,436 行、约 158 万字符（约 39 万 token）。行很长：`close.md` 平均每行 118 字符，`dev-overnight.md` 77，`CLAUDE.md` 88。所以按行计的削减比例偏保守，按字符算会更高。

**方法。**
- 重复：逐行规范化后跨文件比对（≥50 字符的行），再用 difflib 找连续匹配块，最后按段落做模糊匹配。
- 钩子：对照 `settings.json` 的 81 条注册，读钩子文件头部说明和关键代码，再对照 `docs/ENFORCEMENT-LEDGER.md` 的 `mode/precondition` 列（哪些默认只记日志、要设环境变量才拦）。
- 深读：最大的十个文件（dev-overnight、dev、dev-command、commit、close、changelog-analyst、qa、ba、pm、agents/dev）通读主要章节。其余文件读章节结构、量出块大小，再抽读。
- 估算：每行只归入一类，不重复计数。①–④、⑥ 列是可以删掉或压缩掉的行数。⑤ 列是为消除矛盾必须改写或删除的行数。

**钩子的真实强度（这是第①、⑤类判断的依据）。**

| 状态 | 钩子 | 提示词里怎么说 |
|---|---|---|
| 默认就拦（exit 2） | orchestrator-gate、block-background-tasks、read-size-guard、workflow-gate、todo-validate / todo-count / todo-sequence、tool-policy、bash-safety、git-privilege-guard、block-branch-pr-worktree、block-enterworktree、write-guard、claude-config-guard、bulk-commit-detector、push-analyst-grant-guard、aggregate-check（G3）、e2e-enforce、codex-enforce（开了 --codex 时）、artifact-contract 的旧路径（dev/qa 报告 schema）、do-report-gate、Stop 时间锁 | 大体一致 |
| 默认只记日志，要设环境变量才拦 | `subagentstop-cp-enforce.py`（`CP_ENFORCE_MODE`）、`pretool-obligation-gate.py` G1（`CLAUDE_OBLIGATION_GATE`）、`stop-obligation-gate.py` G4（`CLAUDE_OBLIGATION_TERMINAL`）、artifact-contract 的 obligation 路径（`CLAUDE_OBLIGATION_STOPGATE`）。`settings.json` 的 env 里这几个变量一个都没设 | 有 8 个文件写 cp-enforce "BLOCKS your exit (exit 2)"，见例 1 |
| 永远只警告 | `pretool-orchestrator-prompt-purity.py`、`pretool-subagent-code-block.py`、`pretool-layer-escalation-check.sh`、`pretool-bisect-gate.sh`、`pretool-layer-match-gate.sh`、`subagent-stop-guard-integrity.sh`、`subagent-stop-diff-check.sh` | dev.md 写 purity 钩子 "exits with code 2"，见例 2。dev.md 把 layer-escalation 叫作 "gate (mandatory)" |
| orchestrator-gate 的 Bash 上限 | 计数**只有派出 Agent 才清零**，中间穿插 Read、TodoWrite 都不清零。所以实际是"两次派活之间最多 5 次 Bash" | CLAUDE.md:57 写成 "5 consecutive same-name calls"，见例 6 |

---

## (a) 逐文件表

列：① 钩子已执行的复述；② 跨文件重复；③ 填充；④ 应进脚本的机械步骤；⑤ 矛盾（需改写或删除的行）；⑥ 必要但啰嗦（可压缩掉的行）。"瘦身后"等于原行数减去合计。

| 文件 | 行数 | ① | ② | ③ | ④ | ⑤ | ⑥ | 合计 | 瘦身后 | 降幅 | 主要问题 |
|---|---|---|---|---|---|---|---|---|---|---|---|
| `commands/dev-overnight.md` | 1893 | 60 | 300 | 130 | 120 | 15 | 250 | 875 | 1018 | 46% | ② 四合同和派活模板与 dev.md 重复；④ 56 行会话绑定 bash；③ 尚未启用的"派活信封"、死引用；⑤ 专家串行与并行、cp 钩子是否拦，自相矛盾 |
| `commands/dev.md` | 1675 | 90 | 230 | 265 | 135 | 15 | 150 | 885 | 790 | 53% | ③ 1387–1621 行通用说明；② 派活前缀重复 8 遍、5 个维度抄 qa.md；④ spec_path 补丁和 jq 脚本；⑤ 说 purity 钩子会 exit 2、ask 权限并不存在、示例里跳过专家 |
| `commands/dev-command.md` | 1122 | 30 | 700 | 100 | 0 | 140 | 0 | 970 | 152 | 86% | ② 705 行与 dev.md 逐字相同；⑤ 其余是过期分叉（没有 spec 新旧防护、只列 4 个维度） |
| `commands/commit.md` | 1058 | 55 | 140 | 50 | 150 | 10 | 165 | 570 | 488 | 54% | ④⑤ 用 bash 写 `until … route_finding` 循环，实际要派 Agent；② 路由表、R15、--auto 与 close.md 重复；③ AC11 / lane L7 / Must-Have 标签 |
| `commands/close.md` | 1016 | 40 | 120 | 60 | 160 | 10 | 200 | 590 | 426 | 58% | ④⑤ 80 行 shell 函数，依赖跨调用保留的变量；⑤ --force 语义前后相反；⑥ Step 2 的 QA 协议应该归 qa.md |
| `commands/clean.md` | 771 | 10 | 40 | 75 | 20 | 2 | 200 | 347 | 424 | 45% | ③ Philosophy / Safety Features / Quality Standards / Helper Scripts / Usage 等节；⑥ 三个报告模板约 190 行；⑤ 步骤编号从 6 跳到 10A |
| `commands/paseo-daemon.md` | 606 | 15 | 0 | 75 | 70 | 0 | 80 | 240 | 366 | 40% | ③ 蓝图追溯表、F1–F15 和 RUNTIME-AC 标签；④ 108 行 Bootstrap |
| `commands/spec.md` | 520 | 5 | 20 | 20 | 90 | 0 | 60 | 195 | 325 | 38% | ④ Step 6 finalize 182 行，含正则细节；① Interview 期间禁前台 Agent，已有 spec-block-foreground 钩子 |
| `commands/test.md` | 501 | 0 | 32 | 30 | 70 | 0 | 78 | 210 | 291 | 42% | ④ 84 行 bash（迁移 test/、清理、发现验证器）；② 32 行与 test-validator 相同；③ 带表情符号的报告模板 |
| `commands/push.md` | 265 | 45 | 10 | 15 | 50 | 0 | 30 | 150 | 115 | 57% | ① 53 行讲 push.sh 读令牌的内部实现；④ 131 行派活协议 |
| `commands/merge.md` | 227 | 15 | 5 | 10 | 60 | 0 | 15 | 105 | 122 | 46% | ④ 快照、校验、读授权令牌都是机械步骤；① merge.sh 和权限钩子已经在管 |
| `commands/restart.md` | 213 | 50 | 10 | 15 | 10 | 0 | 30 | 115 | 98 | 54% | ① 大段钩子内部实现（capability_token、guidance 绑定、清扫）；② 与 CLAUDE.md 第 16 条重复 |
| `commands/codex.md` | 203 | 0 | 10 | 15 | 40 | 0 | 20 | 85 | 118 | 42% | ④ 生成输出路径和 exec 模式命令 |
| `commands/spec-update.md` | 187 | 0 | 10 | 10 | 0 | 0 | 30 | 50 | 137 | 27% | ⑥ 模式说明可压缩；② 与 dev.md Step 17 的收尾规则重复 |
| `commands/pull.md` | 120 | 0 | 0 | 5 | 25 | 0 | 10 | 40 | 80 | 33% | ④ pull_exit_phase 的判定 |
| `commands/do.md` | 84 | 0 | 0 | 1 | 0 | 1 | 10 | 12 | 72 | 14% | 写得最精简，可作范本；⑤ 与 allow.md 对"正文是否注入"说法相反；缺一行"/do 期间不能派子代理（钩子会拦）" |
| `commands/tickets.md` | 69 | 0 | 0 | 0 | 0 | 0 | 10 | 10 | 59 | 14% | 小 |
| `commands/stop.md` | 44 | 4 | 0 | 5 | 0 | 0 | 0 | 9 | 35 | 20% | ③ "Why this command exists"；① sentinel 的说明 |
| `commands/checkpoint.md` | 43 | 0 | 0 | 15 | 0 | 0 | 0 | 15 | 28 | 35% | ③ "When to use" 和重复的示例 |
| `commands/README.md` / `INDEX.md` | 37 / 35 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 72 | 0% | doc-sync 自动生成，不计 |
| `commands/redev.md` | 19 | 1 | 0 | 0 | 0 | 2 | 0 | 3 | 16 | 16% | ⑤ 写"14 步"（实际 17 步），graphify 位置过期 |
| `commands/allow.md` | 6 | 0 | 0 | 0 | 0 | 1 | 0 | 1 | 5 | 17% | ⑤ 与 do.md 说法相反，指向已搬走的内容 |
| `agents/changelog-analyst.md` | 2058 | 35 | 90 | 200 | 450 | 5 | 250 | 1030 | 1028 | 50% | ④ Phase 3–10 是机械的 git 事务；③ 295 行 push-gate 补偿段落多为论证；① DO NOT 多条已由 git 钩子执行 |
| `agents/qa.md` | 1961 | 60 | 400 | 170 | 80 | 10 | 250 | 970 | 991 | 49% | ② 240 行 Output Format 与 schema 重复，另有 codex、anti-give-up、cp 共享块；③ "身份"演讲；⑤ "速度至上"与"深挖到底"冲突 |
| `agents/ba.md` | 1515 | 45 | 190 | 110 | 50 | 5 | 340 | 740 | 775 | 49% | ⑥ 187 行 context JSON 模板与 schema 重复；③ 44 行语气节；② intake 协议与 pm.md 重复 |
| `agents/pm.md` | 1198 | 25 | 210 | 60 | 30 | 5 | 230 | 560 | 638 | 47% | ② 六个共享块；⑥ test plan / triage / retro 模板；② 禁止跳过的模式与 ba、qa 重复 |
| `agents/dev.md` | 1106 | 60 | 180 | 120 | 100 | 10 | 85 | 555 | 551 | 50% | ④ owned-edits 账本（疑与 attribution 钩子重复，删前要核实）；② 权限节与 commands/dev.md Step 15 重复；⑤ 两个 "PARAMOUNT"；⑤ 标题写"自动更新 settings.json"，tool-policy 不让写 |
| `agents/spec.md` | 823 | 30 | 67 | 25 | 70 | 3 | 140 | 335 | 488 | 41% | ④ 60 行"确定性、无需 LLM 判断"的 coverage fallback，以及 cp-state 写入；② codex |
| `agents/style-inspector.md` | 739 | 25 | 62 | 120 | 120 | 0 | 80 | 407 | 332 | 55% | ④ 各标准的检测都是 grep，适合做成 linter；③ 大量 BAD/GOOD 示例 |
| `agents/user.md` | 618 | 20 | 128 | 50 | 0 | 0 | 100 | 298 | 320 | 48% | ② 128 行共享块（baseline、anti-give-up、authority、test-data、codex）；③ "You Are a Perfectionist"、可选提案 |
| `agents/product-owner.md` | 514 | 20 | 128 | 55 | 0 | 0 | 80 | 283 | 231 | 55% | 同 user.md |
| `agents/architect.md` | 495 | 20 | 128 | 55 | 0 | 0 | 70 | 273 | 222 | 55% | 同 user.md |
| `agents/cleanliness-inspector.md` | 444 | 25 | 62 | 30 | 60 | 0 | 50 | 227 | 217 | 51% | ② codex、cp、--changed-files 模式三个共享块；④ 18 类检测大多可脚本化 |
| `agents/test-executor.md` | 423 | 24 | 6 | 30 | 30 | 0 | 80 | 170 | 253 | 40% | ⑥ 输入、输出格式很长；③ 故障排查节 |
| `agents/ui-specialist.md` | 361 | 11 | 128 | 20 | 0 | 0 | 40 | 199 | 162 | 55% | ② 同 user.md；③ 引用不存在的模板文件 |
| `agents/test-validator.md` | 349 | 24 | 38 | 20 | 30 | 0 | 50 | 162 | 187 | 46% | ② 32 行与 commands/test.md 相同；④ 语法和依赖检查 |
| `agents/prompt-inspector.md` | 309 | 25 | 78 | 25 | 15 | 0 | 30 | 173 | 136 | 56% | ② codex、cp、--changed-files；④ 严重度是纯算术 |
| `agents/git-edge-case-analyst.md` | 275 | 24 | 6 | 25 | 10 | 0 | 40 | 105 | 170 | 38% | ① cp 合同；③ 示例 |
| `agents/test-writer.md` | 241 | 5 | 15 | 10 | 30 | 0 | 25 | 85 | 156 | 35% | ④ manifest 的 UPDATE/CREATE 和 hook_check 推导都是确定性逻辑 |
| `agents/merge-analyst.md` | 222 | 10 | 6 | 10 | 60 | 0 | 20 | 106 | 116 | 48% | ④ 写授权令牌等机械阶段；① DO NOT 由 git 钩子执行 |
| `agents/push-analyst.md` | 210 | 10 | 6 | 8 | 60 | 0 | 20 | 104 | 106 | 50% | 同 merge-analyst；push-analyst-grant-guard 会复核授权 |
| `agents/rule-inspector.md` | 208 | 24 | 6 | 10 | 10 | 0 | 25 | 75 | 133 | 36% | ① cp 合同 24 行 |
| `agents/cleaner.md` | 194 | 29 | 6 | 5 | 10 | 0 | 20 | 70 | 124 | 36% | ① cp 合同；Safety Rules 与 bash-safety 部分重叠 |
| `agents/pull-analyst.md` | 166 | 8 | 6 | 5 | 15 | 0 | 15 | 49 | 117 | 30% | 小 |
| `agents/graphify.md` | 94 | 0 | 6 | 0 | 20 | 0 | 10 | 36 | 58 | 38% | ④ 整个代理只为跑一个脚本；dev.md:241 自己说 pre-BA 阶段不该多一层 LLM |
| `agents/README.md` / `INDEX.md` | 39 / 35 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 74 | 0% | 自动生成，不计 |
| `CLAUDE.md` | 125 | 15 | 6 | 10 | 0 | 2 | 15 | 48 | 77 | 38% | ① orchestrator 门、分支、后台、sentinel 的实现细节；⑤ "5 consecutive" 不准；③ 第 15 条是维护者经验，不影响运行时行为 |
| **commands 小计** | **10714** | 420 | 1627 | 896 | 1000 | 196 | 1338 | **5477** | **5237** | **51%** | |
| **agents 小计** | **14597** | 559 | 1952 | 1163 | 1250 | 38 | 2050 | **7012** | **7585** | **48%** | |
| **总计** | **25436** | 994 | 3585 | 2069 | 2250 | 236 | 3403 | **12537** | **12899** | **49%** | |

### 十个最大文件的细节

**`commands/dev-overnight.md`（1893 行）**
- ① :125–126（state 文件归钩子所有，由 pretool-overnight-hook-guard 管；Stop 时间锁由 stop-workflow-coordinator 的 timelock 阶段管）。:1811–1858 State File Management、Integration with Hooks、Loop Mechanism，约 50 行在复述钩子。:340–351 sentinel 表。
- ② :389–470 Four Contracts Awareness 和层级词汇 ≈ dev.md:326–421。:1453–1510 层级升级 ≈ dev.md:1152–1175。:1511–1546 权限更新 ≈ dev.md:1077–1148。文件里有 18 处 FIRST ACTION、11 处 CHECKPOINT MARKING、8 处 obligation。Hard Rule 11 就是 CLAUDE.md 第 13 条。
- ③ :20–52 未启用的"信封"（例 20）。:136 和 :1849 是死引用。:236–243、:1087–1096 是事故叙述式注释。:293–297 "KNOWN ACCEPTED LIMITATION" 是写给人看的安全披露，应移到 docs。
- ④ :206–262 绑定块（例 17）。:1722–1732 默认分支探测。两处 write-qa-mode 调用各配 11 行注释，解释为什么不能加 `bash`。
- ⑤ :571–573 与 dev.md:270 冲突（例 4）。:31、:356 说 cp 钩子不拦，与 dev.md:235 相反，而本文件各模板里又写 "SubagentStop hook will block exit"。:76 写 "Launch ALL N … in parallel"，:1078 写 "batches of 1-3 per response"。
- ⑥ 582 行未标语言的代码块基本是派活模板。按文件自己在 :52 定的目标（每个模板 ≤12 行），可以压掉约 250 行。

**`commands/dev.md`（1675 行）**
- ① :9 "CRITICAL: Use TodoWrite"：prompt-workflow.py 已经注入待办清单和第一次 TodoWrite 的写法，workflow-gate 和 todo-validate 会拦。:184–196 "hook pre-done" 清单。:235。:876。:1625–1675 Prompt Purity 一节共 52 行。
- ② :62–73 = CLAUDE.md 第 13 条。:68 = CLAUDE.md Subagent Hook Discipline 第 4、5 条。:640–670 = qa.md:81–100。:1043–1048 = qa.md 的 "After Verification"。文件内部，:878–887 与 :905–921 重复。派活前缀重复 8 遍。
- ③ :1387–1621 共约 235 行：JSON 存放规则、与 /clean 的配合、Quality Standards、"Agent Development Use Cases"、端到端示例、Success Metrics、"Remember"。另有 :13–15 的 Philosophy；:424、:1062–1075、:1294–1303 的 Mascot 和 spec-2026 引用；:755 的跨文件编号说明；:1349 过期的 `claude_code_required`；:1675 指向一个家目录绝对路径下的自测文件，仓库里没有。
- ④ :127–138、:158–169、:198–218、:548–583、:1083–1110、:1179–1199，都是 bash、jq 或 python。
- ⑤ :270（例 4）。:282 与 :1576（例 5）。:1512–1531 写 "All development operations require user confirmation via `ask` permission"，而 `settings.json` 的 `permissions.ask` 是空的。:1673（例 2）。:450、:772（例 3）。:1375–1383 写 "Would you like me to create a git commit"，而按 pretool-git-privilege-guard，只有经 /commit 派出的 changelog-analyst 才能提交。
- ⑥ :77–105 扇出规则共 29 行，但都是超长段落，可减半。:1224–1312 完成报告模板。

**`commands/dev-command.md`（1122 行）**：见例 9。真正特有的内容只有 :67–71 一个指针（指向仓库里不存在的 `docs/dev/command-development-patterns.md`）和几项收尾检查。建议改成"等于 /dev，外加以下差异"，约 100–150 行。

**`commands/commit.md`（1058 行）**
- ① :20–26 的"仅限人类"标志，已由 `disable-model-invocation` 和 userprompt-bulk-commit-capability 钩子保证。:262–270 bulk 能力由钩子签发。:1026–1053 privilege guard 兼容说明。
- ② :80–178 的八行路由表和 R15 进展判定 ≈ close.md:146–321。:947–1020 的 --auto ≈ close.md:933–1007。
- ③ 28 处 AC11、lane L7、Must-Have #8、commit#6 之类的标签。
- ④⑤ :295–360（例 8）。
- ⑥ Step 7 各状态的处理，:673–855。

**`commands/close.md`（1016 行）**
- ① :37。"--force 已废弃"说了 13 遍。
- ② 路由、R15、--auto 与 commit.md 重复。:531 的 TodoWrite 顺序提醒 = dev.md:784。
- ③ :32 指向已不存在的 ba-spec 文件。34 处 AC、R、M 标签。"Codex-native" 字样，以及别处没有说明的 `--claude-code` 参数。
- ④ :161–241（例 7）。:334–349 Step 0。:64–73 用 python 检查参数组合。:244–274 QA 武装规则：3 个脚本的调用写了 30 行说明。
- ⑤ :79 与 :115、:30（例 10）。Step 2 的派活提示里写 "Invoke Skill(codex)"，与 Prompt Purity 冲突。
- ⑥ Step 2（:577–790）是 QA 的判定协议，属于 qa.md，在编排提示里重写了一遍。

**`agents/changelog-analyst.md`（2058 行）**
- ① :40–53（例 16）。posttool-push-gate-token-verify.py 的文件头直接写明，它把本文件第 1221–1225、555–569 行要模型手工做的检查机械化了。
- ③ :1508–1800 共 295 行补偿路径，大多是论证（"The gap this closes"、"Why rule 7 cannot be one of these cases"），还有 M 标签。
- ④ Phase 3–5、8–10（flock、私有 index、逐文件 stage、提交、令牌路径和 sha 复核），以及 :1803–1840 的三步 SHA 检查。这些都应该是一个带测试的提交脚本；模型只负责 Phase 2 的分类和 Phase 6 的提交信息。
- ⑤ :22 写 `CONTROL_ROOT=$HOME`，紧接着的注释却说 "NOT an author-absolute literal"。
- ⑥ Phase 2 分类，:212–478。

**`agents/qa.md`（1961 行）**
- ① :1931–1961 cp 合同。spec 不可写，由 tool-policy 保证。e2e 状态字段由 e2e-enforce 检查。
- ② :28 anti-give-up，:1317 codex，:1378 score 回显，:81–100 五个维度（与 dev.md 重复），:1663–1724 禁止模式（≈ ba.md:1261、pm.md:26、CLAUDE.md 第 12 条），:1393–1632 Output Format 共 240 行（≈ `schemas/qa-report.v2.json`）。
- ③ :14–27 身份演讲，:1368 "Why this matters"，:1794–1885 检查单和示例。
- ④ :568–637 硬编码扫描的 grep，:680–754 构建和部署命令。
- ⑤ :66 与 :14–27 冲突。:83、:98 写 "commands/dev.md Step 6"，实际是 Step 7。Step 10.1–10.5 违反 style-inspector 的"整数步骤编号"标准。
- ⑥ Steps 1–14 的验证流程。

**`agents/ba.md`（1515 行）**
- ① :1344–1383 cp 合同，含 "Cross-role scope (HARD RULE)"。
- ② :1384 codex，:1214 intake（= pm.md:1134），:1489 overnight spec，baseline 14 行。
- ③ :537–580（例 18）。另有 54 处历史引用。
- ④ :474–536 观察账本的"确定性延迟创建"。
- ⑤ :627 和 :648 都叫 "Step 1"。
- ⑥ :1016–1203 context JSON 模板 ≈ `schemas/context.v1.json`。:822–1015 Markdown 规格模板。Contract A–E 可以压缩，但四合同的唯一归属就该是 ba.md。

**`agents/pm.md`（1198 行）**
- ② :74 anti-give-up，:103 authority，:1072 codex，:1134 intake（= ba.md），:1016 overnight spec。:26–72 禁止跳过的模式 ≈ ba.md、qa.md 的禁止模式。
- ⑥ :376–517 test plan ≈ `schemas/test-plan.v1.json`。triage 和 retro 报告模板。

**`agents/dev.md`（1106 行）**
- ① :1076 cp 合同。
- ② :389–471 权限节 ≈ commands/dev.md Step 15。:12 authority，:966 codex，:1041 overnight spec。
- ③ :745–807 BAD/GOOD 反模式示例。:914–1000 "canonical example"。
- ④ :545–711 owned-edits 账本：要求模型为每次编辑手工记下精确的 old/new，并在首次编辑前抓快照。这是纯机械记账。pretool-attribution-pre.py / posttool-attribution-post.py 已经记录写入的归属，提交时以 ATTRIBUTION_LOG 为权威（changelog-analyst.md:28）。两者很可能重叠，删之前要核实 stage-owned-hunks.py 是否仍依赖这份账本。
- ⑤ :151 "SPEED IS PARAMOUNT" 和 :153 "SMALLEST DIFF IS PARAMOUNT" 两个"至上"。"不要跑完整测试套件"与"修 bug 必须先写测试"并存。:389 标题写"自动更新 settings.json"，而 tool-policy 的共享保护路径包含 `/.claude/settings.json`，实际只能写进报告。
- ⑥ :166–198 blast radius。

### 瘦身时必须保留的耦合

- `check-todo-md-sync.py` 会比对 `commands/<cmd>.md` 和 `scripts/todo/<cmd>.py` 里的 "Step N" 标记，所以步骤标题要留着，并与待办脚本同步。
- 有钩子按章节名或行号指回提示词：prompt-purity 的提示指向 dev.md 和 CLAUDE.md 的 "Orchestrator Prompt Purity" 一节；aggregate-check 的说明写 "commands/dev.md lines 613-670"（已过期，现在在 :872–953）；push-gate-token-verify 指向 changelog-analyst.md:1221–1225；artifact-contract 指向 close.md 的 "Artifact schema gate"。移动或删除这些章节时，要保留锚点名，或者同步改这些指针。
- `posttool-command-frontmatter-validate.py` 要求 frontmatter 完整。allow.md 和 do.md 的正文不能为空。

---

## (b) 20 个最清楚的例子

**1.【⑤+①】cp 钩子"会拦"的说法与代码不符，三处互相打架**
- 原文：`commands/dev.md:235` "`subagentstop-cp-enforce.py` **is** wired … it blocks (exit 2) on any `pending` checkpoint"。另有 7 个代理逐字写 "BLOCKS your exit (exit 2)"：architect.md:410、ba.md:1370、dev.md:1102、pm.md:1064、product-owner.md:426、qa.md:1957、user.md:532。
- 实际：`hooks/subagentstop-cp-enforce.py:4–14` 默认 ADVISORY，只有 `CP_ENFORCE_MODE=block` 才拦，`settings.json` 没设这个变量。
- 更乱的是：`commands/dev-overnight.md:31`、`:356` 写的是 "no hook blocks exit on pending checkpoints today"。

**2.【⑤】Prompt Purity 钩子被写成会拦，实际只警告**
- 原文：`commands/dev.md:1673` "On any blacklist hit, the hook exits with code 2"。`commands/dev-overnight.md:145` "`pretool-orchestrator-prompt-purity.py` rejects subagent dispatches containing `<options>`"。
- 实际：`hooks/pretool-orchestrator-prompt-purity.py:340–348` "WARNING-ONLY, never blocking"，`main()` 的每个分支都返回 0。

**3.【⑤】派活模板自己违反同文件的 Prompt Purity**
- 原文：`commands/dev.md:772` graphify 派活写 "Run: source ~/.claude/venv/bin/activate && python3 ~/.claude/scripts/graphify-enrich.py …"。`:450` 的 obligation 模板写 "the output of date -u +%Y-%m-%dT%H:%M:%SZ"。`commands/dev-overnight.md:356` 的 SECOND ACTION 给出 spec-check.py 的完整命令行。
- 冲突对象：`commands/dev.md:1638–1643` 禁止 shell 命令、`&&` 和 `$(...)`。

**4.【⑤】专家并行还是串行，两份命令规定相反**
- 原文：`commands/dev.md:270` "Call every specialist marked RELEVANT. Parallelize in a single Agent call."（dev-command.md:205 相同）
- 冲突对象：`commands/dev-overnight.md:571–573` "Specialists run SERIALLY … NEVER launch 2+ specialists in parallel"。

**5.【⑤+③】示例与正文规则相反**
- 原文：`commands/dev.md:1576–1577` 端到端示例写 "No specialists needed for this requirement → skip"。
- 冲突对象：同文件 `:282` "'No specialists needed' without per-specialist assessment — INVALID"。
- 示例还用了旧文件名 `ba-spec-20251226-114500.md`（:1584）。

**6.【⑤】CLAUDE.md 把 Bash 上限写错了**
- 原文：`CLAUDE.md:57` "`Bash` capped at 5 consecutive same-name calls"。
- 实际：`hooks/pretool-orchestrator-gate.py:13–20` "cleared ONLY by an Agent (subagent) dispatch … interleaving a non-Agent tool between Bash calls does NOT launder the streak"。
- 后果：实际规则是"两次派活之间最多 5 次 Bash"。第④类那些长 shell 序列就撞在这条线上。

**7.【④+⑤】close.md 的 shell 函数依赖跨调用保留的变量，照写跑不起来**
- 原文：`commands/close.md:161–241` 用 bash 定义 `close_route_finding`、`close_progress`、`close_awaiting_input`，状态放在 shell 变量 `REQUIRED_ACTIONS_JSON`（:197）和 `CLOSE_PROGRESS_SEEN`（:213、:218）里，还要求跨多轮、跨 Agent 派活累积。
- 冲突对象：`commands/dev-overnight.md:204` 写明 "Every Bash tool call is a fresh shell"。
- 后果：要么每次重贴 80 行函数，要么状态丢失。这本该是一个持久化状态的脚本。

**8.【④+⑤】commit.md 用 bash 循环表示"派 Agent 修复"**
- 原文：`commands/commit.md:316`、`:334`、`:353` 在 ```bash 块里写 `while …; do route_finding …; done`、`until ARTIFACT_CHAIN=…; do route_finding …; done`。
- 冲突对象：`route_finding` 的含义是"派一个 Agent 去修"（:144–151），shell 循环里发不出 Agent 调用。commit.md 只定义了 `artifact_role`（:100），根本没有定义 `route_finding`（close.md 里叫 `close_route_finding`）。这是伪代码冒充可执行脚本。

**9.【②+⑤】dev-command.md 是 dev.md 的过期分叉**
- 原文：`commands/dev-command.md` 有 705 行与 `commands/dev.md` 逐字相同（difflib 匹配块），其余部分已经漂移。
- 漂移一：`:89` 直接取最新的 spec，没有 dev.md:125–151 的"必须比本会话新"防护。
- 漂移二：`:467` 写 "Verify these 4 dimensions"，而 dev.md:640 是 5 个；`agents/qa.md:98` 甚至专门写了"派活只列 4 个维度就视为过期编排"。

**10.【⑤+③】close.md 里 --force 的语义前后相反**
- 原文：`commands/close.md:79` "`--force` skips nothing (AC11)"。
- 冲突对象：`:115` "Forced-override path: use `$ARGUMENTS` directly … with NO file existence verification"；`:30` "`--force` remains a fallback for work with no do-report"。
- "force 已废弃"在 close.md 重复 13 处，在 commit.md 重复 9 处。

**11.【⑤+③】两个空正文命令说法相反，还指向已搬走的内容**
- 原文：`commands/allow.md:6` "body is not injected because of `disable-model-invocation: true`"。`commands/do.md:6` "the body IS injected into context"。
- 两者都写 "see commands/dev-command.md for the empty-body API-400 lesson"。而 `dev-command.md:69` 已经把这部分移到 `docs/dev/command-development-patterns.md`，这个文件不在仓库里。

**12.【⑤】redev.md 的步骤数和位置过期**
- 原文：`commands/redev.md:9` "same canonical 14-step … TodoList"；`:19` 说 graphify 在 "between Step 1 and Step 2 … between Step 7 and Step 8"。
- 实际：`scripts/todo/dev.py` 有 17 步；graphify 在 dev.md 的 Step 2 和 Step 9。
- dev.md:755 为这个不一致专门写了一段"故意不改编号，别去修"。

**13.【②】Codex 对抗审查段落抄了 12 份**
- 原文：`agents/architect.md:418` "## Codex adversarial consultation (OPT-IN — only when `--codex` flag set)"，共 12 份 707 行（ba.md:1384、qa.md:1317、pm.md:1072、dev.md:966、spec.md:741 等）。
- 这一段只在 `codex_required: true` 时才用。应写成一份共享文件，每个代理只留一行"收到 codex_required 时读它"。

**14.【②+①】cp-state 打点合同抄了 17 份，而登记由钩子自动完成**
- 原文：17 份共 413 行，例如 `agents/ba.md:1344–1383`、`cleaner.md:172`、`test-executor.md:401`。
- 已由谁执行：登记由 `hooks/pretool-cp-checkin.py` 在读 cp-state 文件时自动完成（文件自己也写了 "the pretool-cp-checkin.py hook does this for you"）。写 cp-state 只能经 spec-check.py，pretool-bash-views-guard.py 会拦别的写法。
- 每个代理只需三行：读 cp-state；做完一项用 spec-check.py mark；退出前不留 pending。

**15.【②+③】"不要放弃"等共享块，讲的是能力模型本来就会做的事**
- 原文："Anti-Give-Up Discipline" 6 份 × 29 行（qa.md:28–56、pm.md:74、architect.md:14、product-owner.md:14、ui-specialist.md:23、user.md:14），内容是"至少试 3 种方法""Your job is to find a way, not find an excuse"。
- 同类还有 "Test Data Bootstrap Protocol" 4 份 × 26 行，"Authority Chain" 7 份。

**16.【①】changelog-analyst 的 DO NOT 大半已由 git 钩子执行**
- 原文：`agents/changelog-analyst.md:40–53`。
- 已由钩子执行的条目：#2 "Never run `git push`"、#3 "Never run `git reset --hard`"、#4 删分支和 force-push、#13 auto-bulk 前缀，由 `hooks/pretool-git-privilege-guard.py` 执行（push、hard reset、ref 变更、auto-bulk 白名单）；#10 禁用 sync 类提交主题，由 `pretool-bulk-commit-detector.py` 执行；#14 bulk sentinel，由 `pretool-write-guard.sh` Layer A 和 bash-safety 1.F 执行。
- 应该保留的：#12（命令行纯净，在钩子误报之前就要避开），以及 #9、#15、#16 这类钩子管不到的判断。

**17.【④+③】dev-overnight 的 56 行会话绑定 bash**
- 原文：`commands/dev-overnight.md:206–262`：找 state 文件、绑定根目录、export、调 overnight-init.sh。:204 和 :264 反复强调"必须一次调用，不得拆开"。:236–243 是事故叙述（"Binding to the containing directory is what made Step 1 hard-abort with …"）。
- 改法：`scripts/overnight-init.sh` 已经存在，整段应该收进脚本，提示词只留一行调用和输出键的表。

**18.【③】ba.md 有 44 行自称"不是规则"的语气节**
- 原文：`agents/ba.md:537–580` "Tone, mission, and the 'GitHub-praise' aspiration (tone guidance, NOT mandate)"。中间夹着 `<!-- AC-1.5 meta-prose -->`，说明"本节禁用 MUST 字样"这条规则本身。
- 引用的 `spec-20260503-091826.md` 不在仓库里。整节不改变任何行为。

**19.【③+④】dev.md 的 spec_path 补丁**
- 原文：`commands/dev.md:540–596`，57 行，含 python heredoc、5 行真值表，以及 "task 20260526-053746 AC-01"、"codex iter-2 C3"、"codex iter-3 F1: bare heredoc without inline env vars fails KeyError" 这类开发史。
- 改法：规则一句话就够——"编排者解析出的 spec_path 不为空，就写进 context.json"。实现放进脚本。

**20.【③】dev-overnight 留着未启用的"信封"和多处死引用**
- 原文：`commands/dev-overnight.md:20–52` "Standard Dispatch Envelope"，自述 "NOT yet rewritten to reference this envelope — that compression is deferred to Cycle 2"，所以信封和 15 个以上的完整模板并存。
- 死引用一：`:136` 说规则 1、2、4、5、6 "already covered by ~/.claude/CLAUDE.md"，而现在的 CLAUDE.md 只剩 Production Lessons 11–16，没有这些内容。
- 死引用二：`:1849` 列出 `codex_native_harness.py`，这个文件不存在。

**还可以引用的例子**（同样已核实）
- `agents/style-inspector.md:157–193` 标准 1 "Command and agent files MUST NOT contain inline bash/python code"，`:261` 标准 4 "integer step numbering"。dev.md 有 124 行 bash，close.md 有 146 行；qa.md 用 "Step 10.1–10.5"，dev-overnight 用 "Step 11g"，clean.md 用 "Step 10A"。
- `agents/prompt-inspector.md` 把 `## Philosophy`、`## Overview`、`## Quality Standards`、`## Usage` 列为 "always remove"。clean.md:13、test.md:12、dev-overnight.md:56、dev.md:1417 都有。
- `agents/qa.md:66` "SPEED IS PARAMOUNT … not a perfectionist auditor"，对 `:14–27` "Zero findings on first pass = look again"。
- `commands/push.md:60–110` 讲 push.sh 读令牌的内部实现；`commands/restart.md:20–55` 讲 capability_token 和 `_sweep_superseded` 等钩子内部；`CLAUDE.md:100–103` 的 sentinel-grant 段落讲匹配算法细节，外加"某个钩子文件没注册"的旁白。这些都属于第①、③类。

---

## (c) 写提示词的原则（草案，11 条）

**P1. 钩子已执行的规则不复述，最多留一行指针。**
写法："X 由 `hooks/…` 拦截（exit 2）；被拦时按 Subagent Hook Discipline 处理。"
依据：例 14、16，以及 push.md、restart.md、CLAUDE.md 的分支和 sentinel 段落。
以下五种情况，即使有钩子，规则也要留在提示词里（压到最短）：
1. **钩子要靠模型先行动才能工作。** 例如 FIRST ACTION 读 dev-registry（否则 tool-policy 和 cp-checkin 认不出角色，见 dev-overnight.md:340）；派活时自己构造 `<obligation>` 块；`run_in_background: false` 必须显式传。钩子只会拒绝，不会替模型补上。
2. **钩子触发得太晚、代价太大。** 例如"先把待办标成 in_progress 再派 Agent"：否则子代理调用会记到错的步骤上，直到后面完成步骤时才被 Gate 4 拦住（todo-validate / subagent-track），那时已难修复。
3. **钩子默认只记日志或只警告，或者只查自报字段。** cp-enforce、G1、G4、prompt-purity、layer-escalation、bisect 都是如此；e2e-enforce 只查报告里的 `e2e_enforcement.status` 字段。这时提示词才是真正的规则，必须保留，但不能声称"钩子会拦"（例 1、2）。
4. **钩子会误报，模型需要事先知道怎么避开。** changelog-analyst 的命令行纯净规则 CP-1–4 就是为了绕开 bash-safety 的子串误报，留下但要压缩。
5. **被拦之后该怎么做。** Subagent Hook Discipline 这一条钩子替代不了。

**P2. 提示词描述钩子必须与代码一致，以 `docs/ENFORCEMENT-LEDGER.md` 的 mode/precondition 列为唯一来源。**
每次提到钩子，写清"拦 / 只警告 / 默认关闭、要设某变量才开"。不写"enforced by …"这种笼统说法。
依据：例 1、2、6；dev.md:1152 把只警告的检查叫作 "Layer-escalation gate (mandatory)"；redev.md 写 "All /dev hooks remain active … layer-escalation gate"。

**P3. 每条规则只有一个家，别处只留一行指针。**
会重复出现的段落（codex 审查、cp-state、baseline 章程、anti-give-up、test-data、authority、intake、score 回显、overnight spec 集成、路由表、R15）各写成一个共享文件。只在特定条件下才用的（例如 `codex_required`、有 SPEC_ID 时），由代理按需去读。每次都要用的，只留 1–3 行摘要。
依据：例 9、13、14、15；五个维度同时写在 dev.md:640 和 qa.md:81；close.md 和 commit.md 各写了一套路由表，函数名还不一样。
例外：短而必需的内容（≤3 行）可以内联，但要从同一个来源生成（像 doc-sync 的 AUTO 块那样），以免漂移。

**P4. 变体命令只写差异，不写副本。**
/dev-command、/redev、/dev-overnight 相对 /dev，只写"与 /dev 不同之处"，再加引用。
依据：例 9、12，以及 dev-overnight 与 dev.md 的 110 行模糊重复。
例外：如果变体运行时 /dev 的说明不在上下文里（dev-overnight 每轮续跑是新上下文；redev 自己写了"需要 /dev 仍在上下文"），共享部分要放进两边都读的共享文件，而不是复制一份。

**P5. 机械步骤放进脚本，提示词只写"运行什么、读哪几个输出键、失败了怎么办"。**
凡是 3 步以上、不需要判断的 shell 序列，凡是带循环、状态或真值表的逻辑，都写成带测试的脚本。每个步骤最多用 1–2 次 Bash，才能落在"两次派活之间 5 次 Bash"的限制之内。
依据：例 7、8、17、19，以及 dev.md 的 Step 15、16 的 jq 脚本、changelog-analyst 的 Phase 3–10、spec.md 的 Step 6。
例外：需要模型按情况改写的一行命令（如 `git log --grep <关键词>`）可以留在提示词里。shell 伪代码一律不出现在 ```bash 块里；需要派 Agent 的地方用文字写。

**P6. 派活的固定前缀只定义一次。**
FIRST ACTION、SECOND ACTION、CHECKPOINT、obligation 块、用户需求文档路径，这五项要么定义一次，要么由脚本生成派活片段。每个步骤只写自己特有的部分（角色、产物、模式）。每个角色的 obligation 产物列表用一张表写。
依据：dev.md 有 10 处 FIRST ACTION、8 处 obligation、7 处 CHECKPOINT；dev-overnight.md 是 18、8、11；例 20 的信封写了却没用上。

**P7. 输出格式以 `schemas/*.json` 为准。**
已登记 schema 的报告，提示词只写 schema id 和一个 ≤15 行的最小例子，外加需要判断的字段含义（例如什么算 `primary_cause`）。不再内联 100–240 行 JSON。dev/qa 报告由 artifact-contract 钩子按 schema 校验。
依据：qa.md:1393–1632、ba.md:1016–1203、pm.md:376–517、changelog-analyst 的输出 schema。

**P8. 不写历史，不留死引用。**
任务号、spec 号、AC/R/M/F 标签、"iter-2 C3"、"redev7 cycle could not self-deploy"、"Historically …"，这些写进 commit message、CHANGELOG 或 docs，不写进提示词。提示词引用的每个文件都必须在仓库里存在。
依据：例 11、18、19、20，dev.md:1675，dev.md:1349。dev.md 有 20 处任务号或 spec 号，close.md 有 22 处。
例外：模型确实需要打开的文件（例如要读的 spec），保留存在的路径即可，不写编号的来历。

**P9. 不复述能力模型的默认行为，不写动员演讲。**
"You Are a Perfectionist"、"Find Problems, Not Confirm Success"、语气和使命、"Agent-Flexible Implementation"、Success Metrics、Philosophy 这类内容删掉。只留与默认行为不同、能检验的要求。
依据：例 15、18；dev.md:1440–1617；四个专家代理的 "The Standard" 节。
例外：harness 确实想要偏离默认的倾向时，留一句。例如 QA 的 "A false PASS is worse than a false FAIL"。

**P10. 强调要少用。**
CRITICAL、MANDATORY、NON-NEGOTIABLE、HARD RULE、PARAMOUNT 只用在"违反一次就造成损失、而且没有钩子兜底"的规则上，每个文件最多 3 处。
现状：这五个词共 149 处（qa.md 28、agents/dev.md 18、ba.md 13、dev-overnight.md 11）；算上 MUST、NEVER、ALWAYS，qa.md 有 109 处。强调一多就互相抵消，甚至打架：agents/dev.md:151 和 :153 是两个"PARAMOUNT"；qa.md:66 "速度至上"对 :14–27 "深挖到底"。

**P11. 提示词遵守自家规范，同一个概念只有一个名字、一个数。**
style-inspector 的标准 1（不内联代码）、标准 4（整数步骤编号）和 prompt-inspector 的 "always remove" 列表，也要用来检查 `commands/` 和 `agents/` 本身；做不到就删掉这些规则。
同一事物要统一：步骤数（14 还是 17）、维度数（4 还是 5）、标识（`<timestamp>`、`<task_id>`、`$TASK_ID`、`DEV_SESSION_ID` 在 dev.md 的模板里混用）、函数名（`route_finding` 还是 `close_route_finding`）。
步骤标题要与 `scripts/todo/*.py` 同步（check-todo-md-sync），钩子指回的章节名要保留（见 (a) 末尾）。
依据：例 9、12，以及上面"还可以引用的例子"里的前两条。

---

## (d) 估计的总削减量和可信度

**总量。** 25,436 行中，约 12,500 行（49%）可以删掉或压缩，瘦身后约 12,900 行。
- commands：10,714 行 → 约 5,240 行（−51%）
- agents：14,597 行 → 约 7,590 行（−48%）
- CLAUDE.md：125 行 → 约 77 行

**按类型分。** ① 约 1,000 行（4%），② 约 3,600 行（14%），③ 约 2,070 行（8%），④ 约 2,250 行（9%，这些行搬进脚本，不是凭空消失），⑤ 约 240 行（1%，以改写为主），⑥ 约 3,400 行（13%）。

**净值。** 共享文件要加回约 250–300 行（codex 审查约 60、cp-state 约 25、anti-give-up 约 15、派活信封约 40、baseline 章程约 6、路由和 R15 约 40、schema 指针等）。所以提示词总量的净降幅约 47–48%，即从约 25,400 行降到约 13,200 行。按字符算，长段落压缩得更多，单次加载的上下文降幅会接近或超过 50%。例如 /dev-overnight 每次加载约 146k 字符，可降到约 75–80k。

**可信度。**
- **高：** 第②类中可以直接量出来的部分。dev-command 与 dev 逐字重复 705 行；共享块是按章节量的（codex 707、cp 413、anti-give-up 174、baseline 146、test-data 104、intake 104、overnight spec 144、authority 74、score 45，合计约 1,900 行）。第①、⑤类"有没有、在哪里"也已对照钩子代码和 ledger 核实。
- **中：** 第①、⑤类的具体行数；第④类，因为要先写好并测试脚本，其中部分逻辑可能仍要留作判断说明。agents/dev.md 的 owned-edits 账本是否与 attribution 钩子重复，需要专门核实。
- **中低：** 第③、⑥类，误差约 ±30%。这两类靠判断，而且只有最大的十个文件是深读的，其余文件靠章节测量和抽读。
- **总体：** 降幅区间 40–55%，点估计 48%。不应削减的内容：Subagent Hook Discipline、Long-Running Process Verification、BA 四合同（唯一归属是 ba.md，只去重不删）、QA 的 Anti-Fraud 原则（去重后保留）、producer-question 机制、扇出与车道路由（压缩但不删）、obligation 块和 FIRST ACTION 的要求。
