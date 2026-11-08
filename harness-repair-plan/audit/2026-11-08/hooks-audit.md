# Hook 层审计：重叠、状态耦合、冲突、死钩子，以及合并方案

审计对象：`origin/master` = `2acc29b`（fetch 后，工作区即该提交，干净）。只读；未运行任何钩子、测试或脚本。
行号均为该提交上的 `文件:行`。"阶段覆盖"一栏依据规划分支 `claude/vibrant-hopper-bazrn8` 的
`prompts/short/{P2,P3,P4,P5,P6,P9,P10,P11,P1c}.md` 和 `prompts/P1b.md`（P1b 的"行"= 其 Scope 表的第 N 行，
`A<nn>` = `inventory/artifact-map-d625284.tsv` 的行号）。

---

## 0. 基线事实（先纠正起始地图）

| 事实 | 证据 |
|---|---|
| 81 个注册、80 个不同文件；其中 **79 个在 `hooks/` 下，1 个是 `scripts/canary-verify.sh`**（起始地图说"80 个文件在 hooks/ 下"不准确）。`posttool-allowlist-consume.py` 注册两次（PostToolUse `*` 与 PostToolUseFailure `Bash`）。 | settings.json:299-894 |
| 所有注册都指向存在的文件；注册指向缺失文件的数目 = 0。 | 逐条检查（见第 5 节） |
| `hooks/` 下直接文件 118 个，未注册 39 个（可执行 33 个 + `git-fswatch@.service` + 5 个 md/json）。 | `ls hooks` |
| master 上 **P1b、P1c 都还没合并**（已合并：P0、P0b、P7、P1、P7b、P8）。所以起始地图里"notification-idle-overnight.py（P1b 已把它改成空壳）"在 master 上不成立：它仍是一个活的、只写日志的钩子（notification-idle-overnight.py:1-24, :145）。master 上唯一带 `# STUB:` 的文件是 `hooks/stop-completion-gate.py:2`（未注册）。 | `git log --merges origin/master`；`grep '^# STUB:'` |
| CLI 钩子语义（判断"死/半死"的依据，来自 Claude Code hooks 文档）：exit 0 时 stdout 只在 transcript 模式显示，**只有 UserPromptSubmit 和 SessionStart 的 stdout 进入模型上下文**；exit 0 的 stderr 不给模型；exit 2 的 stderr 给模型（PreToolUse 会拦下工具，PostToolUse 只是反馈，工具已执行）；其它退出码的 stderr 只给用户；**同一事件的多个钩子并行运行**；matcher 只匹配工具名；用户中断时不触发 Stop。 | 规划分支 landscape/D-orphans-dangling.md:232 与 P9 R14 已采用同一判断；P1c X10 打算实测并行 |

---

## 1. 四个论断的结论

| 论断 | 是否成立 | 计数 |
|---|---|---|
| 1. 重叠：多个钩子判定同一事实 | **成立** | 13 组，涉及 56 个注册文件；"报告必须存在/合规"一组就有 16 个判定点 |
| 2. 状态耦合 | **成立** | 盘点 34 个状态/产物文件：多写者 12 个，写了没人读 11 类，读了没人写 6 个，同事件并行读写竞态 3 处 |
| 3. 冲突 | **成立** | 8 个（4 个能挡住合规流程或造成死锁，2 个潜伏、待某开关打开即触发，2 个规则矛盾/错误见证） |
| 4. 死/半死钩子 | **成立** | 注册钩子中：输出到不了模型的 17 个，默认 advisory 的判定 6 处，默认关闭的 opt-in 3 个，触发条件已不可能出现的 5 处，空壳 0 个注册（1 个未注册）；未注册文件 39 个，其中 12 个完全无人引用或只被测试引用 |

---

## 2. 论断 1：重叠（同一事实多处判定）

| # | 被重复判定的事实 | 钩子与各自判定内容（证据） | 阶段覆盖 |
|---|---|---|---|
| O1 | **待办清单是否合法、按序、数量对、该派的子代理已派**（6 个专门钩子 + 4 个附带读者） | pretool-todo-validate.py：前置拦截 6 条规则（每次最多完成 1 步、必须经 in_progress、只 1 个 in_progress、内容不可改、按序、Gate 4 子代理已调用）:43-133, :216-246, :265-305；posttool-todo-sequence.py：**同一套规则 1-5 再判一次**，外加首次清单状态检查，违规写锁 :116-131, :139-171；posttool-todo-count.py：数量 ≥ canonical，不足写锁 :44-60；posttool-todo-tracker.py：数量对才置 `todo_acknowledged=True` 并改写 todos 文件 :100-121；pretool-workflow-gate.py：读锁/确认位，未确认则拦**所有**工具 :1101-1192；prompt-workflow.py：命令起点写清单与书签 :1972-1977、:1980-1996；posttool-subagent-track.py：写 Gate 4 的 `subagent_calls` :245-260；pretool-subagent-enforce.py：按 contract 判当前步骤的派发 :60, :300；posttool-overnight-loop.py：全部完成即重置周期；check-todo-md-sync.py：SessionStart 再比对 todo 脚本与命令文档 :1-14 | P5 R18-R20（validate 成唯一规则引擎，sequence/count 成 stub，删 workflow-gate 的锁分支）；P1b 行 2/E7（删书签改写）；P1c R17（按内容配对）；P2 R3（去掉项目优先查找） |
| O2 | **生产者产物是否存在且合规**（16 个判定点） | G1 pretool-obligation-gate.py：派发提示里 obligation 块的语法/角色/时钟 :135-167（advisory）；G3 pretool-aggregate-check.py：(a) QA 派发前规范汇总 dev-report 必须存在 :636-672（**默认拦截**），(b) 前序 obligation 产物屏障 :558-633（advisory）；G2 subagentstop-artifact-contract-enforce.py：(a) 自身 obligation 声明的产物存在+schema+identity :859-1140（advisory），(b) 旧路径按文件名关联 dev/qa 报告做 schema :1194-1288（**默认拦截**）；G4 stop-obligation-gate.py：主会话停时所有派发 obligation 已兑现 :103-145（advisory）；posttool-overnight-loop.py:262-283 同一 G4 检查第二个落点；posttool-lane-completeness-watch.py：分片齐了写标记并跑聚合器 :126-130, :210-237；subagentstop-e2e-enforce.py：QA 报告存在且 e2e 状态合格 :236-268, :326, :422（拦截）；subagentstop-codex-enforce.py：codex 台账存在 :99（拦截）；subagentstop-cp-enforce.py：cp-state 无 pending（advisory）；posttool-overnight-file-check.py：overnight contract 产物存在/合规 :355-367（exit 2）；posttool-subagent-track.py：同一 contract 产物再用 schema 判一次 :341-355, :403；stop-do-report-gate.py：do-report 存在且终态 :186-243（拦截）；pretool-gitignore-preflight.py：dev-report 声明的交付物未被 gitignore :818（拦截）；stop-spec-coverage-enforce.py（由 coordinator 运行） | P1b 目标 3（只留 G1/G2/G3、链函数、Stop 门）、行 3/6/7/13；P3（一个处置函数，R7、R12-R14、R17）；P4 R8-R10；P5 R11-R12（G4 退役）。**未覆盖**：e2e/codex/cp/overnight-file-check 仍各自成门，没有阶段把它们并进 G2 |
| O3 | **/do 授权是否有效** | 12 个钩子 14 处读同一标志，规则三种：内容必须是 "true"（orchestrator-gate:77, read-size-guard:27, do-block-subagents:74, aggregate-check:647, write-guard.sh:60）；只看存在（block-background-tasks:153, bash-safety.sh:2755, :2797, block-enterworktree.sh:60, block-branch-pr-worktree:589, subagent-enforce:52, bash-safety.sh:914）；**硬编码 /tmp**（git-privilege-guard:275） | P1b 行 9（一个 `has_do_consent`，A51） |
| O4 | **某执行者能否写某路径** | pretool-tool-policy.py（角色前缀，含 Bash 写目标）:1-35；pretool-write-guard.sh（禁止 Write 覆盖已有文件、禁止写批量提交哨兵）:16-31, :155-161；pretool-claude-config-guard.py（.claude/hooks、commands）:1-30；pretool-cp-state-write-guard.py（子代理 Write/Edit cp-state）:1-30；pretool-bash-views-guard.py（Bash 重定向到 views/cp-state/lock）:16-30；pretool-overnight-hook-guard.py（overnight 边界与 harness 自身）:1-14；pretool-subagent-code-block.py（非 dev 写代码，仅告警）:1-9；pretool-bash-safety.sh（Layer 1.E3 写见证、settings 等） | P5 R1-R3 只给 tool-policy 加 D8 拒绝；**合并未覆盖** |
| O5 | **cp-state 谁能写** | 写者：scripts/spec-check.py 与 pretool-cp-checkin.py（在 Read 事件里写，:271-309）；禁止者：cp-state-write-guard（Write/Edit）、bash-views-guard（Bash）、tool-policy（前缀） | P1b 行 8（A48）、P6 R2 部分 |
| O6 | **/spec 访谈是否进行中**（同一谓词抄了两份） | pretool-spec-block-foreground-agent.py:45-62 与 pretool-block-background-tasks.py:79-105（注释自称"MIRRORS ... EXACTLY"） | P1b 行 2 只统一读取来源；**两份谓词未合并** |
| O7 | **能否结束会话/轮次** | stop-workflow-coordinator.py（timelock、coverage、auto-commit、cleanup 四相）:42-73；stop-do-report-gate.py；stop-obligation-gate.py | P5（一个 Stop 门 + launcher） |
| O8 | **overnight 窗口是否仍开** | prompt-workflow.py Phase B 续跑 :1166-1204；posttool-overnight-loop.py :255-300；stop-overnight-timelock.py（coordinator 相）；notification-idle-overnight.py；posttool-overnight-file-check.py 的活跃判断 | P2 R7（一个 `window_open`）、P5 R7(4) |
| O9 | **git 提交/推送权限** | git-privilege-guard（主体）；bash-safety.sh（破坏性 git、批量哨兵）；bulk-commit-detector（同一"批量提交"事实，仅告警）；userprompt-bulk-commit-capability（铸造）；commit-dispatch-attest（见证）；push-analyst-grant-guard（再验 push 授权，与 scripts/execute-push.py 两个验证者）；posttool-push-gate-token-verify（再验 token）；hooks/push.sh（第三次验 token）；block-branch-pr-worktree、block-enterworktree、worktree-guard（三个钩子管 worktree） | P6 R8-R9、P5 R4/R6、P1b 行 11-12：逐个修，**不合并** |
| O10 | **防循环/最小改动**（都用"最新的 context-*.json"猜当前任务） | pretool-layer-escalation-check.sh:9, pretool-bisect-gate.sh:9, pretool-layer-match-gate.sh:10-11, subagent-stop-guard-integrity.sh:15, subagent-stop-diff-check.sh:30（最近 10 分钟的 dev-report） | **无**（P9 R14 只改文字） |
| O11 | **/allow 授权生命周期** | 写：userprompt-consent-allowlist.sh（两条通道都写）；读：lib/allowlist.read_grant（orchestrator-gate、write-guard、aggregate-check、do-block-subagents、subagent-enforce、read-size-guard…）；消费：posttool-allowlist-consume.py；回收：stop-cleanup-allowlist.sh:24-41（coordinator 相） | P1b 行 14（A88） |
| O12 | **子代理是什么角色** | 写：pretool-cp-checkin.py（FIRST ACTION 的 Read 时写 agent-index）:155-190；读：lib/agent_resolver（tool-policy、code-block、overnight-hook-guard、G2、codex、e2e、codex-ledger） | P6 R1-R4（角色来自 CLI） |
| O13 | **tmpfs 压力** | session-tmpfs-banner.sh 与 userprompt-tmpfs-pressure.sh 各跑一次 df 判 75% | **无** |

---

## 3. 论断 2：状态耦合（写者/读者）

标记：**MW** 多写者；**W-R0** 写了没人读；**R-W0** 读了没人写；**RACE** 同一事件并行钩子读写同一文件。

| 状态/产物 | 写者（文件:行） | 读者（文件:行） | 标记 | 阶段覆盖 |
|---|---|---|---|---|
| `.claude/workflow-<sid>.json`（书签） | prompt-workflow.py:1980-1996；pretool-workflow-gate.py:908, :998, :1116；posttool-todo-sequence.py:146, :171；posttool-todo-count.py:50；posttool-todo-tracker.py:120；posttool-subagent-track.py:260 | pretool-todo-validate.py:151；pretool-subagent-enforce.py:60；pretool-spec-block-foreground-agent.py:38；pretool-block-background-tasks.py:91；pretool-workflow-gate.py:1075；posttool-subagent-track.py:73；prompt-workflow.py:1207；stop-spec-coverage-enforce.py:75 | **MW（7 个钩子）+ RACE**：TodoWrite 的 3 个 PostToolUse 并行读改写，tracker 置 True（:117-120），count/sequence 置 False+锁（:46-50, :141-147），sequence 的 `save_state` 回写**加载时的旧对象**（:166-171），可抹掉 count 刚写的锁；workflow-gate.py:1134 注释承认此竞态 | P1b 行 2/E7；P5 R19-R20 |
| `~/.claude/todos/<sid>-agent-<sid>.json` | CLI 本身；prompt-workflow.py:1896, :1975；pretool-workflow-gate.py:901；posttool-todo-tracker.py:110 | spec-block-foreground:28；block-background:97；prompt-workflow Phase B | **MW** | P1b 行 2 |
| `claude-tool-streak-<sid>.json` | pretool-orchestrator-gate.py:120（写）、:237（Agent 清零） | 同文件 :109-115 | **MW**（prompt-workflow.py:2009-2016 另一路径删除） | P1b 行 14（A90） |
| `claude-orchestrator-consent-<sid>.flag` | prompt-workflow.py:1408-1410；删除 :2011 | 见 O3 共 14 处 | 多个判定规则；git-privilege-guard:275 读硬编码 `/tmp`，设置 `CLAUDE_STATE_DIR` 时 **R-W0** | P1b 行 9（A51） |
| `claude-do-task-<sid>.json` | prompt-workflow.py:1419 | stop-do-report-gate.py:187 | **无任何钩子清除**（只有安装脚本 scripts/install/tmp-cleanup-install.sh:159 的定期清理）→ 见冲突 C4 | P5 R7/R21 |
| `docs/dev/do-report-<task>.json` | prompt-workflow.py:1363（骨架）；主代理；**stop-do-report-gate.py:149-165, :217（门自己改写为 blocked）** | stop-do-report-gate.py:198 | **MW（3）** | P1b 行 9（A54）、P5 R21 |
| `claude-{commit,push,merge,stop}-userintent-<sid>.flag` | prompt-workflow.py:1924-1926, :1446 | stop：pretool-wrapper-userintent.py:115；commit：bash-safety.sh:27 与 lib/commit_pipeline.py:148 | push、merge 两个 **W-R0** | P1b 行 14（A89） |
| `claude-bash-allowlist-<sid>.json` + `claude-grants/<task>.json` | userprompt-consent-allowlist.sh（两条通道） | lib/allowlist；消费 posttool-allowlist-consume.py；回收 stop-cleanup-allowlist.sh:26-41 | 一个事实两份文件，**MW** | P1b 行 14（A88） |
| `claude-bulk-commit-sentinel-<sid>-<nonce>.json` | userprompt-bulk-commit-capability.py（经 scripts/write-bulk-commit-sentinel.py） | git-privilege-guard、bash-safety.sh；回收 stop-cleanup-allowlist.sh:48-62（硬编码 /tmp）；write-guard.sh:16-31 禁写 | 路径硬编码 /tmp 与 state-dir 不一致 | P1b 行 11（A65） |
| `claude-commit-dispatch-<sid>-<nonce>.json` | pretool-commit-dispatch-attest.py:96-103 | git-privilege-guard | **见证可能失真**：与其它 PreToolUse:Agent 钩子并行，被别的钩子拒绝的派发也会留下见证（冲突 C7） | P1b 行 11（A64）只管多写者 |
| `.claude/dev-registry/agent-index.json` | pretool-cp-checkin.py:167-189（Read 事件的副作用） | lib/agent_resolver 的 7 个调用者 | 注册依赖子代理"先读一个文件"；跳过则所有按角色的门都放行 | P6 R1-R2 |
| `.claude/specs/<id>/cp-state-*.json` | scripts/spec-check.py；pretool-cp-checkin.py:271-309 | cp-enforce、cp-checkin | **MW** | P1b 行 8（A48） |
| `.claude/dev-registry/<reg>/{e2e,codex,artifact-contract}-enforce.json` | scripts/write-enforce-flag.sh | e2e-enforce:368-381；codex-enforce；G2 | 三个门三份读法 | P1b 行 1（A05） |
| `.claude/dev-registry/<reg>/codex-ledger/<aid>.json` | posttool-codex-skill-ledger.py | subagentstop-codex-enforce.py | — | P6 R4 |
| `claude-close-force-<sid>.flag` | **无**（`/close --force` 已是 no-op，commands/close.md:3, :24） | subagentstop-e2e-enforce.py:384-393；G2 :365-375 | **R-W0** | P1b 行 10（A61）、P4 R4 |
| `.claude/dev-registry/dev-<task>/aggregate-pending.json` | posttool-lane-completeness-watch.py:126-130 | 无（全仓 grep 只有写者与文档） | **W-R0** | P2 R4 / P1b E5 |
| 产物门 advisory 日志 `~/.claude/logs/*.jsonl` | G1 :100；G2 :146；G3 :547；G4 stop-obligation-gate.py:56 **与** posttool-overnight-loop.py:28（同一文件两个写者）；do-report-gate :58；lane-watch :94；cp-enforce :31-36 | 无 | **W-R0（7 个文件）**，其中一个 **MW** | P1b E12、P4 R9、P5 R11 |
| `overnight-idle.jsonl` / `overnight-self-repair.jsonl` | notification-idle-overnight.py:145；pretool-overnight-hook-guard.py:60 | 无 | **W-R0** | P1b 行 13（A86） |
| `docs/dev/journal-view-<task>.json` | G2 :451-466 | 无 | **W-R0** | P1b（P10 R19 核对） |
| G2 `deferred-checks/<agent>.json` | G2 :691 | 无 | **W-R0** | P3 R7 |
| `contract-bookmark-<sid>-<cycle>.json` | pretool-subagent-enforce.py:138 | posttool-overnight-file-check.py:156；posttool-subagent-track.py:293 | 两个读者各自判 | P1b 行 13（A78） |
| `artifact-status-<sid>-<cycle>.json` | posttool-overnight-file-check.py:161, :316-330 | posttool-subagent-track.py:298, :358-368, :403 | **RACE**：写者和读者都是 PostToolUse:Agent，并行运行；文件按 sid+cycle 而非按调用键，读者可能读到上一次调用的状态 | P1b 行 13（A79，删重判与 sidecar）、P1c X10 |
| `.claude/overnight-state-<sid>.json` | prompt-workflow.py:555（create）；posttool-overnight-loop.py:106, :136, :150；scripts | timelock、notification-idle、prompt-workflow、overnight-hook-guard、file-check | **MW** | P1b 行 13/E13、P2 R11 |
| `.claude/agent-bookmark-<sid>.json` | 无 | posttool-overnight-trace.py:394 | **R-W0** | P1b 行 18（A117） |
| 产品仓库 `INDEX.md`/`README.md` | posttool-doc-sync.py（doc_sync 模块）；userprompt-doc-sync-check.py（会再生/删除，见规划 D-orphans:174） | 人 | **MW** | P1b 行 17（A108） |
| push-gate token `/tmp/agentic-commit/push/...` | changelog-analyst（Write） | hooks/push.sh；posttool-push-gate-token-verify.py（**不一致就改名隔离**，即钩子改写产物） | 两个验证者 + 一个改写者 | P1b 行 11、P10 R3（成 stub） |
| 环境变量 `TOOL_INPUT` | **无**（CLI 只经 stdin 传输入） | posttool-git-checkpoint.sh:16-17 | **R-W0**，worktree 分支是死代码 | **无** |
| `.claude/.hook-refactor-allow` | 只能人手建（设计如此） | pretool-claude-config-guard.py | R-W0（有意） | — |
| 私有缓存/锁（worktree-guard-cache、guard-integrity.lock、do-report-gate 计数、pressure-warn、doc-sync cache、scratch `.owner`） | 各自写者 | 各自写者或配对钩子（sessionend-scratch-sweep 读 `.owner`） | 无违规 | — |

---

## 4. 论断 3：冲突（能挡住合规流程的规则碰撞）

### C1 连续 Bash 上限 5 次 vs 命令自身的步骤（已知案例的推广）
- 规则：pretool-orchestrator-gate.py:64（`BASH_MAX_CONSECUTIVE = 5`）、:180-187（第 6 次拦）、:223-237（只有 Agent 派发清零）；prompt-workflow.py:1999-2016 只在新的用户提示时清零。
- 触发序列 A（/dev）：用户输入 `/dev …` → 首个子代理派发在 commands/dev.md:496 之前，主代理要跑 5 段必做 Bash（dev.md:127 自动找 spec、:157 解析 spec 产物、:224 cp-state 传播、:243 graphify-query、:253 graphify 自动初始化），会话压缩后还要加 :198 的兜底初始化 → **第 6 次 Bash 被拦**，BA 还没派出去；任何一次额外的只读探查也会提前撞线。
- 触发序列 B（/close）：首个派发在 close.md:553，之前有 6 段 Bash（:64, :161, :334, :446, :474, :506，其中 :64、:474 有条件）。
- 触发序列 C（已知）：/restart 的恢复步骤。
- 阶段：**P1c R18**（"the 5-Bash streak vs dev.md Steps 14-17 and recovery steps"）。

### C2 worktree-guard 自锁：拦下所有工具，包括清理它要求的命令（新发现，**无阶段覆盖**）
- 规则：pretool-worktree-guard.sh 注册在 PreToolUse 全部工具（settings.json:550，无 matcher），没有 /do、/allow、子代理豁免；只要存在路径含 `worktrees/agent-` 且落后主分支的 worktree，就 exit 2（:46-66, :73-79），并要求执行 `git worktree remove <path> --force && git branch -D <branch>`（:75）。
- 触发序列：一个带 worktree 隔离的子代理结束后留下 `.claude/worktrees/agent-xxx`（CLI 会保留有改动的 worktree）→ 主分支再有任何一次提交 → 此后该仓库内**任何会话的任何工具调用**都被拦；执行修复命令本身是一次 Bash 调用，同样被本钩子拦；即便放过，`git branch -D` 还会被 pretool-bash-safety.sh:2324 拦。只能由人在 Claude 之外手工清理。
- 阶段：规划分支 reports/problems.md 的 X36 写着 "Fixed in: P1 PR-0"，但 master 上该文件最后一次修改早于 P1（`git log -- hooks/pretool-worktree-guard.sh` 最新为 2d78e4c1），**问题仍在，且 P2-P11、P1b、P1c 均未提及此文件**。

### C3 do-report 门按"会话"而非按"命令"生效，跨命令阻塞并改写 /do 的产物
- 规则：prompt-workflow.py:1419 写 `claude-do-task-<sid>.json`，没有任何钩子删除它；stop-do-report-gate.py:186-243 只要该文件存在就检查 do-report；`MAX_BLOCKS = 2`（:57）后**门自己把报告从 pending 改成 blocked**（:149-165, :217）。
- 触发序列：用户 `/do X` → 主代理工作中用户按 Esc 中断（用户中断不触发 Stop，报告停在 pending）→ 用户输入 `/dev Y` → /dev 这一轮合规结束时，Stop 被 do-report 门拦两次，要求编辑一个与当前命令无关的 /do 产物（此时 /do 授权已在 prompt-workflow.py:2009-2016 被清除，主代理改它还要占用编排门每轮一次的 Edit 额度，且违背 D8"只由生产者写自己的产物"）→ 第三次放行时门把 /do 报告改写为 blocked。
- 阶段：**P5**（R7 按命令区间的单一 Stop 门；R21 do-report 枚举改为 `[pending, completed]`；P5-d 之后 do-report 门退役）。

### C4 TodoWrite 后三个并行 PostToolUse 钩子争写书签，锁是否生效取决于完成顺序
- 规则与证据见第 3 节书签行（tracker :117-120、count :46-50、sequence :141-147/:166-171；workflow-gate :1134 自认竞态）。
- 触发序列：主代理提交步数不足的 TodoWrite（长度变化）→ count 写 `lock_reason=count_mismatch` 并告诉模型"其它工具已全部被锁"（:52-59）→ sequence 走 `handle_length_mismatch`，回写加载时的旧书签（无锁）→ 若 sequence 后完成，锁消失，workflow-gate 放行所有工具；顺序相反则锁住。同一输入两种结果。合规流程本身不受阻，但门的判决不确定，回放测试若按顺序执行钩子（P1b.md:740 记录"the replays ran them in sequence"）看不到这个问题。
- 阶段：P1b 行 2/E7（删除这些改写）、P5 R19-R20、P1c X10（并行 vs 顺序对比）。

### C5 tool-policy 拒绝 changelog-analyst 文档要求的写入（潜伏）
- 规则：policies/tool-policy.v1.json 的 changelog-analyst 行只允许 `/dev/null`、自己的 scratch、`.claude/scratch/`，而它的 rationale 写着"writes push-gate token to /tmp/agentic-commit/push/"；lib/policy_registry.py:272-274 对列表外路径一律拒绝。
- 触发序列：changelog-analyst 按 agents/changelog-analyst.md:68-71（Rule CP-1：用 Write 写 `/tmp/commit-msg-<unique>.txt`）和 :1221-1228（用 Write 写 push-gate token）执行 → 一旦其角色可解析（完成 FIRST ACTION 注册，或 P6 改为从 CLI 取角色），这两次 Write 都被 pretool-tool-policy.py 拒绝；而 posttool-push-gate-token-verify.py（matcher `Write`）和 hooks/push.sh 正依赖这次写入。今天没触发，只是因为该角色在 master 上从不注册（"不合规反而通过"）。
- 阶段：**P6 R9**（明确列出这三个写入并要求修正该行）。

### C6 /spec 访谈期间两个钩子合起来只剩三种可派发的子代理
- 规则：pretool-spec-block-foreground-agent.py:63-97 拦前台派发（只豁免 `spec`、`qa`）；pretool-block-background-tasks.py:183-205 拦后台派发（只豁免后台 `Explore`）。
- 触发序列：/spec 进行中派发任何其它类型（如 graphify、test-writer，或模板里没写 `subagent_type` 的 spec 子代理——commands/spec.md:299-313 的模板就没写），前台被前者拦，后台被后者拦。两份"访谈进行中"谓词手工保持一致（block-background-tasks.py:60-63 注释），任何一份改动都会让两个门对窗口判断不一致。
- 阶段：P1b 行 2 统一其读取来源；**两门合一未被任何阶段覆盖**。

### C7 commit-dispatch-attest 在并行事件里"见证"了没有发生的派发（规则矛盾）
- 规则：pretool-commit-dispatch-attest.py:66-103 在 PreToolUse:Agent 上只要 `subagent_type == changelog-analyst` 就写见证；其文档称"an artifact it writes exists only because a dispatch really happened"（:9-12）。同一事件的其它钩子（block-background 在缺 `run_in_background:false` 时、G3、gitignore-preflight、do-block-subagents、将来武装的 G1）可能拒绝这次派发。
- 触发序列：主代理派发 changelog-analyst 时忘了 `run_in_background:false` → block-background-tasks.py:212-219 拒绝；attest 已并行写下见证 → 磁盘上留下一个从未发生的派发的见证；修正后再派一次又写一个。消费端要求子代理以自身身份认领（隐患有限），但"见证 = 真实派发"这一前提不成立。
- 阶段：**无阶段点名**（P1b 行 11 只处理 A64 的多写者）。

### C8 G1 要求 /do 区间里的生产者派发带 obligation 块，而另一个钩子禁止 /do 派发任何子代理
- 规则：pretool-obligation-gate.py:88-90 把 `do` 列入必须带块的区间；pretool-do-block-subagents.py:74-121 在 /do 授权期间拒绝主代理的所有 Agent 派发（除非 /allow Agent）。
- 后果：今天 G1 是 advisory，只是一条死规则；P2 武装 G1 后，经 `/allow` 放行的 /do 派发会被 G1 再拦一次，而 /do 的模板不产生 obligation 块。
- 阶段：**无阶段点名**（P1b.md:515 只说"/do itself dispatches nothing"）。

另：P1c R18 已列出若干"文字 vs 钩子"冲突（spec-update.md 的 Write 覆盖 vs write-guard、/dev-command 写命令文件 vs claude-config-guard、Gate 4 vs graphify 跳过等），本报告不重复。

---

## 5. 论断 4：死或半死的钩子

### 5.1 输出到不了模型（注册着、在运行、但模型看不到）— 17 个
| 钩子 | 原因（证据） | 阶段 |
|---|---|---|
| pretool-layer-escalation-check.sh、pretool-bisect-gate.sh、pretool-layer-match-gate.sh、subagent-stop-guard-integrity.sh、subagent-stop-diff-check.sh | 只写 stderr 后 exit 0（各文件末行 `exit 0`；diff-check.sh:4-6 自称"visible to orchestrator"，不成立） | P9 R14：**保持注册、只改文字**，即无阶段让它们生效 |
| pretool-quality-gate.py | `_grandfather_or_block` 恒返回 0（:346-360），docstring 仍写"Blocks" | P9 R14/R15（只改文字） |
| pretool-orchestrator-prompt-purity.py | "warn-only — never blocks"（:21-23），而 CLAUDE.md 称其为 Enforcement | P9 R14 |
| pretool-subagent-code-block.py | 已降级为告警（:1-9） | P9 R14 |
| pretool-bulk-commit-detector.py | `_emit_bulk_block` 实为"exit 0 (warn-only)"（:134-147），docstring 仍写 exit 2 | P9 R14 |
| posttool-git-warn.sh | 见 5.3（不会触发） | P9 R14 |
| session-info.sh、session-tmpfs-banner.sh | SessionStart 本可用 stdout 进上下文，却全部写 stderr（session-info.sh:2-12；banner :30-35） | P9 R14 |
| session-git-init.sh | 见 5.2 | P9 R14 |
| posttool-todo-tracker.py | 进度清单印到 stdout（:128），PostToolUse exit 0 的 stdout 不进上下文；docstring 却说"injected into Claude's context"（:6-8） | **无**（P5 R19 保留它） |
| posttool-overnight-loop.py | 续跑指令印到 stdout（:225-240, :110-111），模型看不到；只有 cycle 计数写盘有效 | **无**（P4 R10 只删其中 G4 检查） |
| posttool-command-frontmatter-validate.py | 打印 "BLOCKED" 后 exit 1（:76-80）：stderr 只给用户，模型不知道命令文件坏了 | P9 R15（只改文字） |
| posttool-push-gate-token-verify.py | 不一致时改名隔离 token 后 exit 1（docstring :24-25）：效果真实，但 changelog-analyst 不知道，会照常报告成功 | P1b 行 11 / P10 R3（成 stub） |

### 5.2 默认只记日志（advisory）或默认关闭
- advisory 默认：G1 `CLAUDE_OBLIGATION_GATE`（pretool-obligation-gate.py:79, :176）；G2 obligation 路径 `CLAUDE_OBLIGATION_STOPGATE`（G2 :859）；G3 屏障 `CLAUDE_OBLIGATION_BARRIER`（aggregate-check :386, :568）；G4 `CLAUDE_OBLIGATION_TERMINAL`（stop-obligation-gate.py:104）及其第二落点 posttool-overnight-loop.py:275；subagentstop-cp-enforce.py `CP_ENFORCE_MODE`（:3-7）。settings.json 的 env 里没有任何一个被设为 block。→ P1b 武装 G2、P2 武装 G1/G3、P5 退役 G4；cp-enforce 由 P9 R8/E4 处理。
- 默认关闭：session-git-init.sh（`CLAUDE_SESSION_GIT_INIT` 无人设置，:10-13）；session-promote-hook.sh（需要 `SESSION_PROMOTE_BIN`，:103-105，作者机器专用）；posttool-git-warn.sh（`GIT_WARN_UNTRACKED != 1` 即退出）。
- 只记日志：notification-idle-overnight.py（Notification 不能拦，日志无人读）。

### 5.3 触发条件已不可能出现 — 5 处
1. **posttool-git-warn.sh**：matcher `Bash\(git commit.*\)`（settings.json:721）是对工具名的正则，工具名只是 `Bash`，永不匹配；即便触发，默认关闭，且建议的 `git commit --amend` 会被 git 守卫拒绝。三重死亡。（P9 R14 只记"never runs, for P10"；P10 D15 不注销任何钩子 → 实际无人处理）
2. **posttool-git-checkpoint.sh:14-27** 读环境变量 `TOOL_INPUT`，CLI 从不设置 → worktree 检测分支是死代码，快照永远针对 cwd 仓库。（**无阶段**；P5 R16 只改阈值路径的输出）
3. **subagent-stop-diff-check.sh:16-19** 用 `HEAD~5..HEAD` 统计"子代理可能已被自动检查点提交的改动"；但检查点已改为写 `refs/checkpoints/<branch>`、从不移动 HEAD（posttool-git-checkpoint.sh:2-4, lib/checkpoint-core.sh:6）→ 每次任何子代理停止都把用户最近 5 个真实提交算进去。（**无阶段**）
4. **强制关闭标志读者**：e2e-enforce.py:384-393、G2 :365-375 读 `claude-close-force-<sid>.flag`，`/close --force` 已是 no-op、无人写入。（P1b 行 10、P4 R4）
5. **G1 的 `do` 区间**（见 C8）。（**无阶段**）

### 5.4 空壳
- 注册的空壳：0。未注册空壳：`hooks/stop-completion-gate.py`（`# STUB:` :2，P10 删除）。P5 R11/R19 将把 stop-overnight-timelock.py、stop-obligation-gate.py、posttool-todo-sequence.py、posttool-todo-count.py 变成空壳。

### 5.5 `hooks/` 下没有注册的文件（39 个）
| 类别 | 文件 | 阶段 |
|---|---|---|
| 由注册钩子调用（Stop coordinator 的相，stop-workflow-coordinator.py:65-73） | stop-overnight-timelock.py、stop-spec-coverage-enforce.py、auto-commit.sh、**stop-cleanup-allowlist.sh** | 注意：CLAUDE.md 说 stop-cleanup-allowlist.sh "未注册所以不会在会话结束时回收"，与代码不符——它作为 cleanup 相在**每次** Stop（每轮结束）运行（coordinator :72）。属文字问题，交 P9 |
| 命令/代理/脚本调用的工具 | push.sh、pull.sh、merge.sh、stop.sh、checkpoint.sh、capability-canary.py | 活 |
| 安装器 | install.sh、install-auto-sync.sh、install-git-hooks.sh、install-protection-all.sh | P10 D1 保留 |
| fswatch 功能 | fswatch-manager.sh、git-fswatch.sh、git-fswatch@.service、start-fswatch-all.sh、protection-status.sh | P10 R4 删 protection-status.sh（但被安装器引用，P10 自己也注明需判断） |
| 只在覆盖层/安装 profile 里 | userprompt-usage-snapshot.py（settings.machine.example.json）、pretool-capability-gate.py（scripts/install/profiles/core.json:21-23） | 按 profile 活 |
| 空壳 | stop-completion-gate.py | P10 |
| 只有测试引用 | pretool-baseline-snapshot-preflight.py、pretool-overwrite-guard.py、sessionstart-artifact-census.py | P10 R4 |
| 无人引用（或只在 README/INDEX 里） | audit-slashcommand.sh、hook-todo-injection.py、post_tool_use.sh、pre_slashcommand_validate.sh、pre_tool_use_safety.sh、session_start.sh、post-commit-warn.sh、pre-commit-check.sh、sentinel-lint.sh | P10 R4 覆盖前 7 个；**pre-commit-check.sh、sentinel-lint.sh 无阶段点名** |
| 文档/模板 | INDEX.md、QUICKSTART.md、README.md、README-TODO-INJECTION.md、project-settings-template.json | P10 R4 删后两个 |

---

## 6. 最重要的五个发现，以及哪些没有阶段覆盖

1. **worktree-guard 自锁（C2）**——一个落后的 agent worktree 就让仓库内所有会话的所有工具调用都被拦，修复命令本身也被拦。规划记录（X36）误标为 P1 已修。**无阶段覆盖。**
2. **13+4 个"告警"钩子的输出到不了模型（5.1）**——"防循环八机制"中的 5 个、质量门、prompt purity、批量提交检测、todo 进度、overnight 续跑指令都在运行却没有效果；P9 只把文字改成"它只告警"，P10 不注销。**这些教训目前没有任何执法，且没有阶段让它们生效。**（todo-tracker、overnight-loop、frontmatter-validate 三者连文字层面都未覆盖）
3. **"产物存在/合规"有 16 个判定点（O2）**——G1-G4 之外，e2e、codex、cp、overnight-file-check、subagent-track、do-report、gitignore-preflight、lane-watch 各有一套规则；P1b/P3/P4/P5 收敛了 G1-G4 与 Stop，但 **e2e/codex/cp/overnight-file-check 并入一个生产者停止门不在任何阶段内**。
4. **同一事件并行钩子共享可变状态（C4、artifact-status 竞态、C7）**——书签 7 个写者、sidecar 读写同事件、见证先于判决；回放测试按顺序跑钩子会掩盖这些问题。P1b/P5 删除写者能消掉前两个；**C7 无阶段点名**；P1c X10 的并行实验是唯一能证明修复的地方。
5. **do-report 门跨命令阻塞并改写 /do 产物（C3）与 Bash 上限撞命令步骤（C1）**——都能挡住合规流程；分别由 P5 和 P1c R18 覆盖。

**无阶段覆盖的完整清单**：C2 worktree-guard 自锁；C7 见证先于判决；C8 G1 的 `do` 区间；C6 两份 /spec 谓词的合并；O4 七个写入守卫的合并；O10 防循环钩子"取最新 context"的错位关联与不可见输出；O13 tmpfs 双检；posttool-todo-tracker / posttool-overnight-loop 输出不可见；posttool-git-checkpoint 的 `TOOL_INPUT` 死分支；diff-check 的 `HEAD~5` 前提失效；posttool-git-warn 实际无人处理；pre-commit-check.sh、sentinel-lint.sh 两个无引用文件。

---

## 7. 合并方案：保留全部教训的目标钩子集

### 7.1 目标结构（按事件，每个文件一个进程、内部按规则函数顺序执行）

| 目标文件 | 事件 / matcher | 内容 |
|---|---|---|
| T1 session-start.py | SessionStart | scratch 初始化、gitignore 传播、tmpfs 横幅（stdout）、可选 git init / promote、调用 scripts/canary-verify.sh |
| T2 prompt-workflow.py（保留） | UserPromptSubmit | 命令起点的唯一生产者：任务 id、书签、清单、/do 授权、userintent、overnight 状态 |
| T3 userprompt-gate.py | UserPromptSubmit | 人类意图铸造：/allow、批量提交能力、/restart 授权；附带 doc-sync 与 tmpfs 提示（additionalContext） |
| T4 pretool-orchestrator-gate.py（扩展） | PreToolUse `*` | 主代理工具预算、读大小、后台 Bash/SendMessage/Workflow、清单已开始检查、陈旧 worktree（修复自锁） |
| T5 pretool-dispatch-gate.py | PreToolUse `Agent|Task` | 后台 Agent、/do 禁派、/spec 窗口（一个谓词）、overnight contract、G1、G3、gitignore 预检、层级/二分输入检查、prompt purity；**全部放行后**才写 changelog-analyst 见证 |
| T6 pretool-write-gate.py | PreToolUse `Write|Edit|MultiEdit|NotebookEdit|Bash` | 角色策略（tool-policy 为核心）、覆盖写、配置目录、cp-state、views/锁、overnight 边界；写入归因（只观察） |
| T7 pretool-bash-safety.sh（保留原样） | PreToolUse `Bash` | 破坏性命令层 |
| T8 pretool-bash-guard.py | PreToolUse `Bash|EnterWorktree` | git 权限（主体）、push 授权再验、分支/PR/worktree、EnterWorktree、/stop 包装器意图、grep 回溯、批量提交形状规则 |
| T9 pretool-todo-validate.py（扩展） | PreToolUse `TodoWrite` | 唯一清单规则引擎（吸收 sequence、count、Gate 4，P5 R18） |
| T10 pretool-cp-checkin.py（临时保留） | PreToolUse `Read` | 角色注册；P6 让角色来自 CLI 后删除 |
| T11 runcode-watchdog.py | Pre+PostToolUse `mcp__playwright__browser_run_code` | 两个 watchdog 合为一个文件、两次注册 |
| T12 posttool-allowlist-consume.py（保留） | PostToolUse `*`、PostToolUseFailure `Bash` | 授权唯一消费者 |
| T13 posttool-observe.py | PostToolUse `Write|Edit|MultiEdit|NotebookEdit|Bash|Skill` | 归因、检查点、doc-sync（唯一 INDEX 写者）、命令 frontmatter（改为模型可见）、分片汇总（聚合报告唯一生产者，P2 R4）、push token 校验（改为模型可见）、codex 台账、质量指标（additionalContext） |
| T14 posttool-todo.py | PostToolUse `TodoWrite` | 进度与 overnight 周期计数，经 additionalContext 输出 |
| T15 posttool-dispatch.py | PostToolUse `Agent|SendMessage` | 子代理记录、overnight 产物检查（与记录顺序执行，消除 sidecar 竞态）、overnight trace、/restart 派发记录 |
| T16 subagentstop-producer-gate.py | SubagentStop | G2 为核心；e2e、codex、cp、层级匹配、守卫完整性、最小改动作为**按自身 obligation 关联**的检查函数；/restart 响应记录（只观察） |
| T17 stop-launch.py → stop-command-gate（P5） | Stop | 单一 Stop 门 + coordinator 相（timelock、coverage、auto-commit、cleanup）+ /do 谓词 |
| T18 sessionend-scratch-sweep.sh（保留） | SessionEnd | — |

**估计钩子数：18 个注册文件、约 22 个注册（P6 落地删 T10 后 17 个）**；对比现在的 80 个文件、81 个注册。scripts/canary-verify.sh 与 coordinator 的相脚本仍是被调用的脚本，不再算注册钩子。迁移期间遵守 P5/P10 的规则：被合并掉的旧文件先成为带 `# STUB:` 的 exit-0 文件，旧会话加载的旧钩子列表不会因缺文件而被 exit 2 卡住。

### 7.2 80 个文件的去向

| # | 当前文件 | 去向 | 理由 |
|---|---|---|---|
| 1 | session-info.sh | 并入 T1（改 stdout）或删除 | stderr 不可见 |
| 2 | session-git-init.sh | T1 的 opt-in 函数 | 默认关闭，保留开关 |
| 3 | session-scratch-init.sh | T1 函数 | 与 T18 配对 |
| 4 | check-todo-md-sync.py | 改成 CI 测试（tests/），不再是钩子 | 漂移是仓库属性；且读 `HOME/.claude` 而非 harness 根（:28-29） |
| 5 | session-promote-hook.sh | T1 可选函数 | 作者环境专用 |
| 6 | scripts/canary-verify.sh | 保留为脚本，由 T1 调用 | 教训"harness 已坏却没人发现" |
| 7 | session-tmpfs-banner.sh | T1 函数，与 #13 共用一个 df 函数 | O13 |
| 8 | session-gitignore-propagate.sh | T1 函数 | — |
| 9 | prompt-workflow.py | 保留（T2） | 命令起点唯一生产者 |
| 10 | userprompt-doc-sync-check.py | T3 函数，INDEX 写入交给 T13 的唯一写者 | A108 多写者 |
| 11 | userprompt-restart-authorize.py | T3 函数 | 授权只能来自人类提示 |
| 12 | userprompt-consent-allowlist.sh | T3 函数（只写结构化哨兵一条通道） | A88 |
| 13 | userprompt-tmpfs-pressure.sh | T3 函数（共享 df） | O13 |
| 14 | userprompt-bulk-commit-capability.py | T3 函数 | 能力由可信代码铸造 |
| 15 | pretool-orchestrator-gate.py | 保留并扩展为 T4 | 核心编排纪律 |
| 16 | pretool-block-background-tasks.py | 拆入 T4（Bash/SendMessage/Workflow）与 T5（Agent/Task） | 两个事实分属两个门 |
| 17 | pretool-do-block-subagents.py | T5 函数 | — |
| 18 | pretool-read-size-guard.py | T4 函数 | — |
| 19 | pretool-workflow-gate.py | T4 函数（P5 R20 删锁分支后） | O1 |
| 20 | pretool-subagent-enforce.py | T5 函数 | overnight contract |
| 21 | pretool-bash-safety.sh | 保留原样（T7） | 2892 行 shell 分层规则，移植风险大于收益 |
| 22 | pretool-bash-views-guard.py | T6 函数（经 bash_write_targets） | O4/O5 |
| 23 | pretool-wrapper-userintent.py | T8 函数 | — |
| 24 | pretool-grep-backtrack-guard.py | T8 函数 | — |
| 25 | pretool-cp-checkin.py | 暂保留（T10），P6 后删除 | 角色来源迁到 CLI |
| 26 | pretool-overnight-hook-guard.py | T6 函数 | overnight 写边界 |
| 27 | pretool-quality-gate.py | T13 函数，改 additionalContext 输出 | 当前不可见 |
| 28 | pretool-tool-policy.py | T6 核心 | 角色策略单一来源 |
| 29 | pretool-cp-state-write-guard.py | T6 中的一条策略 | O5 |
| 30 | pretool-attribution-pre.py | T6 中的观察函数（永不拦） | 与 #55 配对 |
| 31 | pretool-subagent-code-block.py | 删除（成 stub） | tool-policy 已覆盖，自身只告警 |
| 32 | pretool-todo-validate.py | 保留并扩展为 T9 | O1 唯一规则引擎 |
| 33 | pretool-block-enterworktree.sh | T8 函数（matcher 加 EnterWorktree） | — |
| 34 | pretool-block-branch-pr-worktree.py | T8 函数 | — |
| 35 | pretool-worktree-guard.sh | T4 函数，**修自锁**：只提示，或放行清理命令 | C2 |
| 36 | pretool-write-guard.sh | T6 函数 | — |
| 37 | pretool-layer-escalation-check.sh | T5 函数：dev 派发前检查本任务（按 obligation 关联）的层级 | 现在不可见且取"最新 context" |
| 38 | pretool-bisect-gate.sh | T5 函数（同上） | 同上 |
| 39 | pretool-spec-block-foreground-agent.py | T5 函数，与 #16 共用一个 /spec 窗口谓词 | O6/C6 |
| 40 | pretool-orchestrator-prompt-purity.py | T5 函数（是否改为拦截由主人决定） | 当前不可见 |
| 41 | pretool-aggregate-check.py | T5 函数（G3） | — |
| 42 | pretool-gitignore-preflight.py | T5 函数 | — |
| 43 | pretool-obligation-gate.py | T5 函数（G1），去掉 `do` 区间 | C8 |
| 44 | pretool-commit-dispatch-attest.py | T5 最后一步：所有拒绝规则通过后才写见证 | C7 |
| 45 | pretool-runcode-watchdog.py | 并入 T11 | — |
| 46 | pretool-claude-config-guard.py | T6 函数 | — |
| 47 | pretool-bulk-commit-detector.py | T8 中 git 权限的一条规则（或删除） | 当前不可见 |
| 48 | pretool-git-privilege-guard.py | T8 核心 | — |
| 49 | pretool-push-analyst-grant-guard.py | T8 函数 | — |
| 50 | posttool-allowlist-consume.py | 保留（T12） | 唯一消费者 |
| 51 | posttool-todo-tracker.py | T14 函数（additionalContext） | 当前不可见 |
| 52 | posttool-todo-count.py | 并入 T9（P5 R19 成 stub） | O1 |
| 53 | posttool-todo-sequence.py | 并入 T9（P5 R19 成 stub） | O1 |
| 54 | posttool-overnight-loop.py | T14 函数（additionalContext；G4 检查删，P4 R10） | 当前不可见 |
| 55 | posttool-attribution-post.py | T13 函数 | — |
| 56 | posttool-git-checkpoint.sh | T13 调用的相脚本（改读 stdin，删 `TOOL_INPUT`） | 5.3-2 |
| 57 | posttool-doc-sync.py | T13 函数（唯一 INDEX 写者） | A108 |
| 58 | posttool-command-frontmatter-validate.py | T13 函数（改 exit 2/decision 让模型可见） | 5.1 |
| 59 | posttool-lane-completeness-watch.py | T13 函数（聚合报告唯一生产者；删 aggregate-pending） | P2 R4 |
| 60 | posttool-push-gate-token-verify.py | T13 函数（改为模型可见） | 5.1 |
| 61 | posttool-git-warn.sh | 删除（成 stub） | 永不触发 |
| 62 | posttool-overnight-file-check.py | T15 函数（与 #63 顺序执行） | sidecar 竞态 |
| 63 | posttool-subagent-track.py | T15 函数 | — |
| 64 | posttool-overnight-trace.py | T15 函数（删 agent-bookmark 读分支） | A117 |
| 65 | posttool-restart-sendmessage.py | T15 函数（matcher 加 SendMessage） | 薄封装，逻辑在 lib/subagent_restart |
| 66 | posttool-runcode-watchdog.py | 并入 T11 | — |
| 67 | posttool-codex-skill-ledger.py | T13 函数（matcher 加 Skill） | — |
| 68 | notification-idle-overnight.py | 删除（成 stub） | 只写无人读的日志；"空转"由 Stop 门与唤醒负责 |
| 69 | stop-workflow-coordinator.py | 并入 T17（P5 R9-R12） | O7 |
| 70 | stop-do-report-gate.py | T17 的 /do 谓词（P5-d） | C3 |
| 71 | stop-obligation-gate.py | 删除（P5 R11 成 stub） | P1b 目标 3 |
| 72 | sessionend-scratch-sweep.sh | 保留（T18） | — |
| 73 | subagent-stop-diff-check.sh | T16 函数（改为自身 obligation 关联、修 `HEAD~5`） | 5.3-3 |
| 74 | pretool-layer-match-gate.sh | T16 函数（只对 dev，用自身 obligation 的 context 与 report） | 现取"最新"文件 |
| 75 | subagent-stop-guard-integrity.sh | T16 函数（真正拦截 `removal_authorized=false` 的守卫删除） | 教训"不准拆掉已有保护"目前无执法 |
| 76 | subagentstop-restart-track.py | T16 观察函数 | — |
| 77 | subagentstop-codex-enforce.py | T16 函数 | — |
| 78 | subagentstop-e2e-enforce.py | T16 函数（QA 谓词） | O2 |
| 79 | subagentstop-artifact-contract-enforce.py | T16 核心（G2） | — |
| 80 | subagentstop-cp-enforce.py | T16 函数（按自身 obligation 作用域） | 现扫全部 cp-state |

### 7.3 合并时有风险的教训与保住它们的办法

| 风险 | 涉及教训 | 保住的办法 |
|---|---|---|
| **故障隔离消失**：现在一个钩子崩溃不影响别的钩子；合并后一个函数抛异常可能带走整个门 | "never wedge"（block-background-tasks.py:16-20、commit-dispatch-attest.py:21-27"见证不是门"） | 每个规则函数独立 try；观察类函数永远吞异常；见证类函数的失败不得阻止派发 |
| **失败策略混在一起**：tool-policy 导入失败要**拦**（pretool-tool-policy.py:12-15, WS1），write-guard、config-guard、overwrite 类失败要**放** | WS1 fail-closed vs 通用 fail-open | 规则表里显式声明每条规则的失败方向，并各有一条故障注入测试 |
| **豁免语义被统一的早退抹掉**：/do 放行编排门、write-guard、后台检查、G3；但**不**放行 do-block-subagents（方向相反）、write-guard 的批量哨兵层（主代理也禁，:16-31）、config-guard、git 权限 | "/do 期间不得派子代理"；"批量哨兵只能由人类提示铸造" | 不允许门入口处的 `if consent: allow`；每条规则自带豁免列表并有回放测试 |
| **执行者范围不同**：编排门、读大小只管主代理；tool-policy、cp-state 守卫只管子代理；write-guard 两者都管；workflow-gate 目前两者都管（:1101-1118 连子代理的 TodoWrite 也会清主代理的锁） | 主代理只派活；子代理按角色 | 每条规则声明 actor 范围；顺手修正 workflow-gate 对子代理的处理 |
| **连续 Bash 计数被别的写入顺带清掉** | b5d447e：用 Grep 重置计数绕过（pretool-orchestrator-gate.py:11-21, :136-157 NB2 no-clobber） | 计数文件只由一个函数写（P1b 行 14），合并后的其它函数不得写它 |
| **超时预算被拉长的函数吃掉**：归因 30s、写守卫 5s、配置守卫 5s（settings.json 各注册的 timeout）；超时被 CLI 视为非阻断错误 = 安全检查静默跳过 | 安全门必须真的执行 | 重活（归因、质量指标、聚合器、doc-sync）放 PostToolUse 观察门，不放进安全门；安全门设短超时并测量 |
| **并行变顺序后的拒绝信息**：现在任何一个 exit 2 就拦，各钩子各自给出原因 | 原因要指向产物和检查（D21） | 合并门执行完所有规则后**汇总所有拒绝原因**一次给出，避免"修一个再撞一个"的循环 |
| **见证必须发生在判决之后** | commit-dispatch-attest 的设计前提 | 在 T5 里放在所有拒绝规则之后（顺序执行恰好修复 C7） |
| **能力只能从人类提示铸造** | userprompt-bulk-commit-capability.py:1-20、consent-allowlist、restart-authorize | T3 只在 UserPromptSubmit；不得为了合并把铸造挪到 PreToolUse |
| **matcher 写错 = 静默死亡** | posttool-git-warn 的教训 | 合并门用宽 matcher，在函数内按 `tool_name` 分派，并有"每条规则至少被一个回放触发"的 CI 检查 |
| **advisory→block 的独立开关** | G1/G2/G3/G4 分别武装（P1b、P2） | 合并后保留每条规则各自的开关变量名，P2 的三行武装不变 |
| **overnight 自我修复边界** | 过夜期间不得改 harness 自身（pretool-overnight-hook-guard.py:9-11） | 作为 T6 中独立规则，不吃 /do、/allow 豁免（与现状一致），并保留其审计日志直到有读者或删除 |
| **"防循环八机制"本身** | 6 轮未修好的循环（层级、二分、守卫完整性、最小改动） | 不是删除，而是改为按任务（obligation）关联、通过 exit 2/obligation 失败真正生效；在生效前它们没有执法，合并不会让情况更坏 |
| **/restart 恢复路径** | 生产教训 #16 | lib/subagent_restart 保持唯一决策者；三个薄封装合并只改调用位置，P1c 的 /restart 回放必须保持全绿 |
| **跨会话旧钩子列表** | 缺文件时 `python3` exit 2 会卡住旧会话（stop-completion-gate.py:3-7） | 被合并的旧文件先变 `# STUB:` exit-0 文件，按 P10 的规则再删除 |
