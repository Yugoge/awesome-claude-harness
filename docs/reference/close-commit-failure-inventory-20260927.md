# /close 与 /commit 失败方式全量清单(2026-09-27)

裁定(2026-09-27):close/commit 阶段只允许检测"开发周期本身失败"(a 类);一切 artifact
缺失/schema、文件内容/hash/新鲜度、环境/grant/锁、输入前置检查都必须由
dev/redev/do/dev-command/dev-overnight 侧闭环。本清单是现状盘点,不是修复。

**总量:/close 199 种,/commit 275 种,合计 474 个计数点。**
其中约 45 个计数点是同一段实现代码在两条链路各触发一次
(resolve-dev-artifact-chain.py 约 30 项、late-repair verify-disclosure 约 8 项、
会话卫生钩子约 6 项),去重后全局约 **430 个不同失败面**。

允许保留的 a 类:/close 约 21 种,/commit 仅 4 种(#7、#33、#36、#37,另 #88 半种)。
其余约 **405 种全部违规**。

分类键:(a) 开发失败 · (b) artifact 缺失/形状 · (c) 文件内容/hash/digest/所有权 ·
(d) 环境/基础设施 · (e) 用户输入/前置条件。
行为键:ABORT=命令文档中止 · EXIT=非零退出 · HOOK=钩子拦截(exit 2) · ADV=仅告警。

来源:两次工作树(含未提交修改)只读调查,全部条目带 file:line;
标注 [INFERRED]/[unverified] 的条目为静态推断,未运行验证。

---

## 第一部分:/close(199 种)

文件缩写(均在仓库根下):
CL=commands/close.md · AGG=scripts/aggregate-dev-report.py ·
RSV=scripts/resolve-dev-artifact-chain.py · RTE=scripts/close-route-select.py ·
LRC=scripts/late-repair-controller.py · LRP=scripts/check-late-repair-provenance.py ·
RSA=scripts/resolve-spec-artifacts.py · WQM=scripts/write-qa-mode.sh ·
WEF=scripts/write-enforce-flag.sh · CRA=scripts/close-report-append.py ·
CSD=scripts/close-scoring-decide.py · SCU=scripts/score-update.sh ·
DLC=scripts/dev-lifecycle.py · CRT=hooks/lib/contract_runtime.py ·
CV=hooks/lib/close-verdict.py。钩子按 hooks/ 下文件名引用。

### A. 调用与参数解析
1. 模型自行调用 /close — CL:4 disable-model-invocation + settings.json deny Skill(close:*) — 硬拒 — (e)
2. `--auto` 带显式 task-id — CL:62-73, DLC:803-804 — ABORT — (e)
3. `--auto` + `--force` — DLC:805-806 — ABORT — (e)
4. `--auto` + `--reason`(仅存在于文档,DLC:793-809 无该参数)— CL:62 — ABORT — (e)
5. `--late-repair` + `--force` — CL:206, RTE:47-49(exit 1), LRC:214-215 — ABORT — (e)
6. 显式路径不存在 — CL:171 — ABORT — (e)
7. 推不出 task-id("No spec identified…")— CL:194-197 — ABORT — (e)

### B. force 路径
8. sentinel 先于 TodoWrite 写入被拦:CL:37/96 要求先写 sentinel,但 prompt-workflow.py:1954-1957 已建 todo_acknowledged=false 书签,pretool-workflow-gate.py:1128-1191 以 "CHECKLIST NOT STARTED" 拦截 — HOOK — (e)。**文档与钩子互相矛盾。**
9. forced close-report 已存在,Write 被 pretool-write-guard.sh:146-155 拦覆盖 — HOOK — (c/e)
10. sentinel 清理脚本缺路径参数 — cleanup-close-force-sentinel.sh:8-11 exit 1;CL:138 吞掉错误 — ADV — (e)

### C. Step 0 聚合写入(CL:230-231,`|| exit 1`)
13–33 的 dev 侧对应:/dev Step 11 跑同一脚本(commands/dev.md:860),另注除外。
11. 聚合脚本缺失(按 `$PROJECT_ROOT/scripts/…` 调用,项目根非 harness 仓库即缺)— CL:230 — EXIT — (d)
12. `--task-id` 为空 — AGG:1508-1510 exit 2 — (e)
13. roster 不匹配(现存 shard <2 但 canonical 记录 ≥2 workers / parallel_workers 不可用)— AGG:1593-1636 — (b)
14. shard 加载失败(不可读/非 UTF-8/畸形/非对象)— AGG:1643-1657 — (b)
15. worker 标签重复 — AGG:493-494 — (b)
16. shard 缺 task_id/request_id — AGG:499-502 — (b)
17. shard task_id 不匹配 — AGG:506-509 — (b)
18. shard dev.status 非 completed/needs_review(如 blocked)— AGG:517-522 — **(a)**
19. shard AC-deviation 记录被拒 — AGG:523-527 — (b)
20. baseline_head_sha 缺失 — AGG:531-534 — (b)
21. baseline_head_sha 跨 shard 不一致 — AGG:537-540 — (c)
22. baseline_dirty_snapshot 键缺失 — AGG:543-546 — (b)
23. baseline_dirty_snapshot 跨 shard 不一致 — AGG:554-560 — (c)
24. baseline_provenance 声明非法(模式不支持/derived_from 缺失/自指/未知/files_created 差量不符)— AGG:347-397 — (b)
25. provenance 快照佐证失败 — AGG:400-430 — (c)
26. provenance 链成环 — AGG:445-449 — (b)
27. 既有 canonical 不可读 — AGG:1675-1679 — (b)
28. 既有 canonical 过期(workers 或 baseline_sha),需人工恢复 — AGG:1703-1717 — (c)
29. 完整性检查:baseline 快照无法解析 — AGG:1410-1411(汇入 1722-1735、1781-1794)— (c)
30. 完整性检查:owned_edits 台账空/非法 — AGG:1412-1413 — (b)
31. 完整性检查:hunk 重放与活字节不符(stage-owned-hunks --dry-run 失败)— AGG:1422-1432 — (c)。**dev 侧无后续活字节复查。**
32. canonical 写入 OSError — AGG:1727-1730, 1749-1753, 1785-1799 — (d)
33. AC-deviation provider 加载失败 → blocked lane 被拒 — AGG:1099-1111 — (d)

### D. Step 0 路由选择器与解析器(CL:232-235,exit 2)
37–76 的 dev 侧对应:同一解析器作为 /dev 后置条件(commands/dev.md:1335-1343)。
**/dev-command 与 /dev-overnight 未发现任何解析器调用——缺口。**
34. close-route-select.py 找不到(按当前目录相对路径调用)— CL:233 — EXIT — (d)
35. jq 缺失 → ARTIFACT_CHAIN 为空 — CL:234 — (d)
36. 解析器未处理异常 → traceback + exit 2(未找到 handler,unverified)— (d)
37. INVALID_TASK_ID — RSV:1351-1358 — (e)
38. MISSING_DEV_DIRECTORY — RSV:1359-1366 — (b)
39–47. MISSING_ARTIFACT(RSV:171-174, 200-203),每个 artifact 一种,均 (b):
   39 父 dev-report · 40 completion · 41 单体 ticket · 42 单体 context ·
   43 单体 qa-report · 44 lane ticket · 45 lane context · 46 lane dev-report · 47 lane qa-report
48. UNREADABLE_ARTIFACT — RSV:177-179, 206-208 — (d)
49. EMPTY_ARTIFACT — RSV:180-182, 209-211 — (b)
50. MALFORMED_JSON — RSV:183-191 — (b)
51. INVALID_JSON_TYPE — RSV:192-194 — (b)
52. JSON IDENTITY_MISMATCH — RSV:218-225 — (b)
53. Markdown MISSING_IDENTITY — RSV:235-241 — (b)
54. Markdown IDENTITY_MISMATCH — RSV:242-248 — (b)
55. INVALID_DEV_STATUS:dev 非对象 — RSV:254-256 — (b)
56. INVALID_DEV_STATUS:status 非 completed — RSV:257-262 — **(a)**
57. INVALID_FILE_LIST — RSV:263-272 — (b)
58. INVALID_BLOCKING_ISSUES — RSV:273-279 — (b)
59. UNRESOLVED_BLOCKERS — RSV:280-285 — **(a)**
60. INVALID_QA_STATUS(qa.status≠pass)— RSV:287-300 — **(a)**
61. MISSING_COMPLETION_REFERENCE — RSV:307-316 — (b)
62. ABSENT_DECLARED_PATH(声明文件已不在盘上)— RSV:1241-1271 — (c)
63. INVALID_WORKER_SET — RSV:1398-1406 — (b)
64. AMBIGUOUS_WORKER_SET(重复)— RSV:1409-1414 — (b)
65. UNREADABLE_DEV_DIRECTORY — RSV:1428-1432 — (d)
66. AGGREGATE_IMPLEMENTATION_ERROR — RSV:1446-1453 — (d)
67. AMBIGUOUS_WORKER_SET(<2 workers)— RSV:1457-1462 — (b)
68. LANE_SET_MISMATCH — RSV:1463-1469 — (b)
69. UNDECLARED_LANE_ARTIFACT — RSV:1173-1217 — (b)
70. INVALID_SHARD_SET(复跑 15–26 项检查)— RSV:1529-1535 — (b/c)
71. STALE_FILE_UNION — RSV:1553-1558 — (c)
72. STALE_CANONICAL — RSV:1559-1564 — (c)
73. AMBIGUOUS_SINGULAR_CHAIN — RSV:1575-1580 — (b)
74. LOST_WORKER_DECLARATION — RSV:1581-1592 — (b)
75. 可选 fan-out 父 ticket/context/QA 存在但非法 — RSV:1146-1170 — (b;父 QA 非 pass 时为 (a))
76. INVALID_AC_DEVIATION_RECORD — RSV:1630-1662 — (b)
77. CLI_ARGUMENT_ERROR — RSV:1708-1720(直接 CLI;RTE:88 argparse exit 2)— (e)

### E. late-repair 路线(CL:201-214;失败即 CLOSE: NO 或停止)
78. 链不合格("非 beyond-QA gap")— LRC:219-221 — (b)
79. 既有 run record 不可解析 → 无 try/except,直接崩(unverified)— LRC:225 — (b)
80. controller 无可解析输出 — RTE:75-78 — (d)
81. record-stage:无 run record 或 run-id 不匹配 — LRC:274-277 — (e)
82. record-stage:未知 stage — LRC:278-279 — (e)
83. record-stage:fail_closed(无 original_cycle_at 且 dev-report 缺失)— LRC:280-284, 173-188 — (b)
84. record-stage:stage 重复 — LRC:285-286 — (e)
85. record-stage:stage 乱序 — LRC:287-290 — (e)
86. record-stage:report 路径缺失 — LRC:295-296 — (b)
87. record-stage:basename 错误 — LRC:297-303 — (b)
88. finalize:无 record / id 不匹配 / stage 未记录 — LRC:327-334 — (e)
89. finalize:dev-report 缺失(含 fail_closed)— LRC:336-347 — (b)
90. finalize:provenance 检查错误 — LRC:349-352;LRP:229-230, 274-275 — (b)
91. finalize:honest_refuse(不可调和漂移)— LRC:362-370 — (c)
92. verify-disclosure:无 run record — LRC:418-419 — (b)
93. verify-disclosure:无已记录 artifact — LRC:434-435 — (b)
94. verify-disclosure:artifact 或 disclosure 缺失 — LRC:437-442 — (b)
95. verify-disclosure:字段缺失 — LRC:443-445 — (b)
96. verify-disclosure:route 不匹配 — LRC:446-447 — (b)
97. verify-disclosure:run-id 不匹配 — LRC:448-449 — (b)
98. verify-disclosure:artifact 身份不匹配 — LRC:450-451 — (c)
99. verify-disclosure:hash 不匹配 — LRC:452-454 — (c)
100. **潜在 bug(unverified)**:--late-repair 下 RTE 不返回 artifact_chain → ARTIFACT_CHAIN={},CL:315-317 REPORT_PATHS 提取将 KeyError — (d)

### F. do-report 轻量预检(CL:283)
101–105 的 dev 侧对应:stop-do-report-gate.py(默认 advisory,:12-18,且接受 blocked)。
101. task_id ≠ TASK_ID — (b)
102. source ≠ "do" — (b)
103. do.status = pending — (b)
104. do.status = blocked — **(a)**
105. do.files_modified 非数组 — (b)
106. do-report 存在但 source≠"do" → 被路由进 /dev 链撞 MISSING_ARTIFACT — CL:179-184 — (b)

### G. artifact schema 门(CL:315-347)
107. dev-report 未过版本化 schema — CRT:552-558 — EXIT 2 — (b)。dev 侧:subagentstop-artifact-contract-enforce.py(默认拦截)
108. qa-report 未过 schema — 同上 — (b)
109. 版本化 do-report 未过 schema(工作树新增,CL:285, 347)— (b)。dev 侧仅 advisory stop gate
110. 内联 Python import 失败 → exit 1,文档只定义 exit 2 为拦截,结果歧义 — CL:319-334 — (d)
111. 相对路径从错误目录解析 → 静默 SKIP — CRT:537-538 — ADV — (d)

### H. cp-state spec 解析器(CL:363-366,exit 1)
dev 侧:同一解析器被 /spec 与 /dev* 消费方使用(RSA:2-3)。
112. spec 路径不可读 — RSA:273 — (e)
113. manifest 缺失/畸形/非对象/schema_version 错误 — RSA:144-156 — (b)
114. monolith_path 缺失/越界/不存在/不匹配 — RSA:160-176 — (b)
115. .split-complete 标记缺失 — RSA:181 — (b)
116. 记录 hash 畸形或过期 — RSA:215-217 — (c)
117. mtime 过期 — RSA:222 — (c)
118. 引用的 view 缺失 — RSA:238-255 — (b)
119. hash/stat IO 错误 — RSA:212, 224 — (d)
120. 二义(两个合法候选)— RSA:311 — (b)

### I. Step 1 巡检员派发
121. Agent 派发未带 run_in_background=false — pretool-block-background-tasks.py:203-210 — HOOK — (e)
122. gitignore 预检拦巡检派发(dev-report 声明了被 gitignore 的文件)— pretool-gitignore-preflight.py:713-816 — HOOK — (c)
123. /do consent 旗标残留 → 一切 Agent 派发被拦 — pretool-do-block-subagents.py:113-120 — HOOK — (d)
124. 巡检员 3 次重试仍瞬时失败 → findings 记空 — CL:415, 506 — ADV — (d)
125. 连续 >5 次 Bash 无 Agent 派发 — pretool-orchestrator-gate.py:63, 172-184 — HOOK — (e)
126. 编排器读 >600 行文件 — pretool-read-size-guard.py:77-90 — HOOK — (e)
127. workflow 因顺序/计数违规锁死 — pretool-workflow-gate.py:1171-1191;posttool-todo-sequence.py:145;posttool-todo-count.py:49 — HOOK — (e)
128. 常规路径 TodoWrite 前用任何工具 — pretool-workflow-gate.py:1185-1191 — HOOK — (e)

### J. Step 2 registry 写入(CL:430-437,exit 1)
129. CLAUDE_PROJECT_DIR 未设 — WQM:35, WEF:42 — (d)
130. session-id/task-id 含不安全字符 — WQM:31,33;WEF:39-40 — (e)
131. qa.json 非可读 JSON — WQM:75-79 — (b)
132. qa.json 非对象 — WQM:80-81 — (b)
133. qa.json agent_type ≠ "qa" — WQM:82-83 — (b)
134. qa.json session_id ≠ dev-<TASK_ID> — WQM:84-85 — (b/d)
135. init 块 mkdir/写入失败(set -e)— WQM:43-46 — (d)
136. registry mkdir 失败 — WEF:71-72 — (d)
137. 目标是 symlink — WEF:80-81 — (d)
138. enforce-flag 写入失败 — WEF:92-93 — (d)

### K. QA 派发上的 PreToolUse 钩子
139. 聚合检查:≥2 shard 无 canonical,或 prompt 无锚定 task-id 触发全局扫描 — pretool-aggregate-check.py:347-381, 470-472 — HOOK — (b)
140. QA 派发上的 gitignore 预检(lane-matrix 豁免 E3/E4 不满足)— pretool-gitignore-preflight.py:733-812 — HOOK — (c)

### L. close QA 代理上的 SubagentStop 钩子
141. **E2E:无关联 qa-report。/do 路线根本不存在 qa-report,但 CL:430-434 无条件武装 e2e 检查 → /do 的每次 close 必被拦** — subagentstop-e2e-enforce.py:225-234 — HOOK — (b)。/do 无 dev 侧对应
142. E2E:e2e_enforcement 畸形 — :246-253 — HOOK — (b)
143. E2E:e2e_enforcement 字段缺失 — :255-261 — HOOK — (b)
144. E2E:status 不在通过集 — :263-280 — HOOK — (a/b)。142–144 读的是 dev 周期 QA 报告,同钩子在 /dev QA stop 已查过
145. artifact contract:任一关联 qa-report 未过 schema — subagentstop-artifact-contract-enforce.py:274-318 — HOOK — (b)
146. **codex-enforce.json 残留**:--codex /dev 周期复用 registry dev-<TASK_ID>,close QA 不带 codex 即被拦 — subagentstop-codex-enforce.py:76-98 — HOOK — (d)
147. QA 把临时 section 文件写进 /tmp 或 /var/tmp(被 deny;CL:610 未指定应写哪)— pretool-tool-policy.py:224-252;policies/tool-policy.v1.json(qa)— HOOK — (d/e)
148. tool-policy import 失败即 fail-closed — pretool-tool-policy.py:60-80 — HOOK — (d)
149. 未决 checkpoint(仅 CP_ENFORCE_MODE=block 时拦)— subagentstop-cp-enforce.py:44, 94 — 默认 ADV — (b)
150. 大 diff 无 justification — subagent-stop-diff-check.sh:47-63 — ADV — (c)
151. layer 不匹配 — pretool-layer-match-gate.sh:29-38 — ADV — (c)
152. guard 移除 — subagent-stop-guard-integrity.sh:50-58 — ADV — (c)

### M. QA 裁决分支(CLOSE: NO)
153. 分支 3:Codex 异议 — CL:567 — **(a)**
154. Bullet 1:下游可消费性 — CL:488 — (b)
155. Bullet 2:task-id 链一致性 — CL:489 — (b)
156. Bullet 3:范围内既有缺陷未修 — CL:490-494 — **(a)**
157. Bullet 4(i):/commit 可消费性 — CL:496 — (b)
158. Bullet 4(ii):push 权限 — CL:497 — (d)
159. Bullet 4(iii):commit 通道绕行 — CL:498 — **(a)**
160. 分支 5:QA 异议 — CL:571 — **(a)**
161. 分支 2(d):AC deviation 坍缩为 FAIL — CL:564 — **(a)**
162. 分支 7:failed_parse 输出含异议信号 — CL:580 — **(a)**
163. 分支 7:attestation 缺失 → 落入分支 8 — CL:580, 606 — (b)
164. 分支 8:歧义或 QA 侧解析失败 — CL:582 — (d/e)
165. 分支 10:披露的例外无法佐证 — CL:592-596 — (a/c)
166. 巡检员发现新 cleanliness 违规 — CL:518-533 — **(a)**
167. 限定默认 NO:工具不可用阻断评估 — CL:846 — (d)
168. QA 末行非法定 CLOSE: 行 → 归为 unknown,fail-closed — CL:617;CV:29-39 — (b)

### N. close-report 追加助手(既有报告;CL:610-615)
169. 助手缺失($PROJECT_ROOT/scripts/…,CL:611)→ 任何非 sentinel 输出 fail-closed(CL:614)— (d)
170. section 文件未找到 — CRA:766-768 exit 2 — (e)
171. close-verdict.py 缺失 — CRA:205-211, 772-774 — (d)
172. section 文件不可读 — CRA:550-555 — (d)
173. section 文件为空 — CRA:557-561 — (b)
174. section 末行非法定 CLOSE: 行 — CRA:563-566 — (b)
175. 锁超时/锁参数非法 — CRA:572-582 — (d)
176. 既有报告不可读 — CRA:588-593 — (d)
177. temp 写入失败 — CRA:604-616 — (d)
178. staged 回读失败 — CRA:620-629 — (d)
179. staged 字节不匹配 — CRA:631-638 — (d)
180. publish(os.replace)失败 — CRA:643-660 — (d)
181. publish 后回读失败 → ERROR(exit 1)或 CRITICAL(exit 4)— CRA:663-673, 497-538 — (d)
182. publish 后不匹配/并发写者 → CRITICAL — CRA:675-690 — (d)
183. published 末行不匹配 — CRA:692-704 — (d)
184. stderr 损坏 → exit 3 — CRA:777-791 — (d)
185. QA 对既有报告用 Write — pretool-write-guard.sh:146-155 — HOOK — (e)

### O. Step 3(不改变裁决)
186. close-scoring-decide:IO 错误或 verdict 模块缺失 — CSD:172-181, 242-245 exit 3 — ADV — (d)
187. score-update 前置失败(exit 5)— SCU:165-202 — ADV — (b)
188. score-update 锁超时(exit 2)/参数错误(exit 1)— SCU:110-153, 208-213 — ADV — (d)。工作树 settings.json 已丢弃 Bash(scripts/score-update.sh:*) allow 项,现在会触发权限询问

### P. 主会话 Stop 门(任何会话适用)
189. phase 配置/顺序非法 — stop-workflow-coordinator.py:215-235 — HOOK — (d)
190. 资源预检错误(仅 trust 环境设置时)— :238-259 — HOOK — (d)
191. auto_commit checkpoint 失败 — auto-commit.sh:52-54;coordinator:272-280 — HOOK — (d)。同时跳过 cleanup phase → /do consent 旗标残留 → 触发第 123 项
192. phase 超时(30s;auto_commit 120s)— coordinator:155-156 — HOOK — (d)
193. overnight 时间锁 — stop-overnight-timelock.py:231-254 — HOOK(仅 overnight)— (d)
194. 资源终结器失败 — coordinator:292-318 — HOOK — (d)
195. do-report 门 — stop-do-report-gate.py:200-227 — ADV(仅 block 模式拦)— (b)

### Q. --auto
196. 钩子拒绝中止整批 — CL:810-815 — ABORT — (d/e)
197. list-actionable 扫描崩溃(DLC:946-950 无 handler,unverified)— (d)
198. 多父任务对 3 步 todo 清单可能触发顺序锁(第 127 项)(推断,无代码路径确证)— (e)
199. (实际属于 /commit)close-report 24h 过期 — commands/commit.md:114 — 2026-09-26 起 ADV — (c)

/close 未验证项:36、79、100、197、198。

---

## 第二部分:/commit(275 种)

缩写:CA=agents/changelog-analyst.md · RCR=scripts/resolve-commit-repos.py ·
SOH=scripts/stage-owned-hunks.py · PG=hooks/pretool-git-privilege-guard.py。
[INFERRED]=静态推断未运行;[CONDITIONAL]=仅特定会话状态触发;[ADVISORY]=仅告警。

a 类仅 4 项:#7(close-report 末行非 CLOSE: YES)、#33(dev.status≠completed)、
#36(unresolved blocking_issues)、#37(qa.status≠pass);#88 半属 (a)。

### 影响"前移"图景的关键事实
- commit 时 artifact-chain 检查与 dev 侧重复:resolve-dev-artifact-chain.py 已在
  /dev 完成时(commands/dev.md:1342)与 /close Step 0(commands/close.md:254)运行;
  commit 时只抓 close 之后的漂移。
- **ownership 台账 dev 侧零执法**(#71–#73、SOH #211–#224):
  scripts/check-owned-edits-ledger.py 存在但无任何命令/钩子调用;
  hooks/pretool-baseline-snapshot-preflight.py 未跟踪且未注册进 settings.json;
  schemas/owned-edits-ledger.v1.json 在 commit 时从不校验,只通过 SOH 行为生效。
- dev 侧 schema 钩子(subagentstop-artifact-contract-enforce.py,工作树新增)
  只覆盖声明了 report_version 的报告;未版本化报告(多数)全部漏过。
- SOH 工作树新增两种拒绝:filter 属性拒绝(:1369-1385)、apply 后索引复读不匹配拒绝(:1554-1570)。
- RCR 工作树新增:ownership-gate 错误的 code= 分类;files_landed_whole 声明但 claim
  字段畸形时拒绝(:553-566)。
- **疑似现行缺陷**:tracked 删除用 `git -C … rm --` 暂存,疑被 bash-safety rm 规则
  (pretool-bash-safety.sh:1596-1600)拦截 → 删除可能永远无法暂存 [INFERRED];
  同一 session/branch 槽位第二个 push-gate token 被 write-guard(:149-156)拦 [INFERRED];
  changelog-analyst 的 tool-policy 不允许 /tmp/commit-msg-* 与 /tmp/agentic-commit/
  写入(角色解析后才生效)[CONDITIONAL]。
- 已 advisory:Step 3 检查 3(close-report >24h)对所有调用仅告警;检查 2 仅在
  --dry-run 时放松;task-id 从会话上下文推断,歧义时硬失败。

### A. commands/commit.md Steps 1–4
1. --auto 带 task-id — commit.md:41-46;dev-lifecycle.py:803-804 — (e)
2. --auto + --force — dev-lifecycle.py:805-806 — (e)
3. --auto + --bulk — dev-lifecycle.py:807-808 — (e)
4. 推不出 task-id — commit.md:57-72 — 退出 — (e)
5. task-id 歧义(≥2 候选周期)— commit.md:63-72 — 退出 — (e)
6. close-report 缺失 — commit.md:94;resolve-close-report.sh:39-41 — 硬中止 — (b)
7. 末行非 CLOSE: YES — commit.md:95-101(--dry-run 时放松,:102-106)— **(a)**
8. close-report 文件名与 task-id 不匹配 — commit.md:115 — (e)/(b)
9. [ADVISORY] close-report >24h — commit.md:114 — (d)
10. bulk 能力缺失(sentinel 未铸造)— commit.md:153;userprompt-bulk-commit-capability.py:83-97 — (d)

### B. Step 5 late-repair 检查(State C 拒绝;commit.md:209-212 exit 2;源 late-repair-controller.py;(b)/(c);dev 侧=/close --late-repair)
11. 无匹配活动 run record — :418-419
12. run record 无 artifact — :434-435
13. 记录的 artifact 文件缺失 — :438-439
14. artifact 缺 disclosure 块 — :440-442
15. disclosure 缺字段 — :443-445
16. route 不匹配 — :446-447
17. repair_run_id 不匹配 — :448-449
18. artifact 身份不匹配 — :450-451
19. artifact hash 不匹配 — :452-454
20. "admitted" payload 不可解析 — :484-489
21. record 无 effective_report — :491-493
22. effective report 文件缺失 — :494-496

### C. Step 5 artifact-chain 解析器(commit.md:221-222 exit 2;status=fail 于 resolve-dev-artifact-chain.py:1679-1680,exit 2 于 :1723;dev 侧=同解析器已跑于 dev.md:1342 与 close.md:254)
23. CLI_ARGUMENT_ERROR — :1710-1720 (e)
24. INVALID_TASK_ID — :1351-1358 (e)
25. MISSING_DEV_DIRECTORY — :1359-1366 (b)
26. MISSING_ARTIFACT(ticket/context/dev/qa/completion/lane 文件)— :171-174, :200-203 (b)
27. UNREADABLE_ARTIFACT — :177-179, :206-208 (d)
28. EMPTY_ARTIFACT — :180-182, :209-211 (b)
29. MALFORMED_JSON — :185-191 (b)
30. INVALID_JSON_TYPE — :192-194 (b)
31. IDENTITY_MISMATCH — :218-225, :242-248 (b)
32. MISSING_IDENTITY — :235-241 (b)
33. INVALID_DEV_STATUS — :254-262 **(a)**
34. INVALID_FILE_LIST — :263-272 (b)
35. INVALID_BLOCKING_ISSUES — :274-279 (b)
36. UNRESOLVED_BLOCKERS — :280-285 **(a)**
37. INVALID_QA_STATUS — :294-300 **(a)**。#33/#36/#37 可转披露例外(:869-925,未逐行追踪)
38. MISSING_COMPLETION_REFERENCE — :307-316 (b)
39. ABSENT_DECLARED_PATH — :1256-1271 (c)。也会拒绝 files_modified 里合法删除的文件 [INFERRED]
40. INVALID_WORKER_SET — :1398-1406 (b)
41. AMBIGUOUS_WORKER_SET(重复)— :1409-1414 (b)
42. AMBIGUOUS_WORKER_SET(<2)— :1457-1462 (b)
43. UNREADABLE_DEV_DIRECTORY — :1428-1432 (d)
44. AGGREGATE_IMPLEMENTATION_ERROR — :1446-1452 (d)
45. LANE_SET_MISMATCH — :1464-1469 (b)
46. UNDECLARED_LANE_ARTIFACT — :1211-1217 (b)
47. INVALID_SHARD_SET — :1532-1535 (b)
48. STALE_FILE_UNION — :1553-1558 (c)
49. STALE_CANONICAL — :1559-1564 (c)
50. AMBIGUOUS_SINGULAR_CHAIN — :1575-1580 (b)
51. LOST_WORKER_DECLARATION — :1581-1592 (b)
52. INVALID_AC_DEVIATION_RECORD — :1631-1660 (b)

### D. Step 5 仓库计划(RCR;全部 BLOCKED exit 2 于 :660-662 → commit.md:226-229 || exit 2)
53. task-id 为空 — :461-462 (e)
54. 控制根非 git 仓库 — :463, :64-66 (d)
55. 显式 report 文件不存在 — :406-408(commit.md:215-218 静默回落 do-report 路径,"无 dev-report 且无 do-report"在此浮出)(b)
56. report 在控制仓库外(也拒子项目 docs/dev)— :465-466 (b)
57. report 不可读/非法 JSON — :363-366 (b)
58. report 非 JSON 对象 — :367-368 (b)
59. task_id/request_id 缺失或不匹配 — :369-375 (b)
60. .effective.json 报告未被佐证 — :381-394 (b)
61. 既非 canonical dev-report 也非 source=do 的 do-report — :396-397 (b)
62. dev/do section 对象缺失 — :398-400 (b)
63. supported-repo 参数非 git 仓库 — :471-474 (d)
64. files_modified/files_created 非字符串数组 — :478-481 (b)
65. owned path 为空/非字符串/含 NUL — :85-87 (b)
66. owned path 无现存祖先目录 — :75-80 (c)
67. owned path 不在任何 git 仓库内 — :490 → :64-66 (c)
68. owned path 在 supported repo 集外或未 admitted 的嵌套 checkout — :491-493 (c)
69. owned path 命名仓库根 — :498-500 (c)
70. files_landed_whole 声明但 owned_edits/pre_edit_snapshots 非对象(新)— :553-566 (b)
71. **ownership 门:baseline_dirty_snapshot 缺失 → upstream_defect** — :345-346, :583-601 (b)。dev 侧:无(agents/dev.md:533 仅为指示)
72. **ownership 门:快照非 porcelain 文本 → upstream_defect** — :349-350, :590-601 (b)。dev 侧:无
73. **ownership 门:files_modified 路径未被 owned_edits/baseline/files_landed_whole 覆盖** — :602-607 (c)。dev 侧:检查脚本存在但未接线
74. detached HEAD(branch 为空)— :614-617 (e)
75. unborn HEAD — :615 → :64-66 (d)
76. [INFERRED] git 调用 5s 超时,TimeoutExpired 未捕获(:57-62)→ traceback 崩溃 (d)
77. [INFERRED] 相对路径调用脚本,工作目录非 harness home 即失败 — commit.md:206, :221 (d)

### E. Step 5 commit grant 与 manifest
78. 环境无 session id — write-commit-grant.py:353-365;commit.md:239-243 — exit 2 (d)
79. --task-id 为空 — write-commit-grant.py:370-375 — exit 2 (e)
80. repo/branch/HEAD 解析失败 — write-commit-grant.py:392-402 — exit 2 (d)
81. grant 的 repo/branch/HEAD 与 plan 条目不符 → 撤销全部 grant 并中止 — commit.md:236-238 (c)
82. 写 manifest 时 plan/chain 数据丢失或改变 → 中止 — commit.md:266-274 (d)
83. [INFERRED] 同 session 第二次 /commit 写固定名 manifest /tmp/claude-commit-manifest-{sid}.json 被 write-guard(:149-156)拦(文件已存在)(d)

### F. Step 6 提交前 QA 门
84. 规划 dry-run 无可提交内容 — commit.md:295 — no-op 停止 (e)
85. QA 拒:瞬时副产物 — commit.md:325-328 → REJECT、unstage、撤 grant、停(:365)(c)
86. QA 拒:secrets — :329 (c)
87. QA 拒:范围污染 — :330-332 (c)
88. QA 拒:明显正确性缺陷 — :333-334 (c,半 (a))。dev 侧:/dev 的 QA 与 /close
89. Codex 实质 REJECT 翻转裁决 — :337-341 (c)
90. Codex 输出不可解析且显异议/歧义 → REJECT — :342-346 (d)
91. QA 末行非可解析 COMMIT: 裁决 → fail-closed REJECT — :370 (d)
92. 用户 --dry-run 在 APPROVE 后停止(设计使然)— :368 (e)
93. [INFERRED] unborn 仓库上 unstage 用 git rm --cached,疑被 bash-safety rm 规则拦 — commit.md:365;pretool-bash-safety.sh:1596-1600 (d)

### G. Step 7 结果处理、Step 8 与 --auto
94. 结果 repo 根/顺序与 plan 不符 → 拒绝 — commit.md:424-425 (c)
95. status=committed 但某 repo 无终态结果或无 push-gate token — :429-432 (c)
96. partially_committed → 停止、不重试、无 Step 8 — :434-442 (d)
97. [ADVISORY] nothing_to_commit 告警 — :444-445 (b)
98. [ADVISORY] push-gate 对账被拒告警 — :447-451 (c)
99. 对账结果 SHA 非 HEAD 或依据非 commit journal → 拒绝 — :496-502 (c)
100. grant 失败后的一次重试仍失败 → 停止 — :552-570 (d)
101. 不可重试 failure_code → 停止 — :572-577(类别不定)
102. 未知 status 或缺 BEGIN 状态标记 — commit.md:579-580;CA:1931-1935 (d)
103. Step 8:本周期产出一个 spec 未链接 → commit 已落地后非零退出 — commit.md:636 (b)
104. Step 8:多个未链接 spec — :637 (b)
105. [ADVISORY] Step 8 spec-update 派发失败 — :669 (d)
106. --auto:钩子拦了某工具调用 → 中止整批 — :709-712 (d)
107. --auto:某父任务 partially_committed → 中止批内其余 — :713-718 (d)

### H. changelog-analyst(CA)
**Phase 1 — plan 校验(均为 repository_plan_invalid,CA:135-150):**
108. plan 非对象或 schema_version≠1 (b)
109. plan task_id 与 task-id 不符 (e)
110. transaction_semantics 不匹配 (b)
111. report 路径不在控制根下 (b)
112. report SHA-256 已不匹配(规划后被编辑)(c)
113. repositories[] 为空 (b)
114. repo order 不连续 (b)
115. repo 根重复 (b)
116. 活 repo toplevel 不同 — :142 (d)
117. 活 branch 不同 — :143 (d)
118. 活 HEAD 与 expected_head 不同 — :144 (d)
119. owned-path 划分与 owned_paths 不同 — :146-149 (c)

**Phase 1 — artifact-chain 检查(:152-167):**
120. chain 非对象或 status 非 pass (b)
121. chain task_id 不匹配 (b)
122. chain mode 非 singular/fanout (b)
123. canonical_dev_report 与 plan 的 report 路径不同 (b)
124. 必需 chain 数组缺失 — :156-157 (b)
125. do-report plan 带非空 chain — :166-167 (b)
126. .effective.json 例外复验失败 — :169-188 (b)

**Phase 2 — 分类:**
127. files_required_to_ship 路径既不在工作树也不在 HEAD → ABORT scope_violation — :252-255 (b)/(c)。dev 侧:无
128. required-to-ship 声明推导失败:reports 目录缺失 — :305-310;scripts/lib/candidate_tree.py:273-274 — ABORT (b)
129. …无 report 匹配任务 — candidate_tree.py:318-321 (b)
130. …report 不可读/非法 JSON — candidate_tree.py:285-288 (b)
131. …category 非列表 — candidate_tree.py:296-298 (b)
132. …无 report 记录 baseline_head_sha — candidate_tree.py:329-334 (b)。dev 侧:无
133. …无 report 匹配所选 baseline — candidate_tree.py:343-346 (b)
134. 脏文件不在白名单 → 按疑似外来排除(告警+排除)— :316-320 (c)
135. staged 文件数超白名单上限 → ABORT scope_violation — :322-332 (c)
136. 无 dev-report 且无 do-report → ABORT — :338-342 (b)
137. dev-report 查找拒绝未佐证的 late-repair 报告返回空 → 导致 #136 — resolve-dev-report.py:90-91, :106-107 (b)
138. 文件依赖被本次 commit 排除的内容 → 排除(dependency_coupled)— :344-373 (c)
139. [ADVISORY] baseline 缺失或外来 → 跳过 provenance 过滤 — :425-434 (b)
140. files_modified 路径自 baseline 起无变化 → 排除(provenance_anomaly)— :451, :455-459 (c)
141. files_created 路径非 untracked → 排除(provenance_anomaly)— :452, :460 (c)
142. gitignored 文件 → 排除 — :469 (c)。dev 侧:gitignore 预检钩子(#260)
143. /tmp/ 路径 → 排除 — :470 (c)
144. basename 命中 secret 模式 → 排除 — :471-472 (c)
145. 文件落在 QA 批准集外:排除,或实质分歧时 ABORT scope_violation — CA:127;commit.md:407 (c)
146. [ADVISORY] 派发后新出现的文件 → 仅告警 — :196-202 (c)

**Phase 3 — 锁与提交事务:**
147. commit 锁(flock)30s 内未获得 → exit 1 — :586-592 (d)
148. 锁定与提交之间 repo/branch/HEAD 变化 → repository_plan_invalid,或先前 repo 已提交时 partially_committed — :482-487 (d)
149. 实际无 staged 内容 → nothing_to_commit — :512-514 (b)/(c)
150. 写完 message 后 staged 集变化 → unstage、staging_error — :524-538, :1028-1038 (d)

**Phase 5 — 暂存:**
151. untracked 文件收养助手非零返回 → 排除 — :682-687 (c)
152. hunk 暂存助手返回 10 或其他失败 → 排除 — :728-737 (c)
153. required-to-ship 路径同时在同一 report 里被声明为 authored → 拒绝 — :756-771 (c)
154. files_landed_whole 条目无可解析 diff_sha256 → 拒绝 — :794-804 (b)
155. staged digest 与声明 digest 不符 → 回滚并排除 — :823-828 (c)
156. 该回滚失败 → 中止整个事务 — :829-832 (d)
157. files_landed_whole 路径同时在 owned_edits/pre_edit_snapshots → 拒绝 — :834-837 (c)
158. 脏 tracked 文件无 ownership 来历 → 告警跳过 — :845-853 (c)。dev 侧:无
159. untracked 文件消失 → 跳过 — :874 (d)
160. 某文件 git add 失败 → 跳过 — :1322 (d)
161. [INFERRED] tracked 删除用 git -C … rm -- 暂存被 bash-safety rm 规则拦 — CA:866-869;pretool-bash-safety.sh:1596-1600 (d)

**Phase 7 及之后:**
162. 孤儿文件(不在 report、非任务 artifact)→ 跳过 — :981-984 (c)
163. git commit 非零退出 → git_error — :1856 (d)
164. 非 grant 钩子拦提交 → hook_blocked — :1858 (d)
165. 先前 repo 已提交后后续 repo 失败 → partially_committed — :1081-1086 (d)
166. push-gate token 写入前 HEAD 移动 → push_gate_race — :555-558, :1125 (d)
167. token 写入中 HEAD 移动 → push_gate_race — :566-569, :1128 (d)
168. 其他会话 token 已占槽位 → 写入被跳过 — :38, :559-564 (d)
169. [INFERRED] Write 工具拒绝覆盖既有 token 文件(同 session 同 branch 未 push)— pretool-write-guard.sh:149-156 (d)
170. [CONDITIONAL] 角色解析后 tool-policy 拒绝 commit-message 与 token 写入 — policies/tool-policy.v1.json;pretool-tool-policy.py:323-335 (d)
171. [ADVISORY] push-gate token 写入失败 → 仅告警 — :1359-1360 (d)
172. 拒绝在 remote-tracking 分支(refs/remotes/)上运行 — :42 (e)

**恢复路径、对账与 bulk:**
173. 恢复提交失败 → hook_blocked 或 git_error — :1827-1835 (d)
174. 恢复提交的 token 与其他会话冲突 → push_gate_collision — :1820-1825 (d)
175. 对账被拒:无 journal 条目把 HEAD 归于本会话 — :1666-1671 (c)
176. 对账遇竞态或冲突 — :1636-1649 (d)
177. journal 查询出错 → 视为不可归属 — :1542-1545;hooks/lib/commit_journal.py:602-616 (d)
178. bulk 组失败 → FAILED_GROUPS exit 2 — :1328-1357 (d)
179. [ADVISORY] bulk 结束时仍有变更 — :1255-1265 (d)

### I. SOH 排除(每项返回 10,SOH:77-79;CA 据此告警跳过文件,即 #151/#152。checkpoint 与 composed provenance 路线 :1323-1333 从不被 /commit 调用;#229 仅 --approved-sha256 可达,CA 不传)
**共享检查(未注明即 (e)):**
180. 参数用法错误 → exit 2 — :1289-1293
181. 路径逃逸 git 根 — :1300-1301
182. git 根非目录 — :1304-1305 (d)
183. 工作树文件缺失 — :1307-1308 (d)
184. 给出多个 provenance 模式 — :1315-1318
**收养路线(未注明即 (b)):**
185. --task-id 缺失 — :1136-1137
186. --report-sha256 非法 — :1138-1139
187. report 不可读 — :1140-1143
188. report digest 不匹配 — :1144-1149 (c)
189. report 非法 JSON — :1039-1042
190. report 非对象 — :1043-1044
191. 任务绑定不匹配 — :1045-1050
192. 文件名不匹配 — :1051-1064
193. 无 dev 对象 — :1066-1068
194. ownership 数组非字符串 — :1069-1073
195. files_modified claim 不恰为一个,或存在 files_created claim — :1083-1086
196. contract 缺失 — :1089-1091
197. contract 路径不匹配 — :1092-1094
198. admission 模式不匹配 — :1095-1096
199. pre_edit/final 非对象 — :1100-1101
200. status 非 ?? — :1102-1103
201. hash 非法 — :1106-1107
202. before hash 等于 final hash — :1108-1109 (c)
203. pre-edit provenance 非法 — :1111-1122
204. final_source_hashes 不一致 — :1123-1125 (c)
205. evidence_source 缺失 — :1126-1127
206. 目标是 symlink 或非常规文件 — :1156-1157 (c)
207. 活状态不恰为 ?? — :1158-1159 (c)
208. 文件已在索引中 — :1160-1162 (c)
209. 二进制文件 — :1164-1165 (c)
210. 字节与被证实的 final hash 不同 — :1166-1167 (c)
**ownership-ledger 路线(未注明即 (b);dev 侧:无):**
211. ledger 或 snapshot 参数缺失 — :1334-1335
212. ledger 文件缺失 — :1338-1339
213. ledger 不可读 — :1340-1344
214. ledger 为空或非列表 — :1346-1347
215. snapshot 缺失 — :1349-1350
216. 二进制文件 — :1356-1357 (c)
217. snapshot 与文件 CRLF 行尾不一致 — :1361-1362 (c)
218. 文件 mode 变化 — :1365-1367 (c)
219. **新增:** 配置了 content-filter 属性 — :1378-1385 (c)
220. 文件未被跟踪 — :1392-1397 (c)
221. 文件已有 staged 内容 → unstage 并排除 — :1404-1415 (c)
222. ledger 条目畸形 — :1436-1437
223. ledger 条目 old 字符串为空 — :1441-1446
224. old 字符串不可唯一定位 — :1447-1451 (c)
**暂存中的基础设施/内容失败:**
225. 临时索引创建失败 — :1169-1171 (d)
226. add 进临时索引失败 — :1173-1175 (d)
227. 计划 patch 不可用 — :1176-1182 (d)
228. patch 非 UTF-8 — :1183-1186 (c)
229. approved digest 不匹配(/commit 不可达)— :1188-1192 (c)
230. 真实 git add 失败 — :1206-1208 (d)
231. staged patch 在校验后改变 — :1209-1214 (c)
232. snapshot 等于 HEAD blob(I12)— :1454-1479 (c)
233. 重放编辑不能复现工作树 — :1480-1483 (c)
234. git diff --no-index 失败 — :1515-1517 (d)
235. git apply --cached 拒绝 patch — :1547-1552 (c)
236. **新增:** apply 后索引不匹配(I13)— :1561-1570 (c)

### J. 特权卫兵(PG;全部 exit 2。单次使用、绑仓库的 grant 设计也是 #248–#254 以可重试 grant_* 代码收场的原因,CA:1853-1855)
237. 命令的 git 二进制无法静态归类 — :1883-1926 (d)
238. 多于一个 -C 选项 — :844-850 (e)
239. -C 中未解析的 $VAR — :853-860 (e)
240. 环境残留 GIT_DIR/GIT_WORK_TREE/GIT_COMMON_DIR — :993-1001 (d)
241. commit 目标仓库无法定位 — :1003-1011 (d)
242. 一条命令多个 commit — :1012-1025 (e)
243. 内联环境重定向 — :1027-1028 (e)
244. --git-dir/--work-tree/--namespace 旗标 — :1029-1030 (e)
245. commit 前 cd/pushd — :1031-1032 (e)
246. grant 仓库不匹配 — :1059-1070 (d)
247. grant 分支不匹配 — :1076-1085 (d)
248. grant HEAD 不匹配 — :1101-1112 (d)
249. 无 grant → 默认拒绝 — :1292-1306, :1468 (d)
250. grant 过期(30 分钟 TTL)— :1258-1265, :1427-1432 (d)
251. grant 时间戳非 tz-aware ISO → 视为过期 — :1258-1265 (d)
252. grant 已花费:use-record witness 改变或 >3 次使用 — :454, :495-516, :1439-1440 (d)
253. witness 不可读(reflog 关闭或 unborn 仓库)→ 拒绝 — :478-491 (d)
254. grant 被 .lck 锁定(在途提交)→ 视为缺失 — :377 (d)
255. grant JSON 畸形 → 忽略后默认拒绝 — :316-333 (d)
256. 无 bulk sentinel 的 auto-bulk 提交 — :1408-1414 (d)
257. bulk sentinel 的 kind/origin 错误 — :1349-1352 (d)
258. 存在活动 grant 时 auto-bulk 提交被推迟 — :1399-1406 (d)

### K. 其他钩子
259. protected-runtime 卫兵对 commit 命令文本误报 — pretool-bash-safety.sh:209-214;CA:53-64 (d)
260. dev-report 命名 gitignored 文件时 gitignore 预检拦 changelog-analyst/QA 派发,除非 prompt 引用活 grant(E5);commit.md Step 7 prompt 模板不含 grant 路径 — pretool-gitignore-preflight.py:812-814 (c)
261. lane shard 存在而无 canonical 时聚合检查拦 Step 6 QA 派发(prompt 无锚定 task-id 即全局扫描)— pretool-aggregate-check.py:366-381 (b)
262. [CONDITIONAL] /do consent 旗标仍活 → 一切 Agent 派发被拦 — pretool-do-block-subagents.py:117-126(正常由 stop-cleanup-allowlist.sh:28-34 在回合结束清理)(d)
263. 编排器门拦第 6 次连续 Bash — pretool-orchestrator-gate.py:171-185 (d)
264. 编排器门对非白名单工具(如 manifest Write)每回合仅放行一次 — :184-185 (d)
265. 后台任务钩子拦未设 run_in_background:false 的 Agent 派发 — pretool-block-background-tasks.py:183-219 (d)
266. workflow 门在 TodoWrite 确认前拦工具 — pretool-workflow-gate.py:870 (d)
267. 读取尺寸卫兵拦主代理读 >600 行(如大 close-report)— pretool-read-size-guard.py:90 (d)
268. [CONDITIONAL] /commit QA 代理若被登记进 dev registry,SubagentStop E2E 检查拦 — subagentstop-e2e-enforce.py:230-280 (b)
269. [CONDITIONAL] 版本化报告未过 schema 时 SubagentStop artifact-contract 拦 — subagentstop-artifact-contract-enforce.py:308-318 (b)
270. [ADVISORY] bulk-commit 探测器 — pretool-bulk-commit-detector.py:135-163 (c)

### L. git 原生钩子
271. commands/dev*.md 被 staged 时 sentinel-lint 失败 — .git/keystone-hooks/preserved/pre-commit:20-27;hooks/sentinel-lint.sh:74-84 (c)
272. spec-id 集中化 lint 失败 — preserved/pre-commit:38-47;scripts/lint-spec-id-centralization.py:113-121 (c)。此 lint 在已安装钩子里,不在仓库模板 hooks/git-hooks/pre-commit
273. untracked 文件拦截模式 — hooks/pre-commit-check.sh:48-61。settings.json:11 置 0,现为惰性 (c)
274. 自动暂存错误退出 — pre-commit-check.sh:30-44。settings.json:10 置 0,现为惰性 (d)
275. [CONDITIONAL] reference-transaction keystone 拒绝 overnight actor 的 ref 更新 — .git/keystone-hooks/reference-transaction:39-45, :289 (d)

/commit 未验证项:#93、#161、#169(规则正则静态推断);#170(取决于 PreToolUse
payload 是否含 subagent_type,hooks/lib/agent_resolver.py:245-255);
pretool-overnight-hook-guard.py 是否拦 overnight 会话的 /tmp 写入(仅读了头部,未计入);
#33/#36/#37 的披露例外改判路径(resolve-dev-artifact-chain.py:869-925)未逐行追踪。

/commit 分节小计:A 10 · B 12 · C 30 · D 25 · E 6 · F 10 · G 14 · H 72 · I 57 · J 22 · K 12 · L 5 = 275。
advisory 共 8 项:#9、#97、#98、#105、#139、#146、#171、#179;惰性 2 项(#273、#274);overnight 限定 1 项(#275)。

---

## 第三部分:综合 — 为什么这些检查还活在 close/commit

### dev 侧缺口(检查无法前移的直接原因)
1. **resolve-dev-artifact-chain.py 只在 /dev 有后置条件**(commands/dev.md:1335-1343)。
   /dev-command 与 /dev-overnight 无任何调用 → close/commit 被迫重查约 40 项 artifact 条件。
2. **ownership 台账零 dev 侧执法**:check-owned-edits-ledger.py 无人接线;
   pretool-baseline-snapshot-preflight.py 未注册(且 untracked);
   → SOH 全部 57 项排除 + RCR ownership 门(#71–#73)只能在 commit 时爆。
3. **subagentstop-artifact-contract-enforce.py 只覆盖声明 report_version 的报告**,
   未版本化报告(多数)漏过 → close/commit 的 schema 门仍有存在理由。
4. **/do 路线只有 advisory 的 stop-do-report-gate** → close 时补查(101–106)。

### 现行必挂缺陷(不是"检查",是 bug)
- **/do 周期的 /close 永远被拦**:无 qa-report 却无条件武装 e2e 检查(close #141)。
- --codex /dev 周期残留 codex-enforce.json 挡非 codex close(close #146)。
- close --force 文档顺序与 workflow 门矛盾(close #8)。
- QA 临时 section 文件位置未指定而 /tmp 被 deny(close #147)。
- tracked 删除经 git rm 暂存疑被 bash-safety 拦 → 删除可能永远落不了库(commit #161)[INFERRED]。
- 同会话第二个 push-gate token / 第二次 manifest 写入被 write-guard 拦(commit #169、#83)[INFERRED]。
- --late-repair 下 ARTIFACT_CHAIN 为空 → close.md:315 KeyError(close #100)[INFERRED]。
- settings.json 丢失 score-update.sh 的 Bash allow 项 → close Step 3 会触发权限询问(close #188)。

### d 类(约 100+ 项)的定性
锁超时、grant TTL/nonce、HEAD 竞态、git 错误、钩子自身 import 失败等不是"检测",
是 close/commit 机制自身的运行时失败面;它们搬不到 dev 侧,只能通过机制重设计
(去 TTL、去竞态、可重入、幂等重试)消除。e 类中 task-id 相关已因推断机制大半消失,
剩余为参数互斥类。
