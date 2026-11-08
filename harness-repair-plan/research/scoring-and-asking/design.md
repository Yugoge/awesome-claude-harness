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
  - 轮数不设上限（D29）：只要还有需要 owner 决定的点，BA 就再出一轮，直到任务彻底清楚；已回答过的题不再问。/dev 从一个完成的 /spec 出发时规则相同。
  - /dev-overnight 里结构上开不出 /spec 或 /dev 区间，P2 对 AskUserQuestion 的拒绝再兜一层（§2.8）。
- **(b) 评分。**
  - 分数事件只由 hook 从事实中写出，追加进现有的 `logs/lifecycle.jsonl`，由一个写函数完成。
  - 分数不存储：读的时候由纯函数现算，没有新的状态文件，也没有计数器。
  - agent 在 SubagentStart 时看到自己的分数和档位（score-inject.sh 的六档），以及随档位不同的提醒，不超过 3 行（D29）。
  - owner 打分之后，看到趋势、最差的 agent 和原因。/close 只问评分这一个问题（D29）。
  - 分数只改变派发时的提醒：不在生产者停下时设门，也不让 QA 变严（D29）。
  - /close 和 /commit 不加任何检查。
- **(c) 新阶段 P13。** 排在 P12 之后、P11 之前，拆成 P13-1、P13-2（各约一天）和 P13-3（约半天），按顺序合并（`phase-prompt.md`）。
- **在途工作必须先改的地方**（§6）：
  - PR #16（P9）在快照提交 6c4c0d1 里删掉了全部评分代码，必须逐块恢复；
  - PR #12（P4）满足 D28 第 2 条，但审阅者的两条中等级别意见在 31dbb18 上还没修；
  - 规划文件 `prompts/short/P9.md` 的 R10-R13 和 `SPLIT-PLAN.md` 的 P9-7 仍写着"退役"，由审阅者改，本次不碰。
- **owner 的四个选择**已在 D29 回答，本文已按回答修改，见 §7。其余选择按 D10、D18 由规则或实验决定。

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
  3. hook 要求恰好一个问题（`[question] =` 解包）。D29 不加第二问，这一点不用改。
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
4. PostToolUse hook 读 CLI 的 `tool_input` 和 `tool_response`。这次调用的题目与题目文件一致（§2.6 的第三条），并且有用户内容（answers、response、annotations 任一非空）时，就写 `docs/dev/requirement-answers-<task>-r1.json`（§2.5）。题目被改过的调用、Skip、超时、拒绝什么也不写。
5. 主代理派发 **BA analysis**，输入是答案文件的路径（或者"无答案"）。
   - BA 写 context、ticket、acceptance-criteria。
   - 每个已回答的问题都要映射进 `context.requirement.contract_refs`，即 `{answer_ref: "r1.q2", criterion_ids: [...]}`。
   - 每个没回答的问题，按它的 `assume` 选项写进 `assumptions`。G2 在 BA analysis 停下时检查这两项都齐。
6. 只要还有需要 owner 决定的点，BA analysis 就不写分析产物，而是写 `requirement-round-<task>-r2.json`，回到第 3 步。轮数不设上限（D29），见 §2.9。
   - 这和今天的 producer question 一样：G2 接受一个新鲜、合格的 r<n+1> 来顶替该派发声明的产物，写门也允许该派发写它（P5:hooks/subagentstop-artifact-contract-enforce.py:453-457；P5:hooks/pretool-tool-policy.py:14-15）。
   - 否则 BA analysis 要么写不了 r2，要么在停下时因缺少声明的产物被拦。
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
  "questions": [
    {"id": "q1", "dimension": "intent", "header": "Goal", "spec_ref": null,
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
- 有 spec 时（/dev 从一个完成的 /spec 出发），规则相同（D29）：至少 1 题，每个需要 owner 决定的点都要问，不设上限。`spec_ref` 指向题目追问的那一节 spec，点不在 spec 里时为 null。`spec_ref` 是每题的字段，不放在顶层。
- **已回答过的题不再问（D29）。** 如果一道题的规范化题干与本任务（以及 /dev 所依据的 spec）的某个答案文件里已回答的题相同，G2 拒绝。
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
- **只有和题目文件一致的那次提问才写契约。** 题目被改过或换过的调用不写，因此 owner 对主代理自拟题目的回答不会成为契约。之后派发门要求按原题再问（§2.6）。每个文件以第一次一致的提问为准。
- **producer question 用同一条规则。** source 为 `producer-question:<task>:<role>`，答案写到 `docs/dev/producer-answer-<task>-<role>-<q8>.json`。q8 是问题文件 sha256 的前 8 位，所以同一个角色在一个任务里先后提的几个问题各有各的答案文件。producer-question.v1 的形状和 AskUserQuestion 不同，所以这里只要求 source 匹配。今天这类答案只活在再派发的提示词里（§1.2）；改过之后，每个 owner 的回答都是原话产物。
- **谁能写。**
  - 没有任何派发会声明这些路径，所以 P1b 的派生写权限会拒绝子代理写它们。
  - 主代理要另加一条：写门（tool-policy）把 hook 自有的路径列为任何 agent 都不能写，Write、Edit、Bash 重定向都算。这些路径是 `docs/dev/requirement-answers-*`、`docs/dev/producer-answer-*` 和评分日志。
- **消费者。** BA analysis（必读，G2 检查 contract_refs）；QA（验收标准连回答案）；spec agent 的 Finalize；P13-1 把题目和答案文件加进 resolver 的 `commit_whitelist_artifacts`，/commit 的白名单把它和任务的其它产物一起提交。
- **为什么不只用 transcript。** transcript 才是最强的原话来源，但它会被清理，而且是会话级的，/close 和 /commit 常在另一个会话里跑（P4 "Out of scope, found"）。所以契约要落在项目的 docs/dev 里。

### 2.6 hook 怎么强制"问过"

**判定（一个函数，和评分的判定共用）。** `asked(span, source, file)` 为真，当且仅当区间内有一次主代理的 AskUserQuestion tool_use 满足以下三条（第三条只对 requirement-round 文件）：
- `input.metadata.source == source`；
- 有一个 tool_result，内容不限，`is_error` 也算；
- `input.questions` 的规范 JSON，等于题目文件里去掉 id、dimension、assume、spec_ref 之后的内容。

producer question 只看前两条：它的 schema 只有一个决定加 default，转问时 default 还会被标成推荐项，内容本来就对不上。

第三条保证主代理不能改写题目、替换题目或混进技术选择。这个函数放在 hooks/lib，读 transcript 的方式与 P4 的 `close_rating.rating_asked` 相同；P13-1 让 `rating_asked` 改为调用它，评分和提问从此共用一个判定。

**规则（放在派发门，与 G1 同一个 PreToolUse Agent 门）。**
1. **先问后派。** 在一个 /spec、/dev、/redev、/dev-command 区间里，只看本区间的任务（不管 overnight 家族的问题文件，D20）。如果一个题目文件（requirement-round 或 producer-question）满足 schema，且声明它的那次派发正常返回，但还没满足 `asked`，就拒绝该任务的其它派发。声明同一个文件的再派发（用来修它）永远放行，所以写坏的或被中断的 intake 可以重做。拒绝信息是：
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

- r1 必问（D28）。
- 没有上限（D29）："直到整个任务彻底清楚"。只要还有需要 owner 决定的点，BA analysis 就再写一轮；没有这样的点时，才写分析产物。schema 的 `round` 没有最大值，代码里没有轮数上限，也没有计数。
- 已回答过的题不再问，由 G2 检查（§2.4）。跳过的题按它的 `assume` 定下来，记进 assumptions，不再追问：owner 跳过，就是接受了这个默认（D9b）。
- 没有死路（D25）：每一轮都要 owner 作答或跳过才会有下一轮，而 BA 只为需要 owner 决定的点出题，所以循环随 owner 的回答收敛。

### 2.10 D24：(a) 的产物

| 产物 | 生产者 | 决定性的消费者 |
|---|---|---|
| `docs/dev/requirement-round-<task>-r<n>.json` | BA（intake 或 analysis 派发声明它） | 主代理照抄去问；派发门的 `asked` 比对；答案 hook 记它的 sha256 |
| `docs/dev/requirement-answers-<task>-r<n>.json` | PostToolUse AskUserQuestion hook | BA analysis（G2 检查 contract_refs）、QA、spec Finalize、/commit 白名单 |
| `docs/dev/producer-answer-<task>-<role>-<q8>.json` | 同一个 hook | 被再派发的生产者 |
| `context.requirement.contract_refs` 与 `assumptions` | BA（已有产物里的新字段） | G2、QA |

---

## 3. (b) 驱动 agent 的评分系统

### 3.1 原则

1. **只记事实，不记自评。** 事件由 hook 从别人产出的事实里得出：CLI 记录、别的 agent 的报告、代码的判决、owner 的回答。被评的 agent（包括主代理）不能写日志。
2. **分数现算，不存。** 分数、档位、趋势都由读时的纯函数从只追加的日志算出。没有分数字段、计数器或放行标志，也没有新的状态文件。
3. **按项目算。** 每行带 `project`，取 git 根身份的 sha256 前 12 位，不含个人值。这修掉了"项目 A 的评分改变项目 B 的提示词"这个缺陷（H-scoring §2.1）。
4. **滚动窗口、能回升。** 窗口取最近 10 个任务。分数上限 100、没有下限，所以 score-inject.sh 的 Disgraced 档（低于 0）仍然够得着（D29）。但只看窗口里的任务，所以不会像旧系统那样一路累积、再也回不来。
5. **派发时说得短。** 不超过 3 行、400 B，由 hook 注入，不靠主代理的文字。
6. **后果是提醒，不是门（D29）。** 分数只改变派发时 hook 给出的提醒，按档位不同。它不拦生产者的停止，不让 QA 变严，也不进 /close 或 /commit。

### 3.2 事件：哪个事实给哪个 agent 记分

所有事件都由同一个观察者 hook 写出：P13-1 推广后的 AskUserQuestion hook，P13-2 给它加上 matcher `Agent`，所以注册是 PostToolUse `AskUserQuestion|Agent`。它只记录、从不拦，是评分日志和答案文件唯一的写进程。
- 在 PostToolUse(Agent) 这一刻，所有 SubagentStop 门都已放行，obligation、subagent_type 和最终回复同时可见（研究通道 F）。这是最好的观察点。
- 观察者不重算 G2 的结论，否则 G2 的判决会有第二个生产者。它只读已经落地的产物和 CLI 记录。

| 事件 | 事实来源 | 记给谁 | 初始分值（最终由实验定，§5） | 去重键 |
|---|---|---|---|---|
| `qa_first_pass` | lane QA 第一轮 `qa.status = pass` | 该 lane 的 dev +2，ba +1 | | QA 派发的 tool_use_id |
| `qa_fail` | lane QA `fail`，看 `primary_cause` | `dev_implementation` 记 dev -4；`ba_spec` 记 ba -4；`qa_oversight` 和 `environment` 不记 | | 同上 |
| `qa_catch` | 一次 QA 失败之后，dev 的再派发改动了失败项 `location` 指名的文件，随后同一 lane 通过 | qa +1，每个任务最多 +2 | | 通过那次的 tool_use_id |
| `escaped` | close-QA 给出 `CLOSE_FINDINGS`，而 lane QA 已通过；finding 引用的产物用 `declaring_dispatch` 找到角色 | 该角色 -5；该 lane 的 qa -3 | | tool_use_id 加 finding 序号 |
| `close_catch` | 上一行的 finding 被引用产物的生产者在后一轮修好，close 随后落地 | close-qa +1 | | finding 的去重键 |
| `rerun_gap` | 同一 (task, lane, role, 声明路径) 的第 k 次派发（k ≥ 2），起因是缺失或不合格的产物；起因是 QA 失败、close finding、澄清或瞬时 API 错误的不算 | 该角色每次 -2 | | 重派的 tool_use_id |
| `stop_blocked` | G2、e2e、codex 拦下该派发的停止；**只在 transcript 里能测到时才启用**（§5） | 该角色每次 -1，每次派发最多 -3 | | agent_id 加门代码 |
| `main_refused` | 区间里主代理的一次工具调用被门拒绝：tool_result 出错，内容带门代码（ASK_FIRST、G1、写门等） | main 每次 -1，每个区间最多 -5 | | 记录的 uuid |
| `main_stop_blocked` | Stop 门拦下主代理的停止；能测到才启用 | main 每次 -1，每个区间最多 -3 | | 记录的 uuid |
| `rating` | owner 评分 5/4/3/1 | 该任务所有有派发记录的角色和 main：+3/+1/-3/-6 | | 规范化的 task id，只在评分行之间去重 |

- 分值按事件给，角色从事实里得出：派发记录、`declaring_dispatch`、`primary_cause`。没有"文件名到角色"的表（D21）。
- 规则：一次重派只记一个原因。QA 失败已经在 `qa_fail` 记过，close finding 已经在 `escaped` 记过，都不再记 `rerun_gap`。
- 主代理的事件，由观察者在下一次 Agent 回来时，回扫从上一个观察点到现在的区间片段。区间末尾、之后再没有派发的那一段扫不到，这是已知的缺口，写进 "Out of scope, found"。
- **记分身份**取 obligation 的 role，只有一个例外：pipeline 为 close 的 qa 记为 `close-qa`。close-QA 和 lane QA 是同一个 agent 定义；如果合在一起记分，close-QA 找到问题会让"qa"自己扣分（`escaped`），它就有动机什么都不找。分开之后，lane QA 为漏掉的问题负责，close-QA 为找到并被修好的问题得分。
- 不设"close 干净就给分"的事件，原因相同：那会奖励 close-QA 少找问题。

### 3.3 分数怎么算（纯函数）

`score(identity, project, as_of)` 的算法（identity 即 §3.2 的记分身份）：
- 取 `project` 相同、`ts < as_of` 的事件行和评分折算行，在属于该身份的行里找最近 10 个不同的 task_id。
- `raw` 是这些行的分值之和，`score = min(100, 50 + raw)`，没有下限。
- 没有任何行的身份记为"新"，分数 50，落在 Skilled Craftsman；派发时只显示一句"no record yet"加该档的提醒。
- `trend = score(as_of) - score(窗口往回挪 5 个任务)`。
- 档位就是 score-inject.sh 的六档（D29）：Disgraced（低于 0）、Apprentice（0-20）、Journeyman（21-40）、Skilled Craftsman（41-60）、Senior Craftsman（61-80）、Master（81-100）。档位的边界和名字搬进 score_log，一个归处。
- `as_of` 取当前命令区间开头那条人类提示的时间。SubagentStart 注入器和主代理行用同一个 `as_of`、同一个函数，所以同一命令里看到的分数一致。当前命令里新发生的事件，影响的是下一个命令。
- **旧行**（9 键、没有 `kind` 的行）照读不报错，但不计分。P4 留下的 4 键评分行没有 `project`，同样不计分。日志本身保留，作为历史。

### 3.4 派发时 agent 看到什么

由 SubagentStart hook 注入 `additionalContext`（官方文档写明的通道），一律英文，不超过 3 行、400 B。/close、/commit、/merge、/push 区间里的派发不注入，/close 和 /commit 保持不受评分影响。示例：

```
Your record (dev, this project, last 10 tasks): 38 [Rank: Journeyman, 21-40], trend -9.
Most frequent miss: QA failed your work for "edge case not tested" (3 of last 5 tasks).
Reminder: your work failed review more than once lately; check the miss above against every criterion before you stop.
```

- 每个档位都用同样的三行：分数、档位和趋势；最常见的失误（还没有失误时省略这一行）；该档位的提醒（§3.6）。
- 原因用的是事件的 `why`：QA 失败的 `issue`，或 finding 那一行，截到 80 字符。不用 task id，task id 对 agent 没有可操作的信息（H-scoring §2.4）。
- 主代理在 /spec 和 /dev 系列命令开头，由 UserPromptSubmit 的 additionalContext 收到一行：
  `Your record (main): 74 [Rank: Senior Craftsman, 61-80]. Most frequent miss: dispatch refused ASK_FIRST (2 of last 5 tasks).`
- 这些取代：`score-inject.sh` 每次约 1.2 KB 的输出、主代理三次 Bash 注入调用（它们还会撞上 5 次 Bash 的上限）、三份回显合同。而且覆盖 /dev、/redev、/dev-command 和 overnight 的所有派发，不再只有 /dev。

### 3.5 /close 之后 owner 看到什么

由 AskUserQuestion 观察者处理 `close-rating:` 来源时给出。首选 `systemMessage`（显示给用户，要先测，§5）。后备是 additionalContext，让主代理原样贴出：主代理只转贴 hook 写好的文字，不算、不改、不写任何东西，这是 D28 唯一允许的转贴（§6.2）。不超过 5 行：

```
Scores (this project, last 10 tasks): ba 67 Senior (+2) | dev 38 Journeyman (-9) | qa 56 Skilled (-4) | main 80 Senior (0)
This cycle 20261108-101500: dev -4 (QA fail: edge case not tested), qa +1 (caught it), your rating 4: +1 each
Worst: dev (Journeyman). QA failed its work in 3 of the last 5 tasks; its next dispatches get the Journeyman reminder.
```

- **互动性有两处：**
  1. owner 打完分立刻看到这一分带来的变化；
  2. 排名最差的 agent 下一次派发就看到自己的档位、原因和该档位的提醒。
- 对话框只问评分这一个问题，不问"哪个 agent 最需要改进"（D29："没有意义"）。
- 如果 PostToolUse 在 Skip 时也触发（要测），照样显示分数，只是没有本次评分那一行。
- `--auto` 下有多个父任务时，每次评分各显示一次。
- /close 本身不读日志、不算分、不加任何步骤。close.md、commit.md、changelog-analyst.md 和它们调用的脚本都不碰评分日志。摘要来自 hook，不来自 /close 的文字。

### 3.6 低分的后果：按档位不同的提醒（D29）

owner 选了以前的设计："agent 看得到自己的分数，不同的分数给 agent 不同的提醒"。提醒在派发时由 SubagentStart hook 给出（§3.4），所以一定会出现，不靠主代理的文字。档位用 score-inject.sh 的六档：

| 档位 | 分数 | 提醒（英文，一行；最终措辞由 P13-3 定，放在 score_log 里） |
|---|---|---|
| Disgraced | 低于 0 | `Reminder: your work keeps failing review; re-check every acceptance criterion against the code and say which ones you could not verify.` |
| Apprentice | 0-20 | `Reminder: your work often fails review; re-read the requirement and the acceptance criteria before you start, and test each criterion.` |
| Journeyman | 21-40 | `Reminder: your work failed review more than once lately; check the miss above against every criterion before you stop.` |
| Skilled Craftsman | 41-60（新身份从 50 开始） | `Reminder: an average record; the miss above is the one to avoid this time.` |
| Senior Craftsman | 61-80 | `Reminder: a good record; keep the checks that earned it, the miss above is the exception.` |
| Master | 81-100 | `Reminder: an excellent record; do not cut corners to stay fast, one escaped defect costs more than a task earns.` |

- **只是提醒（D29）。** 不要求任何字段，没有停止门，没有读分数的门，QA 也不因分数变严。原设计里"生产者停下时的 self-review 门"和"低分时更严的 QA"已撤回。
- **措辞只说事实和下一步。** 不用威胁口吻；旧 score-inject.sh 里"惩罚远超任何其它事件，且不可逆"那类话不再用（H-scoring §4：威胁式措辞容易引出夸大的自报）。
- **回升。** 窗口滚动，档位随分数自动变化。没有人工放行，也没有状态。
- **没有死路。** 提醒不拦任何东西，P1c 的 dead-end 检查不会多出阻塞点。

### 3.7 单一生产者与存储

- **一个库，一个写函数。** `hooks/lib/score_log.py` 合并现有的读者（T:scripts/lib/score_log.py）和 P4 的 `close_rating.append_row`，提供：
  - `read_lines`、`append`（调用方持锁，首写胜，按 key 去重）；
  - `score`、`tier`、`render_dispatch_line`、`render_owner_summary`。
- **一个写进程。** 只有 PostToolUse `Agent|AskUserQuestion` 观察者调用 `append`。
  - `score-update.sh` 随它的最后一个调用者（dev.md Step 14）在 P13-3 一起删掉，`permissions.allow` 里的条目也删掉。
  - 在那之前，旧的 `scripts/lib/score_log.py` 留一行转出，`close_rating.append_row` 留作原样写行的委托，让 dev.md 里仍在跑的 score-inject 和 score-update 不坏。它们写出的旧格式行不计分。
  - 写门把日志路径列为 hook 自有。
  - 这样 P4 留下的"一个函数、两个进程"问题和"任何 agent 都能写分"问题一起解决。
- **行格式。** 在现有日志里加 `kind`：
  - `{"kind": "event", "ts", "project", "task_id", "role", "event", "points", "key", "why", "ref"}`
  - `{"kind": "rating", "ts", "project", "task_id", "rating", "roles", "tool_use_id"}`：`roles` 在写入时从任务的派发记录读出，读分数时就不必跨会话扫描
- **评分去重。** 只在 `kind == "rating"` 的行之间按规范化 task id 去重，修掉 §1.3 的第 2 条。
- **并发。** 沿用 flock。扇出的多个 lane 并行回来时，20 个并发 append 得到 20 行，互不交错。
- **耗时。** 观察者要读 transcript 和 obligation，放在 PostToolUse 观察 hook 里，不放进安全门；设短超时并实测（hooks-audit §7.3 "超时预算"）。

### 3.8 防作弊

- 被评者写不到事实：父 transcript 由 CLI 写；QA 报告的派生写权限只给 QA；close-QA 由别人派发；owner 评分只认 CLI 的 tool_response。
- 日志、答案文件只能由 hook 写，写门拒绝所有 agent 写它们。
- QA 用 `primary_cause` 归咎是一面之词。对冲办法有两个：`escaped` 会同时罚 lane qa；`qa_catch` 只在 dev 的再派发改动了失败项 `location` 指名的文件之后才给，所以 QA 乱判一次失败、dev 随便改一个文件，QA 拿不到分。这挡不住 QA 把 dev 冤枉成 `dev_implementation`，剩下的风险由 owner 评分兜底。

### 3.9 旧代码的去留

D28：评分系统重新设计，不移除。P9 不删任何评分代码。P13 在新实现接上的同一个子阶段里删除被取代的部分（D17，附可达性证明）。

| 现有部分 | 去向 | 子阶段 |
|---|---|---|
| `scripts/lib/score_log.py` | 搬到 `hooks/lib/score_log.py`，并入 append 和计分；原处留一行转出，P13-3 删除 | P13-2 |
| `close_rating.py` | `rating_asked` 改调共用的 `asked`（P13-1）；写入改调 score_log，`append_row` 留作委托到 P13-3；去重修好；加摘要（P13-2） | P13-1、P13-2 |
| `score-update.sh` | 删除：它的调用者（dev.md Step 14）同时删掉；agent 不该能写分 | P13-3 |
| `score-inject.sh` | 删除：SubagentStart 注入器取代它，六个档位搬进 score_log | P13-3 |
| `close-scoring-decide.py` | 删除：P4 起已无调用者；close_* 在 D7 下是常量 | P13-2 |
| agent front matter `score:` | 删除：分值按事件放在 score_log 里，一个归处 | P13-3 |
| 三份回显合同 INJECTION_PROOF | 删除：换成 SubagentStart 注入的分数、档位和按档位的提醒（D29） | P13-3 |
| dev.md 注入块、占位符、Step 14 评分、"Mascot Score Changes" 表、:93 的批处理理由 | 删除 | P13-3 |
| 两个评分 shell 测试 | 和它们测的两个脚本一起删除，覆盖由 pytest 接替（在 CI 里） | P13-3 |
| `logs/lifecycle.jsonl` 里的旧行 | 保留，不计分 | — |
| prompt-purity 的 OPTIONS_XML 分类 | 这是提问执法，不是评分；P9 删除它可以保留 | P9 |

### 3.10 D24：(b) 的产物

| 产物 | 生产者 | 决定性的消费者 |
|---|---|---|
| `logs/lifecycle.jsonl` 的 event 和 rating 行 | `score_log.append`，只有 PostToolUse `Agent\|AskUserQuestion` 观察者调用 | SubagentStart 注入器、UserPromptSubmit 主代理行、owner 摘要 |

---

## 4. 否决的方案

- **主代理出题或转述答案**：违背 D8 和只编排规则；技术选择会不经检查混进来；转述会丢掉原话。
- **把题目和答案写进 context.json 或 spec**：hook 一写就成了第二个生产者（D24）；BA 的两次派发还会撞上"Write 不能覆盖已有文件"和 G2 的新鲜度规则（P4 "Out of scope, found"）。
- **在 Stop 门检查"问过"**：管不了顺序，也管不了 /spec（§2.6）。
- **把分数存成字段或文件**：违反"不加可变状态"；会饱和；会被改。
- **按"文件名到角色"的表归因**：D21 禁止。
- **owner 摘要由 /close 读日志生成**：等于在 /close 加检查（producer-side 原则，P4 的 DO NOT）。
- **用 PreToolUse `updatedInput` 改派发提示词注入分数**：文档没写 Agent 的规则，同事件并行时谁的 updatedInput 生效也不确定。只作 SubagentStart 测不通时的后备（§5）。
- **按 owner 评分直接重罚**（旧表 1 星 dev -40）：会饱和，失去信息。改为滚动窗口。
- **生产者停下时的 self-review 门、低分时更严的 QA、评分时的第二问**：owner 在 D29 选了以前的设计，只按档位给提醒，对话框只问评分。

## 5. 风险，以及要做的实验（D18：每项做一次实验，记下结果后照结果执行）

| 问题 | 实验 | 测不通时的后备 |
|---|---|---|
| SubagentStart 的 additionalContext 真能到达子代理 | 静态读 CLI 包；在回放里看注入的位置 | 用 PreToolUse(Agent) 的 `updatedInput` 追加到提示词末尾，要在派发门的所有规则放行之后 |
| PostToolUse 的 systemMessage 是否显示给用户 | 静态读 CLI 包的 PostToolUse 输出处理 | additionalContext，让主代理原样贴出 |
| AskUserQuestion 在 Skip、拒绝、超时时是否触发 PostToolUse | 静态读加回放 | 摘要只在有答案时显示；契约和评分不受影响 |
| 工具不可用时（headless、dontAsk），transcript 里是否仍有 tool_use 加出错的 tool_result | 静态读 | 加一个只读的 CLI 事实，例如 init 记录里的工具列表，满足时才要求提问；不能靠 agent 自称 |
| SubagentStop 被拦时，子代理 transcript 里是否留下可识别的记录（`stop_blocked`），Stop 被拦时主 transcript 里是否留下记录（`main_stop_blocked`） | 静态读加回放 | 这两个事件不启用，写进 "Out of scope, found" |
| 分值 | 用固定日志回放：dev 3 个任务里 QA 失败 2 次，应掉一档；接着连续 3 个干净任务，应回到原档；一串失败的任务能把分数压到 0 以下（Disgraced），窗口满了之后不再往下掉 | 调整分值，把选定的值和关键数字写进 PR |
| 观察者耗时 | 在扇出回放中测 p95 | 把 transcript 扫描限制在本区间之内 |

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
- P4 的 DO NOT"让主代理……echo a rating, score"在 D28 下基本成立：主代理不算、不写、不解析分数。唯一的松动是 §3.5 的后备：如果 systemMessage 显示不出来，主代理原样转贴 hook 写好的摘要。

### 6.3 PR #10（P2）、PR #14（P5）、P12

- **P2**：overnight 的拒绝保持现状，P13 只依赖它。`_unattended` 是私有函数，P13 不需要调用它（§2.8）。
- **P5**：P13-1 往 Stop 门加文本问句规则，作为对 /spec 和 /dev 系列区间的一个谓词；门的尾注已经写着 "Ask with AskUserQuestion only for a real decision"。P5 和 P4 合并后，评分判定要用真的 close_rating 跑一遍（P5 现在用的是 fake，P5 报告 §6）。
- **P12**：L3 把 agents 的共享块搬进 `agents/shared/`，L5 把门合并成"一事一门"。P13 的 prompt 只按功能指名（"G1 所在的派发门"、"生产者的停止门 G2"、"PostToolUse AskUserQuestion hook"），不写文件名。P13 新加的 prompt 文字要通过 L6 的 CI 检查。

### 6.4 规划文件（由审阅者改，本次不改）

- `prompts/short/P9.md`：R10-R13、标题、:10-11 的依赖、D9a 和 D17 两行、A11、A12、A19 的 score-inject exit 127、A24、DO NOT :293、:298。
- `SPLIT-PLAN.md` 的 P9-7 和 :249。
- `FAST-TRACK.md` 的合并顺序：在 P12 之后、P11 之前插入 P13。

---

## 7. owner 的选择（D29 已回答）

§7 的四个问题以一次 AskUserQuestion 提出，owner 的回答记在 DECISIONS.md 的 D29。本文已照回答修改：

| 问题 | 提供的选项 | owner 的回答（D29） | 本文的改动 |
|---|---|---|---|
| Rounds：开工前最多问几轮 | 1 + 至多 2 轮 / 恰好 1 轮 / 不设上限 | "没有任何限制，直到整个任务彻底清楚" | §2.9：不设上限；已回答过的题不再问 |
| After /spec：/dev 从完成的 /spec 出发时问什么 | 只问没写清楚的 / 四个维度全问 | "一样的，没有限制，只要是需要用户决定的" | §2.4：至少一轮，每个需要 owner 决定的点都问，不设上限 |
| Blame：评分时是否问哪个 agent 最需要改进 | 可选的第二问 / 只问评分 | "没有意义" | §3.5：/close 只问评分 |
| Low score：低分让 agent 做什么 | self-review 加更严的 QA / 只要 self-review / 只给提醒 | "以前的设计，agent 看得到自己的分数，不同的分数给 agent 不同的提醒 hook" | §3.4、§3.6：按 score-inject.sh 的六档给提醒；没有停止门，也没有更严的 QA |

**不问 owner、按规则决定的（D10、D18）**：
- 出题人是 BA；
- 分数按项目算；
- 旧行不计分；
- 分值，以及注入和显示通道，由 §5 的实验决定；
- /dev-command 和 /redev 与 /dev 相同（D22，以及"变体命令只写它和 /dev 的差别"）。

## 8. 阶段划分

见 `phase-prompt.md`：P13-1 需求提问轮；P13-2 评分事件和 owner 视图；P13-3 派发时的分数、档位和提醒。P13-1、P13-2 各约一天，P13-3 约半天，交给不同的账号（D26）。

三个子阶段按顺序进行：它们共用 AskUserQuestion hook、close_rating、回放驱动（dev、dev_command、spec、close 和子代理模拟器）以及 ENFORCEMENT-LEDGER，并行只会制造冲突。
