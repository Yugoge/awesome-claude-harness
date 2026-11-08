# D28 研究与设计：/spec、/dev 的需求提问轮，/close 评分，驱动 agent 的评分系统

日期 2026-11-08。只读研究，没有改动任何代码、hook 或运行时状态。依据：规划分支 `claude/vibrant-hopper-bazrn8` @ 54cc08f 的
DECISIONS.md（D28、D3、D9、D9b、D18、D20、D23、D24、D26）、P12-SLIM.md 和 `audit/2026-11-08/` 的两份审计；
七条只读研究通道的报告；Claude Code 官方 hooks、sub-agents、tools-reference 文档（2026-11-08 读）。

引用前缀：M = origin/master 2acc29b；T = 合并列车 `claude/harness-review-merge-qlm420` 69172e2（P1b+P1c+P3）；
P2 = `claude/eloquent-archimedes-ry9p7q` 3915e39（PR #10）；P4 = `repair/P4` 31dbb18（PR #12）；
P5 = `repair/P5` fa66a1a（PR #14）；P6 = `repair/P6` 84f87a9；P9 = `repair/P9` b3827f9（PR #16）。

---

## 0. 结论

- **(a) 提问轮。** 题目由 **BA** 出：/spec 和 /dev 系列（/dev、/redev、/dev-command）都由 BA 出，spec agent 不出题。
  - BA 把一轮题目写成产物 `docs/dev/requirement-round-<task>-r<n>.json`。
  - 主代理把题目原样放进一次 AskUserQuestion 去问，`metadata.source = requirement-round:<task>:r<n>`。子代理没有这个工具（§1.1）。
  - CLI 写下的答案由 PostToolUse hook 原样写进 `docs/dev/requirement-answers-<task>-r<n>.json`，这就是用户原话契约。
  - 派发门（G1 所在的 PreToolUse Agent 门）强制"问过"：本轮题目被原样问过之前，拒绝该任务的下一次派发。
  - 语义照 D9b：只要问过，不论答没答；Skip、拒绝、超时都算问过，什么也不记，也不拦。
  - /dev-overnight 里结构上开不出 /spec 或 /dev 区间，P2 对 AskUserQuestion 的拒绝再兜一层（§2.8）。
- **(b) 评分。**
  - 分数事件只由 hook 从事实中写出，追加进现有的 `logs/lifecycle.jsonl`，由一个写函数完成。
  - 分数不存储：读的时候由纯函数现算，没有新的状态文件，也没有计数器。
  - agent 在 SubagentStart 时看到自己的分数，不超过 3 行。
  - owner 打分之后，看到趋势、最差的 agent 和原因。
  - 分数低的生产者，在它自己停下时（G2）必须交出 self-review 一类的字段；dev 分数低时，QA 还要做对抗性检查。
  - /close 和 /commit 不加任何检查。
- **(c) 新阶段 P13。** 排在 P12 之后、P11 之前，拆成 P13-1、P13-2、P13-3，每个约一天。P13-1 和 P13-2 可以并行（`phase-prompt.md`）。
- **在途工作必须先改的地方**（§6）：
  - PR #16（P9）在快照提交 6c4c0d1 里删掉了全部评分代码，必须逐块恢复；
  - PR #12（P4）满足 D28 第 2 条，但审阅者的两条中等级别意见在 31dbb18 上还没修；
  - 规划文件 `prompts/short/P9.md` 的 R10-R13 和 `SPLIT-PLAN.md` 的 P9-7 仍写着"退役"，由审阅者改，本次不碰。
- **需要 owner 决定的四个问题**写成一次 AskUserQuestion，见 §7。其余选择按 D10、D18 由规则或实验决定。

---

## 1. 现状

### 1.1 平台事实（官方文档）

| 事实 | 出处 | 对设计的影响 |
|---|---|---|
| 子代理不能调用 AskUserQuestion，即使写进 `tools` 也会被第一道过滤去掉 | sub-agents，"Available tools" | 出题人和提问人分开：子代理出题，主代理去问 |
| SubagentStart 存在，输入有 `agent_id`、`agent_type`，没有 prompt；`hookSpecificOutput.additionalContext` 会"加到子代理开始时的上下文里" | hooks，SubagentStart | 派发时的分数行用它注入，不靠主代理的文字 |
| PreToolUse 可以返回 `updatedInput` 替换工具输入；针对 Agent 的规则没有写明 | hooks，PreToolUse | 只作后备方案，用实验决定（§5） |
| PostToolUse 的 `additionalContext` 进入模型，界面上不显示；`systemMessage` "shown to the user"，但 PostToolUse 一节没有单独确认 | hooks，Common JSON output | owner 看到的摘要优先用 systemMessage，要先测（§5） |
| AskUserQuestion 在跳过、超时自动结束、拒绝时 PostToolUse 会不会触发：文档没写；被拒绝的调用不触发 PermissionDenied | hooks，PermissionDenied | 契约与评分只在有答案时写；"问过"读 transcript，不依赖 PostToolUse 是否触发 |
| 同一事件的多个 hook 并行运行 | hooks，handler fields | SubagentStop 上的观察者看不到 G2 当次的结论，评分观察点放在 PostToolUse(Agent)（§3.2） |
| UserPromptSubmit 和 SessionStart 的 stdout 进入模型 | hooks，Exit code 0 | 主代理自己的分数行在命令开头给出 |

### 1.2 今天谁问、怎么问

- **/spec。** 主代理自己用纯文字问（M:commands/spec.md:24、:37）。
  - 只在 Section 5 写不出来时才问，最多 3 轮（:32、:39）。
  - 明文禁止需求访谈："No 'deep-dive', no 'acceptance criteria' interview"（:26）。
  - spec agent 只在 Finalize 时派发（:297-313），没有提问职责，front matter 也没有 `tools`（M:agents/spec.md:1-4）。
  - P9 把 Step 2 改成 AskUserQuestion（P9:commands/spec.md:37），但 :26 的禁令还在。
  - P5 的 Stop 门不管 /spec（P5:hooks/lib/stop-commands.json，`GATED_COMMANDS` 不含 spec）。
- **/dev 系列。** 派发 BA 之前什么也不问，只有参数为空时才问（M:commands/dev.md:179）。
  - BA 不直接问用户（M:agents/ba.md:60、:1457）。
  - 只有在"请求、代码和合理默认都定不了"时，BA 才写 producer question：`docs/dev/producer-question-<task>-ba.json`，一个决定、2-4 个选项、带 default（M:ba.md:105-138；schema producer-question.v1）。
  - 主代理用一次 AskUserQuestion 转问，再派发 BA。答案只出现在再派发的提示词里，没有 hook、脚本或 schema 保存它（M:dev.md:491-523）。
  - **也没有任何 hook 强制主代理去转问**（P2:commands/dev.md:444-449，只是文字）。
- **"用户原话"并不是原话。** `docs/dev/user-requirement-<id>.md` 由 prompt-workflow 写，但它用 `' '.join(clean_tokens)` 重组过，换行和空白都被压掉了（M:hooks/prompt-workflow.py:1556-1574；T:1465；P9:1454）。
- **违反 D18 的示例还在。** M:commands/dev.md:1580-1583 问 "which API?"，M:commands/dev-command.md:1072-1075 问 "which metrics?"，T 和 P4 上都没改。
- **纯文字的等待。** close.md 的 `<options>` 和 `AWAITING_INPUT`（P4 已删）；/do 和 /dev 空参数时的提问（P9 改成 AskUserQuestion）；/spec 的空参数提问（P9:24，仍是纯文字）。
- **overnight。** P2 的 `pretool-overnight-hook-guard.py` 在 PreToolUse 拒绝 AskUserQuestion，主代理和子代理都拒（P2:settings.json:483；hook :2119-2145）。
  - 判断条件 `_unattended`：最近一次人类输入的提示是 /dev-overnight。它不读状态文件，直到下一次人类输入才解除。
  - /spec 和 /dev 是 `disable-model-invocation: true`，且 `Skill(dev:*)`、`Skill(spec:*)` 被拒（P2:settings.json:275、:299）。所以 overnight 窗口里开不出 /spec 或 /dev 区间。

### 1.3 P4（PR #12）的评分：对照 D28 第 2 条

- **满足。**
  - /close Step 4 是一次原生 AskUserQuestion：header `Rating`，四个标签，`multiSelect: false`，`metadata.source = close-rating:<task>`（P4:commands/close.md:345-366）。
  - hook 只在三个条件同时成立时写一行 `{ts, task_id, rating, tool_use_id}`：主代理在问、来源匹配、答案是四个精确标签之一（P4:hooks/lib/close_rating.py:59-78；hooks/posttool-close-rating.py:13-25）。
  - Skip、文字回答、超时、拒绝都不写，也不拦（P4:hooks/tests/test_close_rating.py:96-112）。
  - "问过"的判定 `rating_asked` 接受任何 tool_result（:50-56），由 P5 Stop 门的 `p_close` 消费（P5:hooks/stop-command-gate.py:198-210）。
  - 这满足 D9 和 D9b。
- **未修。** 审阅意见两条，在 31dbb18 上都还在：
  - 意见 1：Step 4 没有 `subagent_call`，`_canonical_step` 按标签把 BA 的产物绑到评分这一步（P4:scripts/todo/close.py:19；hooks/lib/obligation.py:1312-1323）；
  - 意见 2：`--auto` 会收进完成不了的旧链（P4:scripts/dev-lifecycle.py:167-183）。
- **P4 对重新设计的约束**（由 P13 改，P4 不用改）：
  1. 每个周期一行，没有 agent 字段。
  2. 去重时读的是"任何含 `task_id` 的行"（close_rating.py:17、:76）。将来任何带 task_id 的事件行都会挡住 owner 对这个任务的评分。去重必须改成只在评分行之间比较。
  3. hook 要求恰好一个问题（`[question] =` 解包）。加第二问要改这里。
  4. 文字回答被丢弃；"1-2" 存成 1。
  5. `close_rating.append_row` 是唯一的写函数，但 `score-update.sh` 通过 heredoc 也调用它，于是有两个写进程。`score-update.sh` 还在 `permissions.allow` 里（P4:settings.json:62），任何有 Bash 的 agent 都能给自己写分。
  6. P4 上分数只降不升：close_success 不再发出，qa_first_pass 和 qa_second_pass 的增量是 0。
  7. 文档字符串仍引用 D9a（close_rating.py:1；posttool-close-rating.py:2）。

### 1.4 评分系统现状

- **存储。** `${CLAUDE_CONFIG_DIR:-~/.claude}/logs/lifecycle.jsonl`，被 gitignore，所有项目共用一份。
  - 每行 9 个键：`ts, agent, event, prev_score, new_score, delta, unclamped_score, actor:"orchestrator", reason`（T:scripts/score-update.sh:357-368）。
  - 写时取排他锁（flock），读时取共享锁。
- **P1b 带来的变化（在 T 上）。**
  - 新增唯一读者 `scripts/lib/score_log.py`，以及 `tests/test_score_log.py`（在 CI 中）。
  - 增量表移到 agent 的 front matter `score:`（T:agents/dev.md:4 等）。
  - 用 roster 取代 CANONICAL_AGENTS。
  - M3 前置条件不再读 close-report。
- **事件**（dev/ba/qa 的增量，M 与 T 相同）：

  | 事件 | dev | ba | qa |
  |---|---|---|---|
  | close_success_qa_pass / qa_fail_fixed | +2 | +1 | +1 |
  | qa_reject_dev | -12 | 0 | 0 |
  | qa_reject_ba | -5 | -8 | 0 |
  | user_rating_1 | -40 | -20 | -20 |

  没有下限。D7 让 /close 总能完成，close_success 因此变成常量；在 D2 下 QA 不通过只是流程中的一步。结果分数只往下走，最后都落到 "Disgraced"（landscape/H-scoring.md §4）。
- **注入。** `score-inject.sh` 只出现在 /dev 的 BA、dev、QA 三个模板里（T:commands/dev.md:374、:713、:795），每次 1,185-1,328 B。
  - 三份回显合同 INJECTION_PROOF（四个字段）没有任何消费者（T:agents/ba.md:768-779、dev.md:511-522、qa.md:1370-1381）。
  - 没有任何 hook 读分数来改变行为。
  - 评分相关的文字在 T 上共 17,105 B。
- **P9 的现状。** P9 在快照提交 6c4c0d1 里删掉了全部评分代码：四个脚本、三组测试、dev.md 的注入与 Step 14、三份回显合同、front matter `score:`、settings 的 allow、回放驱动里的评分步骤。P9 头上已经没有评分代码。这和 D28 的"P9 不删评分代码"冲突（§6.1）。

### 1.5 可用的事实信号

| 信号 | 生产者和位置 | 能否归到某个 agent | 被评者能否作弊 |
|---|---|---|---|
| 重派次数 | CLI 写在父 transcript 里的 Agent tool_use 及其 obligation 块；读法见 T:hooks/lib/obligation.py:1007-1043、:1107-1149、`first_declared_at` :1440-1467 | 能：按 (task, lane, role, 声明的路径) 分组；重派的原因从新提示词里读（QA 报告、gap 或 finding 路径） | 不能：子代理写不到父 transcript；G1 把 dispatched_at 限在 ±300 s 内，并让 role 与 subagent_type 一致 |
| lane QA 的 `qa.status` | `docs/dev/qa-report-<ts>.json`，schema 枚举 pass/fail/warning（T:schemas/qa-report.v2.json:52-55）；派生写权限只给 QA | 能：用 `primary_cause` 归因，但它只在模板里，是 QA 未经验证的判断（T:agents/qa.md:1583） | dev 不能改 QA 的结论；QA 对别人的归咎是一面之词 |
| close-QA 判决与 finding | close-QA 回复的最后一行，用 `classify_line` 判（T:hooks/lib/close-verdict.py:26-37）；每个 finding 指向一个产物路径 | 能：`declaring_dispatch(task, path)` 给出角色（T:hooks/lib/obligation.py:1384-1437） | 不能：close-QA 写，被评的生产者写不到 |
| G2、e2e、codex 拦下的停止 | 退出码 2 加 stderr，信息里有 agent_id 和角色（T:hooks/subagentstop-artifact-contract-enforce.py:757-777） | 能 | 不能，但今天没有任何地方记录；它在 transcript 里的形态没有测过 |
| owner 评分 | P4 的评分行 | 只有任务级，没有 agent 级 | 不能：只有 CLI 的 tool_response 算数 |
| 不可靠的信号 | inspector findings（无类型，无 agent）、specialist yield（只在 overnight）、codex 台账（只证明调用过）、主代理自己调用 score-update | — | — |

---

## 2. (a) 需求提问轮

### 2.1 谁出题：BA

- 子代理问不了（§1.1），所以出题和提问必须分开：一个子代理出题，主代理照抄去问。
- BA 本来就负责需求分析。它的五个清晰度维度（What/Why/Where/Scope/Success，M:ba.md:94-103）正好对上 D28 要的意图、范围、边界情况、验收。它已经有 producer-question 这条通路，也有五个合同。
- spec agent 只做拆分、视图和检查点（M:agents/spec.md:3、:14-18），是机械的收尾。让它出题等于给它加一项新职责。
- 由一个角色出题，就只有一个生产者（D24），规则只有一个归处（P12 原则"one home per rule"），题目质量的分数也只落在一个角色上。
- 否决主代理自己出题的方案，理由有三：
  - 违背只编排的规则；
  - 题目会不经检查就混进技术选择（D18）；
  - 出题质量无法归到任何一个 agent 去记分。
- 代价：每个 /dev 多一次 BA 派发（intake），每个 /spec 多一次 BA 派发。/spec 的"访谈中"谓词（P12 之后是派发门里的一个谓词）要允许前台的 `ba`（hooks-audit C6）。

### 2.2 /dev、/redev、/dev-command 一轮的流程

1. 主代理派发 **BA intake**：obligation 只声明 `docs/dev/requirement-round-<task>-r1.json`（kind `requirement_round`，schema `requirement-round.v1`）。
2. BA 读需求、代码（以及 spec，如果有）后写题目文件，然后停下。G2 在 BA 停下时检查这个文件（§2.4）。
3. 主代理调用一次 AskUserQuestion，参数如下：
   - `questions` 逐字取自题目文件，即每题的 question、header、multiSelect、options；
   - `metadata.source = "requirement-round:<task>:r1"`。
4. PostToolUse hook 读 CLI 的 `tool_response`。只要里面有用户内容（answers、response、annotations 任一非空），就写 `docs/dev/requirement-answers-<task>-r1.json`（§2.5）。Skip、超时、拒绝什么也不写。
5. 主代理派发 **BA analysis**，输入是答案文件的路径（或者"无答案"）。
   - BA 写 context、ticket、acceptance-criteria。
   - 每个已回答的问题都要映射进 `context.requirement.contract_refs`，即 `{answer_ref: "r1.q2", criterion_ids: [...]}`。
   - 每个没回答的问题，按它的 `assume` 选项写进 `assumptions`。G2 在 BA analysis 停下时检查这两项都齐。
6. 如果答案引出了新的、无法用默认值解决的问题，BA analysis 不写分析产物，而是写 `requirement-round-<task>-r2.json`，回到第 3 步。轮数上限见 §2.9。
7. 之后的 dev 和 QA 照旧。QA 按验收标准核对；验收标准经由 contract_refs 连回用户原话。

### 2.3 /spec

- Section 5 初稿写好之后，第一次 Explore 之前，派发 BA intake。task id 用 spec id，由 spec-write.py create 生成。
- 后面同 §2.2 的第 2-4 步。
- 答案文件写好后，`spec-write.py append` 把答案原样复制进 Section 5，写成 `### 5.N: Requirement round r<n>`，并注明出处路径。
  - 这一步由脚本逐字节复制，主代理不转述。
  - spec 的生产者仍然是 spec-write.py，hook 不写 spec，所以 D24 不会出现第二个生产者。
- spec agent 的 Finalize 派发要读答案文件。在 r1 被问过之前，派发门拒绝 Finalize（§2.6）。
- 删除 M:commands/spec.md:26 "No 'deep-dive', no 'acceptance criteria' interview" 这条禁令。它和 D28 正面冲突。

### 2.4 题目文件 `requirement-round.v1`

```json
{
  "task_id": "20261108-101500",
  "round": 1,
  "spec_ref": null,
  "questions": [
    {"id": "q1", "dimension": "intent", "header": "Goal",
     "question": "What should change for you when this is done?",
     "multiSelect": false,
     "options": [{"label": "...", "description": "..."}],
     "assume": "<one of the labels, used if you skip>"}
  ]
}
```

G2 在 BA 停下时检查以下几项：
- `task_id` 等于 obligation 的 task；`round` 是下一轮，即前一轮已经问过。
- 题目 1-4 个，每题 2-4 个选项；`header` 不超过 12 个字符；`assume` 必须是该题某个选项的标签。这些都是 AskUserQuestion 的硬约束。
- **没有 spec 时，r1 必须恰好 4 题，分别覆盖 `intent`、`scope`、`edge_cases`、`acceptance`。** 这样"刨根问底"变成可以机器检查的规则。
- 有 spec 时（/dev 从一个 /spec 出发），至少 1 题，每题的 `spec_ref` 指向 spec 中没写清楚的那一节。这是 owner 选择 Q2 的推荐项。
- **D18 检查（真实强度：lint，只能抓代码痕迹）**：
  - `dimension` 只能取上面四个值，没有 `technical`；
  - 题干和选项里不得出现代码标记：反引号、带扩展名的路径、`()`、`::`；
  - 它抓不到"用纯文字写的技术选择"。prompt 里的示例全部改成产品层面的问题，并删掉 dev.md:1580 那一类技术示例。

### 2.5 答案即用户原话契约

- **生产者。** PostToolUse AskUserQuestion hook，也就是 P4 的 posttool-close-rating 推广后的版本：按 source 前缀分给各个库的 `handle(payload)`。它是答案文件唯一的写者。
- **答案文件的内容。** 只从 CLI 的 `tool_input` 和 `tool_response` 原样复制，不做任何规范化：

  ```json
  {"task_id": "...", "round": 1, "source": "requirement-round:<task>:r1", "tool_use_id": "...",
   "asked_at": "<transcript ts>", "round_file_sha256": "<题目文件的 sha256>",
   "questions": <tool_input.questions 原样>, "answers": <tool_response.answers 原样>,
   "response": <原样，若有>, "annotations": <原样，若有>}
  ```

- **Skip、超时自动结束（`afkTimeoutMs`）、拒绝、出错：什么也不写**（D9b）。BA analysis 看到"没有答案文件"，就按 `assume` 继续，并把它写进 assumptions。
- **producer question 用同一条规则。** source 为 `producer-question:<task>:<role>`，答案写到 `docs/dev/producer-answer-<task>-<role>.json`。今天这类答案只活在再派发的提示词里（§1.2）；改过之后，每个 owner 的回答都是原话产物。
- **谁能写。**
  - 没有任何派发会声明这些路径，所以 P1b 的派生写权限会拒绝子代理写它们。
  - 主代理要另加一条：写门（tool-policy）把 hook 自有的路径列为任何 agent 都不能写，Write、Edit、Bash 重定向都算。这些路径是 `docs/dev/requirement-answers-*`、`docs/dev/producer-answer-*` 和评分日志。
- **消费者。** BA analysis（必读，G2 检查 contract_refs）；QA（验收标准连回答案）；spec agent 的 Finalize；/commit 的白名单把它和任务的其它产物一起提交。
- **为什么不只用 transcript。** transcript 才是最强的原话来源，但它会被清理，而且是会话级的，/close 和 /commit 常在另一个会话里跑（P4 "Out of scope, found"）。所以契约要落在项目的 docs/dev 里。

### 2.6 hook 怎么强制"问过"

**判定（一个函数，和评分的判定共用）。** `asked(span, source, questions)` 为真，当且仅当区间内有一次主代理的 AskUserQuestion tool_use 满足以下三条：
- `input.metadata.source == source`；
- 有一个 tool_result，内容不限，`is_error` 也算；
- `input.questions` 去掉 id、dimension、assume 之后的规范 JSON，等于题目文件里同样处理后的内容。

第三条保证主代理不能改写题目、替换题目或混进技术选择。这个函数放在 hooks/lib，读 transcript 的方式与 P4 的 `close_rating.rating_asked` 相同；P13-3 让 `rating_asked` 改为调用它，评分和提问从此共用一个判定。

**规则（放在派发门，与 G1 同一个 PreToolUse Agent 门）。**
1. **先问后派。** 在一个 /spec、/dev、/redev、/dev-command 区间里，如果某次派发声明的题目文件（requirement-round 或 producer-question）已经存在且新鲜，但还没满足 `asked`，就拒绝同一任务的任何下一次派发。拒绝信息是：
   `ASK_FIRST: ask <file> with one AskUserQuestion, metadata.source "<source>", questions exactly as written; then dispatch.`
   这顺带补上了 producer question 转问没人强制的缺口（§1.2）。
2. **没有 r1 就不开工。** 在同样的区间里，一次声明了"除 requirement-round r1 以外任何产物"的派发（BA analysis、dev、QA、specialists、spec Finalize），在 `asked(..., r1)` 之前一律拒绝。
   - 没有 obligation 块的派发（Explore、graphify）放行。
   - /dev 的 task 取 `span.minted_id()`（P5），/spec 的 task 取被检查那次派发的 obligation task。

**为什么放在派发门，而不放在 Stop 门。**
- 顺序本身就是要求：先问，再分析，再开发。在 Stop 时才发现没问，已经晚了。
- P5 的 Stop 门不管 /spec。如果把 /spec 加进 `GATED_COMMANDS`，就得为 /spec 那几个贯穿整个会话的 todo 步骤开豁免（P5 报告 §4）。
- 一件事只由一个门判定。P5 已有的 "no pipeline dispatched" 缺口覆盖了完全不派发的情况。D21 也明确把派发（G1）列为执法点。

**没有死路（D25）。**
- 每次拒绝都能用一个 agent 动作解除：派发 BA intake，或者调用一次 AskUserQuestion。
- 不能弹对话框的会话也不会卡死：
  - dontAsk 模式会拒绝 AskUserQuestion；
  - 无权限宿主的 headless 会话里，工具不提供，调用会得到 "no such tool" 一类的错误结果；
  - 这两种情况下 transcript 里都有 tool_use 加一个出错的 tool_result，按定义就算问过。
  - P13-1 要用静态读 CLI 包的方式核实这一点（§5）。
- 规则里没有计数、没有放行文件、没有重试上限（D4）。回答本身不放行任何门（D23）。

### 2.7 不用纯文字问

- **结构上已经挡住了。** /dev 系列在 todo 没完成前不能停（P5 的 todo 半门）。所以主代理不能用"打一个问题然后结束这一轮"的方式等用户回复。只能停在 AskUserQuestion 上，这正是 D23 说的"提问即暂停"。
- **再加一条窄规则，在 Stop 门里。** 区间是 /spec 或 /dev 系列，且这一轮最后一个主代理文本块的最后一个非空行以 `?` 或 `？` 结尾时，记一个 gap：
  `<cmd>: the turn ends with a question in text; ask it with AskUserQuestion, or end without it.`
  - 对 /spec，这是 Stop 门对它唯一的检查。/spec 仍然不进 `GATED_COMMANDS`，所以不受 todo 半门影响。
  - 门仍然什么都不写（P5 用 AST 禁止门里出现写操作）。
  - 解除办法：改用 AskUserQuestion，或者结尾不带问号。不是死路。
  - "Anything else?"、"要不要我再……？"这类结尾正是 owner 不要的；纯修辞的问句收尾很少见。

### 2.8 不在 /dev-overnight 里问

- /spec 和 /dev 区间只能由人类亲手输入开启（P5:hooks/lib/command_span.py:49-52、:105-112）。overnight 内部跑的流水线是自己派发 BA、dev、QA，不经过 /dev。所以 §2.6 的两条规则在 overnight 里根本不会触发。overnight 的 BA 模板也不声明 requirement-round。
- 万一有人在窗口期内手动输入 /dev：人在场，P2 的拒绝也随之解除（P2 测试 :166-177）。提问是正当的。
- 在 overnight 里调用 AskUserQuestion 照旧被 P2 拒绝，提示 agent 自己决定并记录（D20）。P13 不加任何 overnight 例外。

### 2.9 轮数

- r1 必问。只有当答案引出新的、无法靠默认值解决的问题时，才有追加轮。
- 上限写在 schema 的 `round` 最大值里：r(max+1) 文件在 G2 处被拒，BA 只能按默认决定并记录。代码里有上限，但不需要状态。
- 推荐上限是 3 轮，由 owner 定（§7 Q1）。

### 2.10 D24：(a) 的产物

| 产物 | 生产者 | 决定性的消费者 |
|---|---|---|
| `docs/dev/requirement-round-<task>-r<n>.json` | BA（intake 或 analysis 派发声明它） | 主代理照抄去问；派发门的 `asked` 比对；答案 hook 记它的 sha256 |
| `docs/dev/requirement-answers-<task>-r<n>.json` | PostToolUse AskUserQuestion hook | BA analysis（G2 检查 contract_refs）、QA、spec Finalize、/commit 白名单 |
| `docs/dev/producer-answer-<task>-<role>.json` | 同一个 hook | 被再派发的生产者 |
| `context.requirement.contract_refs` 与 `assumptions` | BA（已有产物里的新字段） | G2、QA |

---

## 3. (b) 驱动 agent 的评分系统

### 3.1 原则

1. **只记事实，不记自评。** 事件由 hook 从别人产出的事实里得出：CLI 记录、别的 agent 的报告、代码的判决、owner 的回答。被评的 agent（包括主代理）不能写日志。
2. **分数现算，不存。** 分数、档位、趋势都由读时的纯函数从只追加的日志算出。没有分数字段、计数器或放行标志，也没有新的状态文件。
3. **按项目算。** 每行带 `project`，取 git 根身份的 sha256 前 12 位，不含个人值。这修掉了"项目 A 的评分改变项目 B 的提示词"这个缺陷（H-scoring §2.1）。
4. **滚动窗口、有上下界、能回升。** 窗口取最近 10 个任务，分数在 0-100 之间，不会再一路掉到 "Disgraced"。
5. **派发时说得短。** 不超过 3 行、400 B，由 hook 注入，不靠主代理的文字。
6. **后果由 hook 执行。** 低分的后果在生产者自己停下时（G2）检查，从不放在 /close 或 /commit。

### 3.2 事件：哪个事实给哪个 agent 记分

所有事件都由同一个观察者 hook 写出。它注册在 PostToolUse，matcher 是 `Agent|AskUserQuestion`，只记录、从不拦。
- 在 PostToolUse(Agent) 这一刻，所有 SubagentStop 门都已放行，obligation、subagent_type 和最终回复同时可见（研究通道 F）。这是最好的观察点。
- 观察者不重算 G2 的结论，否则 G2 的判决会有第二个生产者。它只读已经落地的产物和 CLI 记录。

| 事件 | 事实来源 | 记给谁 | 初始分值（最终由实验定，§5） | 去重键 |
|---|---|---|---|---|
| `qa_first_pass` | lane QA 第一轮 `qa.status = pass` | 该 lane 的 dev +2，ba +1 | | QA 派发的 tool_use_id |
| `qa_fail` | lane QA `fail`，看 `primary_cause` | `dev_implementation` 记 dev -4；`ba_spec` 记 ba -4；`qa_oversight` 和 `environment` 不记 | | 同上 |
| `qa_catch` | 一次 QA 失败之后，同一 lane 改了文件并通过 | qa +1，每个任务最多 +2 | | 通过那次的 tool_use_id |
| `escaped` | close-QA 给出 `CLOSE_FINDINGS`，而 lane QA 已通过；finding 引用的产物用 `declaring_dispatch` 找到角色 | 该角色 -5；该 lane 的 qa -3 | | tool_use_id 加 finding 序号 |
| `close_clean` | close-QA 第一轮就落地 `CLOSE: YES*` | qa +2 | | tool_use_id |
| `rerun_gap` | 同一 (task, lane, role, 声明路径) 的第 k 次派发（k ≥ 2），起因是缺失或不合格的产物；起因是 QA 失败、close finding、澄清或瞬时 API 错误的不算 | 该角色每次 -2 | | 重派的 tool_use_id |
| `stop_blocked` | G2、e2e、codex 拦下该派发的停止；**只在 transcript 里能测到时才启用**（§5） | 该角色每次 -1，每次派发最多 -3 | | agent_id 加门代码 |
| `main_refused` | 区间里主代理的一次工具调用被门拒绝：tool_result 出错，内容带门代码（ASK_FIRST、G1、写门等） | main 每次 -1，每个区间最多 -5 | | 记录的 uuid |
| `main_stop_blocked` | Stop 门拦下主代理的停止；能测到才启用 | main 每次 -1，每个区间最多 -3 | | 记录的 uuid |
| `rating` | owner 评分 5/4/3/1 | 该任务所有有派发记录的角色和 main：+3/+1/-3/-6 | | 规范化的 task id，只在评分行之间去重 |
| `rating_blame` | owner 第二问选中了角色 X（§7 Q3） | 评分不超过 4 时 X 再 -4；评分为 5 或选"没有"时不记 | | 同上 |

- 分值按事件给，角色从事实里得出：派发记录、`declaring_dispatch`、`primary_cause`。没有"文件名到角色"的表（D21）。
- 规则：一次重派只记一个原因。QA 失败已经在 `qa_fail` 记过，close finding 已经在 `escaped` 记过，都不再记 `rerun_gap`。
- 主代理的事件，由观察者在下一次 Agent 回来时，回扫从上一个观察点到现在的区间片段。区间末尾、之后再没有派发的那一段，会在评分时补扫；补扫不到的就丢掉，诚实地写进 "Out of scope, found"。

### 3.3 分数怎么算（纯函数）

`score(role, project, as_of)` 的算法：
- 取 `project` 相同、`ts < as_of` 的事件行和评分折算行，在属于该角色的行里找最近 10 个不同的 task_id。
- `raw` 是这些行的分值之和，`score = clamp(60 + raw, 0, 100)`。
- 没有任何行的角色记为"新"，派发时只显示一句"no record yet"。
- `trend = score(as_of) - score(窗口往回挪 5 个任务)`。
- 档位：≥ 70 是 good；50-69 是 watch；< 50 是 probation。另外，同一类失误在该角色最近 3 个任务里出现 2 次，也算 probation。失误类别取 `primary_cause`、门代码或 finding 的产物类型。
- `as_of` 取当前命令区间开头那条人类提示的时间。SubagentStart 注入器和 G2 用同一个 `as_of`、同一个函数，所以结果一定一致。当前命令里新发生的事件，影响的是下一个命令。
- 本命令内的升级规则见 §3.6 第 2 条，它只看 transcript，也是确定的。
- **旧行**（9 键、没有 `kind` 的行）照读不报错，但不计分。P4 留下的 4 键评分行没有 `project`，同样不计分。日志本身保留，作为历史。

### 3.4 派发时 agent 看到什么

由 SubagentStart hook 注入 `additionalContext`（官方文档写明的通道），一律英文，不超过 3 行、400 B。示例：

```
Your record (dev, this project, last 10 tasks): 58/100, trend -9, tier probation.
Most frequent miss: QA failed your work for "edge case not tested" (3 of last 5 tasks).
This dispatch: your report must carry self_review (one entry per acceptance criterion); your stop is checked for it.
```

- good 档只给一行：`Your record (qa): 82/100, trend +4. Last miss: close QA found "<finding, 80 chars>".`
- 原因用的是事件的 `why`：QA 失败的 `issue`，或 finding 那一行，截到 80 字符。不用 task id，task id 对 agent 没有可操作的信息（H-scoring §2.4）。
- 主代理在命令开头，由 UserPromptSubmit 的 additionalContext 收到一行：
  `Your record (main): 74/100. Most frequent miss: dispatch refused ASK_FIRST (2 of last 5 tasks).`
- 这些取代：`score-inject.sh` 每次约 1.2 KB 的输出、主代理三次 Bash 注入调用（它们还会撞上 5 次 Bash 的上限）、三份回显合同。而且覆盖所有流水线，包括 /dev-command、overnight、/close 和 /commit 里的 QA，不再只有 /dev。

### 3.5 /close 之后 owner 看到什么

由 AskUserQuestion 观察者处理 `close-rating:` 来源时给出。首选 `systemMessage`（显示给用户，要先测，§5）；后备是 additionalContext，让主代理原样贴出。不超过 5 行：

```
Scores (this project, last 10 tasks): ba 77 (+2) | dev 58 (-9, probation) | qa 66 (-4) | main 90 (0)
This cycle 20261108-101500: dev -4 (QA fail: edge case not tested), qa +1 (caught it), your rating 4: +1 each
Worst: dev. QA failed its work in 3 of the last 5 tasks; its next dispatches must self-review.
```

- **互动性有三处：**
  1. owner 打完分立刻看到这一分带来的变化；
  2. 可选的第二问，在同一个对话框里问"哪个 agent 最需要改进：BA / dev / QA / 没有"（§7 Q3）；
  3. 被点名的 agent 下一次派发就看到原因和要做的事。
- 如果 PostToolUse 在 Skip 时也触发（要测），照样显示分数，只是没有本次评分那一行。
- `--auto` 下有多个父任务时，每次评分各显示一次。
- /close 本身不读日志、不算分、不加任何步骤（P4 的 DO NOT 和 C2 都保留）。摘要来自 hook，不来自 /close 的文字。

### 3.6 低分的后果（hook 执行，位置在生产者自己的停止）

1. **probation 时**（档位按 §3.3 在本命令开头算）：

   | 角色 | 报告里必须有 | G2 检查什么 |
   |---|---|---|
   | dev | `self_review: [{criterion_id, test, result}]` | 覆盖 acceptance-criteria 里的每个 `ac_uid`；`test` 指向工作树里真实存在的测试 |
   | ba | 每条验收标准带 `contract_ref` 或 `source_phrase` | 每条标准都能追到用户原话（答案文件或 Section 5） |
   | qa | 每条验收标准有 `evidence[]`（命令加观察到的输出摘录），并有 `adversarial[]`，至少 3 个尝试过的反例 | 覆盖并且非空 |
   | 其它生产者 | `self_review[]`，每个声明的产物至少一条 | 非空，并引用声明的路径 |

2. **本命令内升级。** 同一 (task, lane, role) 在本区间里已经被 QA 判过一次失败，再派发时不论档位都必须交 `self_review`："第二次交付要证明你检查过"。
3. **更严的下游检查。** 本区间的 dev 处于 probation 时，lane QA 的 SubagentStart 行会说明这一点，QA 报告必须带 `adversarial[]`，G2 检查。这是 QA 变严，不是 /close 加检查。
4. **回升。** 窗口滚动，分数回到 50 以上就自动解除。没有人工放行，也没有状态。
5. **没有死路。** 每个要求都能由生产者写出对应字段来满足。P1c 的 dead-end 检查会把这些新的阻塞点列进去。
6. 强度由 owner 选（§7 Q4）：推荐"self-review 加更严的 QA"；可以只要 self-review；也可以只显示不执行。

### 3.7 单一生产者与存储

- **一个库，一个写函数。** `hooks/lib/score_log.py` 合并现有的读者（T:scripts/lib/score_log.py）和 P4 的 `close_rating.append_row`，提供：
  - `read_lines`、`append`（调用方持锁，首写胜，按 key 去重）；
  - `score`、`tier`、`render_dispatch_line`、`render_owner_summary`。
- **一个写进程。** 只有 PostToolUse `Agent|AskUserQuestion` 观察者调用 `append`。`score-update.sh` 的写入模式随它的最后一个调用者（dev.md Step 14）一起删掉，`permissions.allow` 里的条目也删掉。写门把日志路径列为 hook 自有。这样 P4 留下的"一个函数、两个进程"问题和"任何 agent 都能写分"问题一起解决。
- **行格式。** 在现有日志里加 `kind`：
  - `{"kind": "event", "ts", "project", "task_id", "role", "event", "points", "key", "why", "ref"}`
  - `{"kind": "rating", "ts", "project", "task_id", "rating", "blame"?, "tool_use_id"}`
- **评分去重。** 只在 `kind == "rating"` 的行之间按规范化 task id 去重，修掉 §1.3 的第 2 条。
- **并发。** 沿用 flock。扇出的多个 lane 并行回来时，20 个并发 append 得到 20 行，互不交错。
- **耗时。** 观察者要读 transcript 和 obligation，放在 PostToolUse 观察 hook 里，不放进安全门；设短超时并实测（hooks-audit §7.3 "超时预算"）。

### 3.8 防作弊

- 被评者写不到事实：父 transcript 由 CLI 写；QA 报告的派生写权限只给 QA；close-QA 由别人派发；owner 评分只认 CLI 的 tool_response。
- 日志、答案文件只能由 hook 写，写门拒绝所有 agent 写它们。
- QA 用 `primary_cause` 归咎是一面之词。对冲办法：`escaped` 会同时罚 QA；QA 自己的加分 `qa_catch` 只在"改了文件之后通过"时给，所以 QA 乱判失败拿不到分。
- 自评字段不是"我检查过了"这种空话。G2 核对它覆盖了每个 `ac_uid`、引用的测试真实存在、反例非空。

### 3.9 旧代码的去留

D28：评分系统重新设计，不移除。P9 不删任何评分代码。P13 在新实现接上的同一个子阶段里删除被取代的部分（D17，附可达性证明）。

| 现有部分 | 去向 | 子阶段 |
|---|---|---|
| `scripts/lib/score_log.py` | 搬到 `hooks/lib/score_log.py`，并入 append 和计分 | P13-2 |
| `close_rating.py` | 保留评分逻辑和 `rating_asked`；写入改调 score_log；去重修好；加第二问和摘要 | P13-2 |
| `score-update.sh` | 删除：它的调用者（dev.md Step 14）同时删掉；agent 不该能写分 | P13-3 |
| `score-inject.sh` | 删除：SubagentStart 注入器取代它 | P13-3 |
| `close-scoring-decide.py` | 删除：P4 起已无调用者；close_* 在 D7 下是常量 | P13-2 |
| agent front matter `score:` | 删除：分值按事件放在 score_log 里，一个归处 | P13-3 |
| 三份回显合同 INJECTION_PROOF | 删除：换成可度量的 self_review / evidence / contract_ref | P13-3 |
| dev.md 注入块、占位符、Step 14 评分、"Mascot Score Changes" 表、:93 的批处理理由 | 删除 | P13-3 |
| 两个评分 shell 测试 | 换成 pytest（在 CI 里） | P13-2 |
| `logs/lifecycle.jsonl` 里的旧行 | 保留，不计分 | — |
| prompt-purity 的 OPTIONS_XML 分类 | 这是提问执法，不是评分；P9 删除它可以保留 | P9 |

### 3.10 D24：(b) 的产物

| 产物 | 生产者 | 决定性的消费者 |
|---|---|---|
| `logs/lifecycle.jsonl` 的 event 和 rating 行 | `score_log.append`，只有 PostToolUse `Agent\|AskUserQuestion` 观察者调用 | SubagentStart 注入器、UserPromptSubmit 主代理行、G2 后果检查、owner 摘要 |
| 报告里的 `self_review`、`evidence`、`adversarial`、`contract_ref` | 各自报告已有的生产者 | G2 |

---

## 4. 否决的方案

- **主代理出题或转述答案**：违背 D8 和只编排规则；技术选择会不经检查混进来；转述会丢掉原话。
- **把题目和答案写进 context.json 或 spec**：hook 一写就成了第二个生产者（D24）；BA 的两次派发还会撞上"Write 不能覆盖已有文件"和 G2 的新鲜度规则（P4 "Out of scope, found"）。
- **在 Stop 门检查"问过"**：管不了顺序，也管不了 /spec（§2.6）。
- **把分数存成字段或文件**：违反"不加可变状态"；会饱和；会被改。
- **按"文件名到角色"的表归因**：D21 禁止。
- **owner 摘要由 /close 读日志生成**：等于在 /close 加检查（producer-side 原则，P4 的 DO NOT）。
- **用 PreToolUse `updatedInput` 改派发提示词注入分数**：文档没写 Agent 的规则，同事件并行时谁的 updatedInput 生效也不确定。只作 SubagentStart 测不通时的后备（§5）。
- **按 owner 评分直接重罚**（旧表 1 星 dev -40）：会饱和，失去信息。改为有界窗口，加上可选的点名。

## 5. 风险，以及要做的实验（D18：每项做一次实验，记下结果后照结果执行）

| 问题 | 实验 | 测不通时的后备 |
|---|---|---|
| SubagentStart 的 additionalContext 真能到达子代理 | 静态读 CLI 包；在回放里看注入的位置 | 用 PreToolUse(Agent) 的 `updatedInput` 追加到提示词末尾，要在派发门的所有规则放行之后 |
| PostToolUse 的 systemMessage 是否显示给用户 | 静态读 CLI 包的 PostToolUse 输出处理 | additionalContext，让主代理原样贴出 |
| AskUserQuestion 在 Skip、拒绝、超时时是否触发 PostToolUse | 静态读加回放 | 摘要只在有答案时显示；契约和评分不受影响 |
| 工具不可用时（headless、dontAsk），transcript 里是否仍有 tool_use 加出错的 tool_result | 静态读 | 加一个只读的 CLI 事实，例如 init 记录里的工具列表，满足时才要求提问；不能靠 agent 自称 |
| SubagentStop 被拦时，子代理 transcript 里是否留下可识别的记录（`stop_blocked`），Stop 被拦时主 transcript 里是否留下记录（`main_stop_blocked`） | 静态读加回放 | 这两个事件不启用，写进 "Out of scope, found" |
| 分值和档位阈值 | 用固定日志回放：dev 3 个任务里 QA 失败 2 次，应进 probation；接着连续 3 个干净任务，应回到 watch 以上；100 次失败不会到负无穷 | 调整分值，把选定的值和关键数字写进 PR |
| 观察者耗时 | 在扇出回放中测 p95 | 把 transcript 扫描限制在本区间之内 |
| 提问轮让 owner 觉得烦 | 无法实验，由 owner 的选择 Q1 和 Q2 决定 | — |

## 6. 对在途工作的要求

### 6.1 PR #16（P9）：恢复评分代码

全部删除都在 6c4c0d1 这一个快照提交里，而它同时带着 doc-sync、spec-path 和 consent 的改动，**不能整提交 revert，只能按块从 P6（84f87a9）恢复**：
1. 四个脚本：`scripts/score-inject.sh`、`scripts/score-update.sh`、`scripts/close-scoring-decide.py`、`scripts/lib/score_log.py`。
2. 测试：`tests/score-inject-contract/*`、`tests/score-lifecycle-contract/*`、`tests/test_score_log.py`，以及 INDEX、README 和 TESTING.md 的 S5 行。
3. `settings.json` 的两条评分 allow（P6:50-51）。
4. `agents/{ba,dev,qa}.md:4` 的 `score:`。少了它们，score-update.sh 就没有增量可用。
5. 三份回显合同。
6. dev.md 的注入块、占位符、Step 14、"Mascot Score Changes" 表、:93。
7. 残留白名单里 close-scoring-decide.py 的 5 条。
8. 回放驱动里的评分步骤（agents.py、drivers/dev.py、drivers/close.py）。
9. qa.md `_primary_cause_doc` 里的评分归因。

**不恢复**：close.md 的评分段（P4 已经移走）；prompt-purity 的 OPTIONS_XML 删除；dev-overnight 的 Clause C 和 Rule 8 文字；16 条无用的 Skill deny。这些都不是评分代码。

PR 标题、正文第 14、25、43、73 行要随之更改。

### 6.2 PR #12（P4）

- D28 第 2 条已满足，不需要为 D28 再改。
- 合并前修掉审阅意见 1 和 2。这是 D7 和 D25 的问题，与 D28 无关。
- P4 的 DO NOT"让主代理……echo a rating, score"在 D28 下仍然成立：P13 的摘要来自 hook，不来自主代理。

### 6.3 PR #10（P2）、PR #14（P5）、P12

- **P2**：overnight 的拒绝保持现状，P13 只依赖它。`_unattended` 是私有函数，P13 不需要调用它（§2.8）。
- **P5**：P13-1 往 Stop 门加文本问句规则，作为对 /spec 和 /dev 系列区间的一个谓词；门的尾注已经写着 "Ask with AskUserQuestion only for a real decision"。P5 和 P4 合并后，评分判定要用真的 close_rating 跑一遍（P5 现在用的是 fake，P5 报告 §6）。
- **P12**：L3 把 agents 的共享块搬进 `agents/shared/`，L5 把门合并成"一事一门"。P13 的 prompt 只按功能指名（"G1 所在的派发门"、"生产者的停止门 G2"、"PostToolUse AskUserQuestion hook"），不写文件名。P13 新加的 prompt 文字要通过 L6 的 CI 检查。

### 6.4 规划文件（由审阅者改，本次不改）

- `prompts/short/P9.md`：R10-R13、标题、:10-11 的依赖、D9a 和 D17 两行、A11、A12、A19 的 score-inject exit 127、A24、DO NOT :293、:298。
- `SPLIT-PLAN.md` 的 P9-7 和 :249。
- `FAST-TRACK.md` 的合并顺序：在 P12 之后、P11 之前插入 P13。

---

## 7. owner 的选择（一次 AskUserQuestion，推荐项排在第一位）

```json
{
  "questions": [
    {
      "question": "How many requirement question rounds may /spec and /dev ask before work starts?",
      "header": "Rounds",
      "multiSelect": false,
      "options": [
        {"label": "1 + up to 2 more (Recommended)", "description": "Round 1 always (intent, scope, edge cases, acceptance); BA adds a round only for a point your answers opened; never more than 3."},
        {"label": "Exactly 1", "description": "One round of up to 4 questions; anything still open BA decides by its stated default and records."},
        {"label": "No cap", "description": "BA keeps asking while your answers leave a point it cannot settle."}
      ]
    },
    {
      "question": "When /dev starts from a finished /spec, what should its question round ask?",
      "header": "After /spec",
      "multiSelect": false,
      "options": [
        {"label": "Only open points (Recommended)", "description": "At least one question, each tied to a spec section that leaves something open."},
        {"label": "All four again", "description": "Intent, scope, edge cases and acceptance every time, even right after /spec."}
      ]
    },
    {
      "question": "Should the /close rating also ask which agent most needs to improve?",
      "header": "Blame",
      "multiSelect": false,
      "options": [
        {"label": "Yes, optional (Recommended)", "description": "A second question in the same dialog: BA, dev, QA or no one. Skipping it costs nothing."},
        {"label": "Rating only", "description": "Your rating counts for every agent of the cycle; the evidence decides who loses most."}
      ]
    },
    {
      "question": "What should a low score make an agent do?",
      "header": "Low score",
      "multiSelect": false,
      "options": [
        {"label": "Self-review + stricter QA (Recommended)", "description": "Its report must carry a self-review its own stop checks; QA must try counter-examples on a low-scoring dev's work."},
        {"label": "Self-review only", "description": "Only the producer's own self-review, checked when it stops."},
        {"label": "Warning only", "description": "It sees its score and reason at each dispatch; nothing else changes."}
      ]
    }
  ],
  "metadata": {"source": "plan-decision:D28-design"}
}
```

**不问 owner、按规则决定的（D10、D18）**：
- 出题人是 BA；
- 分数按项目算；
- 旧行不计分；
- agent 看得到分数的数字；
- 分值、阈值，以及注入和显示通道由 §5 的实验决定；
- /dev-command 和 /redev 与 /dev 相同（D22，以及"变体命令只写它和 /dev 的差别"）。

**如果 owner 没有回答**：每题取推荐项（D18）。

## 8. 阶段划分

见 `phase-prompt.md`：P13-1 需求提问轮；P13-2 评分事件和 owner 视图；P13-3 派发视图和后果。每个约一天，交给不同的账号（D26）。

- P13-1 和 P13-2 可以并行。它们只共用 AskUserQuestion hook 这一个文件：P13-2 只改其中 close-rating 那一支。后合并的那个先合入 origin/master，保留双方的行为（FAST-TRACK 的合并规则）。
- P13-3 在两者都合并之后开始。
