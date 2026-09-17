# 控制器实测缺陷记录 — 2026-09-06

记录人:`/paseo-daemon` 控制器会话 `5805a4d1`(原生 `0a0db999`)。
测量窗口:2026-09-06 15:12Z – 15:57Z。

本文件刻意放在 `docs/reference/`(已跟踪)而非 `docs/dev/`(gitignored)。
后者不随推送上车,写在那里的缺陷记录在远端不存在。

**证据分级贯穿全文,不做平滑:**

- **[实测]** = 控制器本人在上述窗口内直接测得,命令与输出在本会话可复现。
- **[转述]** = 被管会话报上来、控制器**未**独立复验。转述项一律标出来源会话。

分级本身就是本文件的一部分。今晚控制器已有六次把未核实内容当事实陈述,
其中一次陈述的是自己下属是否在干活。下级会复算控制器交下去的数字,
控制器没有复算下级交上来的数字 —— 这个不对称是这份记录存在的原因之一。

---

## 一、监控面缺陷

### D1 [实测] agent 列表静默剥离账号限定符

`list_agents` 报告会话模型为裸 `claude-opus-5`;同一 agent 的权威配置
`config.model` 为 `claude-opus-5@yugetang`。而 `claude-opus-5@orchestrade`
在 `list_models` 中标记 `isDefault: true`。

监工读列表 → 拿裸名去比对默认值 → 得出"该会话计费在 orchestrade"
—— **而它实际计费在 yugetang**。

同一条 agent 记录内部三个字段互相矛盾:

| 字段 | 7ba38627 | 926d1cda | 5c56779e |
|---|---|---|---|
| `config.model` | `claude-opus-5@yugetang` | `claude-opus-5@yugetang` | `claude-opus-5@yugetang` |
| `persistence.metadata.model` | `claude-opus-5@yugetang` | `claude-opus-5@yugetang` | `claude-opus-5@yugetang` |
| `runtimeInfo.model` | `claude-opus-5`(丢限定) | `claude-opus-5`(丢限定) | `null` |

**后果:监控面上的静默账号错配,直通违反用量地板。**
控制器本人差一步就据此做出调度决定。

### D2 [实测] 注意力标志是闩锁,却被当作状态呈现

`7ba38627` 的记录同时持有:

```
requiresAttention : true
attentionReason   : "finished"
attentionTimestamp: 2026-09-06T14:45:11.682Z
status            : "running"
lastActivityAt    : 2026-09-06T15:14:56.409Z
```

`attentionTimestamp` **早于** 促成其后约三十分钟真实工作的那条监工指令
(发出于 14:45:37Z),期间包含一整轮 27.5 分钟的 QA。
标志在完成时置位,**恢复工作时从不清除**。

同一小时内两名独立读者在两条不同会话上各自发现此现象
(`7ba38627` 与 `5c56779e`,后者 `attentionTimestamp` 14:38:41.828Z
对 `lastActivityAt` 14:59:43.964Z)。

**后果:** 监工若信任该字段,会被告知会话在其后确凿发生的工作之前就已完成。
控制器正是这样做的,并据此对用户断言两条会话已空等半小时 —— 两条都在连续工作。

### D3 [实测] 看门狗刷屏挤掉可观测窗口

请求最近 100 条 agent,返回约 96 条为看门狗(30 分钟一条)。
真实被管会话被挤出列表尾端。一条正在被监督的会话在列表中完全找不到,
最终靠文件系统定位。

### D4 [实测] `update_agent` 与 `get_agent_status` 对同一 agent 是否存在给出相反答案

同一分钟内,对 `5c56779e-a709-471e-a19a-67cb05d8900c`:

- `get_agent_status` → 返回完整快照,`status: "closed"`
- `update_agent`     → `Unknown agent '5c56779e-...'`

**与调度策略叠加后构成死锁:**

账本对耗尽账号的裁决是 `stop_or_switch`,且 `same_account_degrade_forbidden: true`
(禁止用同账号降级模型冒充解决)。但:

- **进程已退出时换号** → `Unknown agent`,不可变更;
- **进程运行中换号** → R36:SIGKILL 当前轮且永不重驱。

换号只在 `status: running` **且** `attentionReason: finished`(活着且空闲)
这一窄状态可行。**而耗尽常常伴随进程退出,恰是不可换号的那个状态。**

---

## 二、度量与信号缺陷

### D5 [实测] 磁盘满伪装成干净的空结果

`/tmp` 处于 4.0G、100% 占用、9567 条目的状态时,把读取命令重定向到该文件系统:

```
run1 exit=1 stdout_bytes=0 stderr_bytes=0
run2 exit=1 stdout_bytes=0 stderr_bytes=0
run3 exit=1 stdout_bytes=0 stderr_bytes=0
```

**退出码 1,标准输出 0 字节,标准错误也 0 字节 —— 没有任何诊断信息。**

把同一命令接入管道**看似成功**,因为下游读取者在写入落盘前就关闭了管道。
产生的空文件喂给账本,报 `JSONDecodeError: Expecting value: line 1 column 1 (char 0)`
—— 看上去完全像读取脚本的格式缺陷。

控制器最初据此判定"读取脚本有重定向缺陷"。**该判定是错的。**
同一命令对有余量的文件系统执行:`exit 0, 2598 bytes`。

**通用危害:100% 占用时,静默失败与合法空结果不可区分,
且下游每一次测量都继承它。** 一次几乎被写入缺陷记录的误判,
本身会污染缺陷记录。

### D6 [实测] 心跳通道长期处于未受信状态

`wake-status` 于 15:14Z:

```
missed_total            : 37
untrusted_minutes_total : 1682.33
trust_state             : "untrusted"
trust_reason            : "engine_policy_absent"
```

即通道已在无策略保护下运行约 28 小时。

### D7 [实测] 租约 TTL 违反其自身的节拍不变量

每次续约都输出:

```
WARNING: lease TTL 3600s violates the TTL/cadence coupling invariant:
required >= 6300s = (tolerated_missed_fires+1) x heartbeat_minutes x 60
                    + wake_slack_minutes x 60
```

配置的 TTL 短于系统声称可容忍的漏拍数所要求的下限。
**一次"被容忍的"漏拍就足以让租约静默过期。**
当日 14:57Z 的心跳即被记为漏拍,实证了该路径。

---

## 三、工作流与闸门缺陷

### D8 [实测] 待办追踪被永久锁死在某条命令的固定脚本上

控制器会话历史上执行过一次 `/do`,其待办列表此后被永久校验against
该命令的四步固定脚本。尝试追踪控制器自身的运营工作被拒:

```
BLOCKED TodoWrite (canonical validation):
  [1] Todo count mismatch: canonical has 4, submitted has 7
```

**常驻监督型会话无法追踪自己的工作。**

### D9 [转述:5c56779e] 流程定义的中间判决档在下游无表示

`/dev` Step 14 判定树**明确定义** `warning` 为编排器裁量点
(minor issues 可接受则进 Step 15,否则进 Step 16)。
下游产物解析器只接受两个值:

```
INVALID_QA_STATUS  qa.status is 'warning'; expected 'pass'
```

流程与闸门对判决空间的**基数**认识不一致 —— 不只是词汇不匹配。

**后果:编排器被文档赋予的裁量权不可行使。**
通过闸门只剩两条路:让判决真的变成 pass,或者改标签。
**后者正是本记录所编目的假绿类别。**

控制器对该会话下达的约束据此写明:修完若诚实结论仍是 `warning` 就报 `warning`,
不许为过闸改判;闸门缺一档是闸门的问题,不是判决该改的理由。

### D10 [转述:5c56779e] 一条在其所守护的转换中永不触发的 lint

对 per-criterion 状态字段的一致性检查,**仅在整体 status 等于 `pass` 时触发**。
在 fail→fail 转换下它结构上不可达,于是上一轮的陈旧 per-criterion 值存活下来,
与报告自身的叙述互相矛盾。

**与已记录的同族并列:**

| 实例 | 检查对象 | 为何问不出来 |
|---|---|---|
| `elif blockers:` | 阻断项集合 | 分支从不读 status |
| `baseline_dirty_snapshot` 等值判据 | 基线快照 | 串行派发下构造性不适用 |
| 本条 F11 | per-criterion 状态 | 仅在 pass 时触发,fail→fail 不可达 |

共同形态:**检查器度量的对象是对的,提问的时机让它永远问不出答案。**

### D11 [转述:7ba38627 的 QA 子代理] 机器解析的判决行承载自由散文

QA 报告被要求以恰好一个裸判决词作为最后一非空行,因为运行时解析器逐字读取该行。
交付文件的最后一非空行是判决词后接约两百字论证。

**解析器是前缀匹配还是精确匹配未确定。**
故记为规范符合性缺口,运行时后果未定 —— 不断言它导致了任何故障。

### D12 [转述:7ba38627] required-to-ship 集合 ≠ 周期交付面

控制器指示"提交路径限定到你声明的那 5 条"。该会话量出:

- **A = 5 条**(required-to-ship)
- **B = 33 条**(周期声明并集中相对 HEAD 有变化者)

按 A 字面执行会**提交测试却把被测代码留在工作树**
(`hooks/prompt-workflow.py`、`hooks/pretool-overnight-hook-guard.py`、
`scripts/create-overnight-state.sh` 正是两个原始需求的修复本体)。

**第三件更重:R1 的 gitignore 预检闸门修复不在 A 也不在 B**,
因为它属于另一份 spec 的授权;**而它正是让这次 close 跑通的东西**。

即:**本次绿灯依赖一份不会随提交上车的改动** —— 与第三轮 QA 判 bullet 3 FAIL
的理由是同一个缺陷形态(绿灯建立在不在发货树里的东西上)。

裁决:B 的 33 条本次提交,逐条归属;R1 修复单独一次提交按其自身 spec 归属。
"必须落地"不等于"必须落在这一次里" —— 混进来就造出一条归属不可追溯的提交。

### D13 [转述:d925b6ed] 修复车道用编造的 task-id 写产物

`docs/dev/dev-report-20260906-oel-repair.json` 由其修复车道写出,
使用了**编造的 task-id** 而非父任务的 id,造成一次真实的假阳性阻断。
因 gitignored 未上车,但会复发。

**与控制器自己编造 `20260906-092911-r60` 是同一缺陷的两端。**

---

## 四、一处已撤回的数字(控制器自身错误)

`docs/dev/specs/spec-20260904-harness-fixes.md` 第 415 行曾断言
**`44 pass 对 100 violations`**。

- **原值保留于此,不静默覆盖。**
- **偏差:** 该值在**任何**读法下都错,不只是在不便的那一种读法下。
- **实测替代值 [转述:d925b6ed,控制器未复算]:**
  带 `--git-root` 为 **47**,不带为 **64**。原值两者都不匹配。
- **来历:** `44` 溯源至 `style-inspector-report` 第 130 行,
  在那里它命名的是**另一个量**,该量已被 schema 约束消除。
- **加重情节:** 紧邻的第 414 行**已经记录过同一个数字出错一次**。
  第二次错误写在记录第一次错误的段落里。

引用扫描尚未完成 —— 该项列为未了。

---

### D14 [实测] 投递证明记不到它自己那一拍

控制器每拍都执行 `wake-observe --delivered --channel-id <id>`。三个连续 tick 的实测:

| tick(UTC) | 控制器动作 | `missed_fires` | `expected_next_fire` |
|---|---|---|---|
| 15:12 | 记录投递 | 1(14:57,该次确因用户禁用工具而漏) | 15:57 |
| 15:57:10 | **记录投递** | **0** | **15:57** ← 应为 16:12 |
| 16:12 | 记录投递 | **1 —— 记的正是 15:57** | 16:57 |

15:57:10 明确执行了 `--delivered`,**15:57 这一拍仍在下一 tick 被判为漏**。
投递证明未能归到它自己所属的那一拍;`expected_next_fire` 在该拍也未推进。

**后果:** 每拍必到的控制器仍持续累积漏拍计数。
可解释 D6 中 `missed_total: 37` 与长期 `untrusted` 状态 —— 漏拍数在度量记账,
而非度量心跳。**该缺陷使 D6 的数字本身不可作为通道健康度的证据。**

### D15 ~~[实测] 会话静默停止:无提交、无产物、无报告、无错误~~ **【已撤回 —— 见 D15-R】**

> **撤回声明。** 本条的核心断言「未写任何报告产物」**是错的**,且错在控制器自身的测量方法。
> 原文保留于下,不静默覆盖,因为这条错误本身是本文件所编目缺陷的一个实例。
> 撤回时刻:2026-09-06 16:22Z。撤回依据见 D15-R。

`7ba38627` 于 15:44:39Z 收到明确指令(两次范围限定提交,附 blob 相等性核对),
16:03:49Z 转为 `closed`。该十九分钟内:

- `git reflog` 最后一次提交为 **14:53:16 的 `be418621`** —— 区间内**无任何提交尝试**;
  【此条仍成立】
- ~~`docs/dev` 下**无 15:44Z 之后修改的文件** —— 未写任何报告产物~~;
  **【错误。搜索范围只覆盖 `docs/dev`,而产物写在 `docs/reference`。】**
- 暂存区仍只有并发会话的外来项(`abandoned-cycles-20260905.md`),未被扰动;
- 5 条声明路径均在工作树中(1 条未跟踪、4 条已修改),工作内容未丢失;
- 15:57 时上下文为 **479653/1000000,未耗尽**;
- 所在账号 `yugetang` 当时为 5 小时窗 27%、周窗 23%,两窗均在地板下。

**停止原因未确定。** 不断言为限额 —— 未取得该结论所需的证据,
而按规矩,监工不得读取被管会话 transcript,需委派子代理,
而子代理同样消耗已跌破地板的账号。**该缺陷因此与地板约束互锁:
诊断本身需要花费,而花费正是被禁止的那件事。**

值得单独记的是:会话消失时**未留下任何可供事后判读的痕迹** ——
无退出码、无错误产物、无部分完成报告。与 D2(注意力标志是闩锁)叠加后,
监控面上一条静默死亡的会话与一条已完成的会话**外观完全一致**。

---

### D15-R [实测] 周期产物横跨「被忽略」与「已跟踪」两个目录,范围受限的搜索会静默漏掉一半

D15 的错误结论来自控制器执行的这条搜索:

```
find docs/dev -newermt '2026-09-06 15:44' -type f     -> 0 结果
```

而实际产物在:

```
docs/reference/dev-cycle-20260809-013317/commit-attribution.json   38500 B   16:02:13Z
```

**该搜索在结构上不可能找到它。** 控制器据此宣布会话「未写任何产物、静默死亡」,
并将该结论写入本文件。**事实是:该会话在那十九分钟内完成了归属审计,
得出 12/16/5 的三分结论,提出四个它拒绝独断的范围问题,然后停下等待裁决 ——
完全按规矩办事。**

**真正的缺陷在此:** 同一个开发周期的产物被分散在两类目录:

| 目录 | git 状态 | 后果 |
|---|---|---|
| `docs/dev/` | 被 `.gitignore:142` 忽略 | 内容永不随推送上车 |
| `docs/reference/dev-cycle-<id>/` | 已跟踪 | 会上车 |

没有任何单一位置可以完整回答「这个周期产出了什么」。
按目录检索周期产物的人,**得到的答案取决于他碰巧选了哪个目录,而工具不会提示他只看了一半**。

**控制器自身的失误分列如下,不合并叙述:**

1. 用一个范围不覆盖目标的搜索,得出了「目标不存在」的结论 ——
   即本文件 D10 所编目的形态(仪器没测到它声称在测的东西),
   **发生在编写该目录本身的过程中**。
2. 同一轮里把 `grep -c .`(非空行数 764)当作行数报出,
   真实 `wc -l` = 1202,空行 438。接收方据该数字做出了一个结构性推论。
   **错误的数字向下游传播,并在下游长出了结论。**

### D16 [实测] 磁盘满使 agent 侧唯一的人类授权机制失效,且部分工作根本没有合规提交路径

尝试从 agent 上下文提交时:

```
PreToolUse:Bash hook error: [python3 "/root/.claude/hooks/pretool-git-privilege-guard.py"]:
BLOCKED: agent git commit - only the blessed /merge auto-bulk bridge or the /commit
wrapper may commit from an agent context.
Allowed pattern: ^auto-bulk: end-of-cycle commit for <branch>
For closed dev tasks, use /commit <task-id>.
For human-driven commits, exit the agent context and run git commit directly.
Main agent may bypass with /allow <pattern> before the git commit command.
```

闸门列出三条合规出路。**逐条实测,当前可用数为零:**

| 出路 | 实测结果 |
|---|---|
| `/commit <task-id>` | 该工作由 `spec-20260904-harness-fixes` R1 授权,**不绑定任何 dev 周期,不存在 task-id**。 |
| `/allow <pattern>` | 哨兵授权写入 `/tmp/claude-grants/<task_id>.json`。**`/tmp` 4.0G 已 100% 占满,写入探针返回 rc=1,0 字节可用 —— 新授权文件建不出来。** |
| 人类在 agent 上下文外直接提交 | 需要用户在场。 |

**两条独立缺陷在此交汇:**

1. **磁盘满静默吃掉授权通道。** `/allow` 的设计前提是能在 `/tmp` 建立哨兵文件;
   该前提在 100% 占用下不成立。**授权机制的失效不表现为「授权被拒」,
   而表现为「授权看似发出但闸门依旧拦截」** —— 与 D5 同族:
   资源耗尽伪装成别的东西。
2. **由 spec 授权、未绑定 dev 任务号的工作,没有任何 agent 侧合规提交路径。**
   两条正规通道一条要 task-id、一条要可写的 `/tmp`。
   本例中该工作**正是使当前周期闭合闸门得以通过的那份修复** ——
   即:让绿灯成立的东西,自身没有落地通道。

**受影响的具体待提交内容(已核实,等通道恢复即可用):**

| 路径 | 工作树 blob | HEAD blob |
|---|---|---|
| `hooks/pretool-gitignore-preflight.py` | `5fc00531bd6edf88fce6f0313435dfca5c72ef65` | `9088f5ed37a58aba8ef08e8a025766831549b3a8` |
| `hooks/tests/test_gitignore_preflight_close_contract.py` | `abf165d88bfa8657de21889b11b4994c8aad12a5` | 不在 HEAD(新增) |

自足性已验证:`HEAD + 仅这 2 文件` → **47 passed, 1 skipped, exit 0**。

#### D16 补充 [实测,16:3xZ 复测] 盘满只是成因之一,另有一种与磁盘无关的成因

用户于 16:3x 注入 `/allow git commit` 后,以**逐字相同**的命令重试提交,
闸门以**逐字相同**的输出再次拦截。此时:

```
tmpfs  4.0G  3.1G  959M  77%  /tmp
```

**`/tmp` 已回落至 77%、959M 可用,授权哨兵依然没有落盘。**
`/tmp/claude-grants/` 现有 9 条,全部为 `test-*` 测试夹具,最新一条 mtime 为
**15:36:47Z**,而该次 `/allow` 发生在 16:3x —— **无任何新条目产生**。

**因此本节标题所述「磁盘满使授权机制失效」只覆盖成因之一。**
存在第二种成因:在 `/tmp` 可写的情况下,`/allow` 仍未写出哨兵。
该成因的定位需要读取钩子源码,而钩子源码侦察是被明令禁止的路径,
**故本条止于现象记录,不作机制推断**。

#### 盘满成因的残骸证据(把推断升级为实证)

`/tmp/claude-grants/` 中三条 **0 字节**的 `.tmp.<pid>` 残留:

| 文件 | mtime | 大小 |
|---|---|---|
| `test-allow-absent-optional-settings.json.tmp.3668449` | 15:32:35Z | 0 B |
| `test-allow-absent-optional-settings.json.tmp.3678080` | 15:33:29Z | 0 B |
| `test-allow-absent-optional-settings.json.tmp.3764570` | 15:36:46Z | 0 B |

三条时间戳**全部落在 `/tmp` 100% 占满的窗口内**;写入器采用
「先写临时文件、再改名」的模式,而这三条临时文件**大小为零且从未被改名**。

这是盘满导致写入失败的**直接残骸证据**,不再是从「`/allow` 未生效」
反推出的推断。同一目录下 2026-07-20 另有 5 条同形态 0 字节残骸,
说明该失败模式**可重现且长期存在,只是此前无人将其与授权失效关联**。

---

### D17 [实测] `check-owned-edits-ledger.py` 缺 `--git-root` 时整个 replay 检查被跳过而非失败,产出一个自洽的假数字

`scripts/check-owned-edits-ledger.py` 对周期 20260809-013317 的 9 份 dev-report
实测结果:

| 调用方式 | exit | findings | REPLAY-UNIQUE |
|---|---|---|---|
| 带 `--git-root` | 1 | **74** | 1 |
| 不带 `--git-root` | 1 | **73** | **0** |

缺 `--git-root` 时 checker 无法解析 hex blob-ref 快照,`_resolve_snapshot`
返回 `blobref-unchecked`,**整个 replay 检查被跳过,而不是失败或报警**。

**这是「跳过被计为通过」的又一实例** —— 与今晚的 `44`、
与「18 个探测器过了 16 个、其中含一个 skip」同族。

本例额外揭示了该缺陷形态的传播机制:**73 这个数字之所以在圈子里流传,
正因为它自洽、可复现、且不报错。** 一个少跑了一整类检查的测量,
在外观上与一次完整测量无法区分 —— 没有 "N skipped" 字样,
没有降级警告,退出码同样是 1。**引用者无从得知自己引的是半次测量。**

完整分布(带 `--git-root`):SCHEMA 31、REPLAY-EMPTY-OLD 29、
LEDGER-SNAPSHOT-ORPHAN 10、LEDGER-ABSENT 3、REPLAY-UNIQUE 1。
流传的分解式只报了后三项,**漏掉了最大的一桶,所以它根本加不出总数** ——
这本可以在传播早期就暴露它。

### D18 [实测] 该 checker 的 74 是下界,不是总量:修得越多,数字越大

`_check_replay` 的第二个循环在**遇到第一条 `old == ""` 的条目时 `break`**,
其后所有条目永不被检查。29 条 REPLAY-EMPTY-OLD 因此同时充当了
29 个**遮蔽点**。

实证:init 通道 `hooks/prompt-workflow.py` 的 `owned_edits` entry[3],
其 `old` 为 `"        )\n"`,在该通道自己的快照中出现 **14 次** ——
这是一条**真实的 REPLAY-UNIQUE 违规**,只因 entry[0] 已使循环中止而**从未被报出**。

**推论(标注为推论):修掉那 29 条 empty-`old` 不会让 findings 数向零收敛,
会揭出更多。** 对这类「首错即中止」的检查器,
**数字下降不等于质量上升,数字上升也不等于劣化** ——
在遮蔽被解除之前,总数不具备趋势含义。任何把该数字当作 KPI 的用法都是错的。

### D19 [实测] 测试把实验室根目录硬编码到仓库与 scratch 之外

`hooks/tests/test_overnight_qa_sentinel_bind.py` 将其实验室根写死为
`/var/tmp/claude-qa-sentinel-bind-labs/`(位于 `/dev/sda1`,非 `/tmp`、非 `/dev/shm`、非仓库)。

后果:任何在受控 scratch 目录内运行该测试的测量,**都会在受控范围之外落盘**,
且 `TMPDIR` / `--basetemp` 对它无效。本轮测量因此在该路径创建了目录;
按 `rm` 全面禁止的规则**原样留置未删**。

这与 D5(盘满伪装成空结果)叠加时有实际风险:
**一个被认为「已改道 /dev/shm」的测量,其真实写入落点可能并不在那里**,
而操作者不会收到任何提示。

### D20 [实测] `grep` 是套用 `.gitignore` 的包装函数,而周期产物全部住在被忽略的目录里 —— 空结果的默认含义是「没看那里」

本环境中 `grep` **不是二进制,是一个 shell 函数**,exec 的是
`ugrep -G --ignore-files`。后果:**连手写 `grep -r --exclude-dir=.git .`
也会静默套用 `.gitignore`**,操作者以为自己关掉了过滤,其实没有。

同一次归属搜索的两个对照数字:

| 工具 | 触及范围 |
|---|---|
| 包装后的 `grep` | `docs/dev/` 下 **0 个文件** |
| `/bin/grep` | **2488 处命中 / 62654 个文件** |

而 `docs/dev/` 被 `.gitignore:142` 忽略,**整个开发周期的产物都住在那里**
(dev-report、close-report、ticket、context、acceptance-criteria、
inspector 报告、spec)。**决定归属的证据 100% 落在包装版看不见的地方。**

**这不是理论风险,它已经造成过污染:** 执行该次归属搜索的子代理
**头两遍全部作废重跑** —— 它先用包装版得到阴性,发现工具身份后
改用 `/bin/grep` 才拿到真实结果。若它没有察觉,那两遍阴性会作为
「无外来所有权主张」的结论上报,而这个结论正是一次提交的放行闸门。

**操作准则:在本环境中,一次 `grep` 返回空的默认含义是
「我没有看那里」,而不是「那里没有」。** 任何以空结果为依据的否定性结论,
必须先证明所用工具**确实看过**目标目录 —— 与 D10(仪器没测到它声称在测的东西)
同族,但这一条的成因不是搜索范围写错,而是**工具在操作者不知情时改写了搜索范围**。

### D21 [实测] 排除项的落地约束(备忘,防止将来单独提交)

`scripts/resolve-dev-artifact-chain.py` 已从周期 20260809-013317 的提交中排除
(实测:十五条清单中无一条依赖其工作树版本与 be418621 版本的差异,
两版本下七个测试文件结果逐字相同)。

**约束:该文件将来若单独落地,必须与 `tests/test_resolve_dev_artifact_chain.py` 同批。**
实测四格矩阵:

| resolver | 测试文件 | 结果 |
|---|---|---|
| be418621 | be418621 | 40 passed, exit 0 |
| 工作树 | be418621 | 40 passed, exit 0 |
| **be418621** | **工作树** | **12 failed, 36 passed, exit 1** |
| 工作树 | 工作树 | 48 passed, exit 0 |

单发 resolver 会引入一处**仓库内零测试覆盖**的行为变更
(覆盖它的测试正在被排除的那个文件里);单发测试则直接挂 12 条。

---

## 五、当前运营状态(2026-09-06 15:57Z)

| 账号 | 5小时窗 | 周窗 | 账本状态 | 账本裁决 |
|---|---|---|---|---|
| orchestrade | 96% | 37% | probation | `dispatch`(单并发) |
| yugetang | **28%** | **24%** | blocked_until | `stop_or_switch` |
| yugoge | 67% | **23%** | blocked_until | `stop_or_switch` |

地板为 5 小时窗 30%、周窗 25%,绝对约束。
**yugetang 两个窗口同时跌破;yugoge 周窗跌破。**

三条被管会话(`7ba38627`、`5c56779e`、`926d1cda`)**全部绑定
`claude-opus-5@yugetang`**;控制器自身在 `claude-fable-5@yugoge`。
唯一有余量的 orchestrade 为单并发。**这不是调度紧张,是单点。**

### 一处刻意不作为

`926d1cda` 处于可换号状态(活着且空闲),**但控制器拒绝为其换号**。

依据:`lastUsage` 报 `contextWindowMaxTokens: 1000000`、
`contextWindowUsedTokens: 635507`;三个账号 `extra_usage` 均为 `Disabled`。
2026-09-05 的一次模型变更曾使某会话上下文档位从 1M 掉至 200k,
报 `API Error: Usage credits required for 1M context`,停摆约 17 小时。

**1M 窗口是否随账号迁移未经证实。** 猜错的代价是当场销毁一份
不可重建的 63.5 万 token 调查。**拒绝重复该失败,而不是赌它。**

需用户确认:`claude-opus-5@orchestrade` 是否授予与
`claude-opus-5@yugetang` 相同的 1M 上下文窗口。

---

## 六、需用户动作(agent 不可代行)

1. **确认 orchestrade 的 1M 上下文** —— 确认后 `926d1cda` 方可迁移。
2. **清理 `/tmp`**(4.0G 满,9567 条目)。`rm` 对包括控制器在内的所有 agent 禁止;
   已证实该状态会把失败伪装成空结果(见 D5)。控制器所有临时写入已改道 `/dev/shm`。
3. **裁定 yugetang 地板口子**:是授权 `7ba38627` 与 `5c56779e` 在其上跑完,
   还是全部停到周窗于 2026-09-11 重置。地板是用户设定的绝对约束,
   **控制器不自行开此口子。**

升级已入账本:`escalation-floor-and-switch-deadlock-20260906T1552Z`。

---

## 七、19:00Z 后追加(控制器实测)

### D22 [实测] harness 自身住在 tmpfs 上

```
/root/.claude -> /dev/shm/dev-workspace/dot-claude     (符号链接)
tmpfs on /dev/shm type tmpfs (rw,nosuid,nodev,inode64)
```

**治理一切的 hooks、commands、agents、`settings.json` 全部在内存盘上。**
风险被切成两半,这个区分决定了该抢救什么:

| | 位置 | 重启后 |
|---|---|---|
| 已提交状态 | `github.com/Yugoge/awesome-claude-harness`,`unpushed=0` | **安全** |
| 未提交状态 | 仅 tmpfs | **归零** |

未提交面 = 67 个 porcelain 条目、33 个已跟踪改动(`git diff` 408968 字节)、
570 个未跟踪文件(4,078,152 字节)。**也就是今晚三组落不了地的那批东西。**

已全量快照至 `/var/backups/harness-uncommitted-20260906T1855Z`:
**3415 文件 / 99 MB / sha256 清单**(含 gitignored 的 `docs/dev/` ——
整个车队的周期证据链此前只存在于内存中)。
事后校验:`git diff` 仍为 408968 字节 / 33 文件,与快照前逐字节相同。

**这解释了今晚提交被卡住为什么不是流程问题:** 那些工作只存在于一块
会填满、会随重启清零的盘上。同期 `/dev/shm` 一度达到 96%(773M 可用)。

**附带**:多个项目仍配置指向已不存在的 `/dev/shm/dev-workspace/<project>` 路径。

### D23 [实测] `lastActivityAt` 会在前台子代理派发期间冻结

`926d1cda` 的 `lastActivityAt` 在 `13:02:06Z` 冻结**五个半小时**,
而该会话实际从 `13:06:45Z` 连续运行至 `18:43:53Z`(其中 3.93 小时为流水线执行)。

**机制**:前台(同步)子代理派发会阻塞父会话,**父会话的活动时间戳在此期间不前进**;
`13:02:06Z` 那个时间戳正是派发动作本身的写入时刻。

**这比 D2 更严重。** D2 是"闩锁置位后不清除",而控制器当时明确区分过:
「这次不是闩锁字段,是真实活动时间戳,所以它是真的停了。」
**那个区分是错的 —— 被挑出来当作可信的那个字段,恰恰也是坏的。**
控制器据此三次向用户报告该会话"闲置 2.5 / 4 / 5.5 小时"。

被管会话自己的观察值得并列记录:它在那五个半小时里**同样无法证明自己在工作** ——
它没有任何独立于该字段的活跃度证据可以出示。**监工与下属看的是同一块坏表。**

### D24 [实测] `/commit` 没有路径限定能力;范围来自声明,不来自命令

`commands/commit.md:17` 的文法:

```
/commit [<task-id>] [--force] [--bulk] [--dry-run] [--codex]
```

**无 `--paths` / `--only` / `--pathspec`,无第二个位置参数**;`:37` 明确「剥掉四个 flag
后剩下的 token 即 TASK_ID」,单数。

且手工收窄会被主动拒绝:`agents/changelog-analyst.md:146-150` 要求重新从 report
派生分区并**与 `owned_paths` 完全相等**,不等即 `failed/repository_plan_invalid`,
并明写「Do not silently rebuild or widen the plan inside this agent」。
`QA_APPROVED_FILES` 也不是杠杆:`commit.md:310` 机械设为 `PLAN_FILES`,
故意缩小的预期结果是 `scope_violation` 中止。

**控制器曾断言 `/commit` 支持路径限定,并以今晚的 `be418621` 为先例。该断言是错的。**
`be418621` 之所以呈现为路径限定,是因为**那条会话的 report 恰好只声明了那五条路径**。
**要改的是声明,不是命令。** 一条基于该错误前提下达的指令因此不可执行。

### D25 [实测] 半途完成的修复读起来像"已处理"

`/root/applio/docker-compose.override.yml`,同一份未提交 diff 内:

```
applio-web:  -context: /dev/shm/dev-workspace/applio/frontend
             +context: /root/applio-frontend                    ← 路径存在
applio-api:   context: /dev/shm/dev-workspace/applio/backend    ← 路径不存在,未改
```

后端那行在文件第 4 行,**位于 diff hunk 之上四行**。

**后果**:计划中的镜像重建会在 `applio-api` 上失败 —— 而那次重建正是让 PDF
内容完整性闸门在生产生效的唯一途径(三路独立证明其当前为死:镜像建于 2026-08-05,
早于闸门一个月)。

**为何比"完全没修"更危险**:审阅者看到一个陈旧 `/dev/shm` 路径正在被修正,
**不会怀疑同一文件里还有第二个**。修复的存在本身成了不再检查的理由。

---

## 八、用户动作清单(2026-09-06T19:15Z 现状,取代第六节)

第六节的第 2 项已部分自行处理,其余项状态有更新:

1. **执行三组提交** —— 见 `docs/reference/commit-handover-20260906-blocked.md` §0
   五分钟执行摘要。这是**唯一能让今晚工作离开内存盘的动作**(D22)。
2. **修 `applio` 的 `docker-compose.override.yml:4`** —— 一行,否则你计划中的
   镜像重建会失败(D25)。
3. ~~清理 `/tmp`~~ —— **已部分处理**:16:45Z 迁走 57 条 / 988 MB 至
   `/var/backups/tmp-relocate-20260906T1645Z`(带 sha256 清单),
   `/tmp` 由 100% 降至 77%。19:00Z 另迁 331 条 / 5.3 GB 出 `/dev/shm`,
   由 96% 降至 70%。**全程零删除**;`rm` 仍需由人执行。
   遗留:该次迁移的**逐文件 sha256 清单仍欠着**(5.3 GB 单命令跑不完),
   现有目录清单 `shm-relocate-20260906T1900Z.listing`(163,386 条);
   以及一条被中断标死的半途条目 `adjudicate-scratch.PARTIAL-...`(完整原件仍在源位置)。
4. **确认 `claude-opus-5@orchestrade` 是否授予 1M 上下文** —— `926d1cda` 迁移的前提。
   注意:用来判断这件事的 `contextWindowMaxTokens` 字段**本身已被证实会报假值**
   (17:43–17:57Z 报 200000 且同时报 used 超过 max,18:14Z 自行变回 1000000),
   所以**不能靠读该字段来回答此问**。
5. **yugetang / yugoge 地板** —— 分别为周窗 22% / 21%,均在 25% 地板下,
   账本判 `stop_or_switch`。orchestrade 周窗已于 19:13Z 重置至 100%(已核对原始来源)。
6. **`926d1cda` 第 3 步** —— 根因方向已定:step 7 的签名是「少产出恰好一条 bullet」
   4/5,且 `'the skills section'` 两次作为 bullet 标识出现。要判的是 minimax
   输出格式问题、还是流水线本该过滤小节标题 —— 决定修解析器还是修提示词。
