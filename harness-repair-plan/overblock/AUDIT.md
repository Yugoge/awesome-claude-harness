# 过度拦截审计：综合报告

- 仓库：Yugoge/awesome-claude-harness，本地 clone 位于 `/home/user/awesome-claude-harness`，只读使用。
- 探针基线：origin/master `a21dcbf9`，下文所有 `path:line` 都指这个提交。撰写本报告时 origin/master 已前进到 `83c3b352`（Train B #60）。
- 输入来源：7 个单元（bash-safety、search、caps-dispatch、writes、git、state-gates、permissions）。每条发现都经独立复核者复现后才收录，共 131 条。
- 说明：
  - 没有修改任何文件。
  - 为核对 P14 等在途分支，运行过一次 `git fetch -q origin`。这只更新了 clone 的 remote-tracking refs，工作树和本地分支都没有变。
- 记号：
  - 严重度分三档：日常（blocks-daily-work）、偶发（occasional）、罕见（rare）。
  - 复核结论分三种：确认、部分（复核修正了范围或修复方向）、补充（复核者自己发现的漏报，原文为 confirmed-by-skeptic）。
- 编号冲突：
  - `MB-2` 有两条：bash-safety 单元的 killall/pkill，以及 caps 单元的只读内置工具。
  - `M2` 也有两条：writes 单元的 cp/mv/tee 抽取，以及 search 单元的 `search-M2`。
  - 表中用单元前缀区分它们。

## 0. 结论速览

**拦截日常工作最多的五组：**
1. 编排者调用上限：只读调用也计数，被别的 hook 拒绝的调用也计数。
2. 子代理找不到一个能写的 scratch 位置。
3. 权限层的问题：allow 列表有缺口，`Read()` deny 条目会连带触发 CLI 的 cd 复合命令批准提示。
4. bash-safety 按原始文本的共现判断（数据被当成命令），约 50 条发现集中在这里。
5. 权限层的秘密文件 glob 按大小写不敏感的子串匹配，在有认证代码的仓库里天天撞上。

**与 P14 的关系（关键）：**
- P14-5（`origin/claude/p14-5-bash-safety`，head `8a932eb0`）把 bash-safety 的规则搬进 `hooks/lib/bash_safety_rules.py`。
- 它的 bar 1 规定，除 O1–O7 外判定一律不变；bar 5 规定不得新增名单。
- 我核对了 P14-5 head 上的 `service_rules`、`worktree_git_rules` 和 `SENSITIVE_NAME`：它们仍是原来的原始正则。所以 G4 的大部分修复必须等 P14-5 合并后，在 `bash_safety_rules.py` 上做。
- P14-5 已经修掉或删除的是 BS-01、BS-03、BS-04，以及引号/heredoc 内的敏感名误报（O6）。MB-1a/MB-1b 也已解决，因为 payload 现在走 stdin，剥离器在进程内运行。

**已被覆盖或在途、不需要新 lane 的：**
- P14-8 删除 BB-02..08，因为 owner 在 2026-11-16 决定允许分支和 PR。GIT-7、GIT-9、GIT-M2、GIT-M3 随之消失。
- P14-6 删除 TP-13/TP-14（Q5 (a)），消除 F06。
- P14-6/P14-10 改用 `shell_parse.write_targets`，消除 F03、F04、writes-M2、M14 的幻影目标。
- P14-11 的 O7 修掉 OG-03 和 OG-22。
- `claude/harness-newer-tools-design-a` 的 T2/T5 覆盖 CD-8 和 CD-10。

**lane 数量：**共 46 条单一根因的修复 lane，其中 9 条需要 owner 先拍板（标 `[owner]`）。

## 1. 根因组（按拦截日常工作的程度排序）

### G1 编排者调用上限把只读调用算进去（日常）

- **影响范围：**
  - 只影响主代理，子代理豁免。
  - 普通上下文和 /dev 内（TodoWrite 之后）都会触发；/do 可解除。
  - 只有在 overnight 窗口内，Agent 派发才会重置非白名单工具的计数。
- **示例：**
  - 5 次只读 Bash（`rg -n 'def add' .`、`git log --oneline -5`、`find . -name '*.py'` 等）之后，第 6 次 `rg -c x .` 被拒。
  - 同一回合的第二个 `WebSearch{query:'python asyncio wait_for cancel'}` 被拒。
  - 第二个 `mcp__context7__resolve-library-id{libraryName:'pydantic'}`、第二个 `LSP goToDefinition`、第二个 `BashOutput` 都被拒。
- **判定代码（`hooks/pretool-orchestrator-gate.py`）：**
  - `:234`：Bash 上限，`BASH_MAX_CONSECUTIVE=5`，定义在 `:86`。
  - `:237`：非白名单工具每回合 1 次，定义在 `:87`；白名单在 `:66-79`。
  - `:341`：计数发生在 PreToolUse、总判定之前。`:327` 的注释写明这是有意为之的 fail-strict。
- **原文拒绝行：**
  - `[Orchestrator Gate] BLOCKED: Bash used consecutively beyond limit (6/5): Bash counts its calls since the last Agent dispatch or prompt, any other non-whitelisted tool its calls this turn, whatever ran between them.`
  - `[Orchestrator Gate] BLOCKED: WebSearch used consecutively beyond limit (2/1): ...`
- **保护对象：**Orchestrator-Only Rule，即编排者把实际工作委派出去，不自己动手。
- **放大效应（CD-4）：**被 workflow-gate 或 bash-safety 拒绝的调用照样占一个名额。所以 G4 的每一次误报，都同时消耗编排者的 5 次 Bash 名额。
- **文档冲突：**CLAUDE.md:49 写 WebSearch/WebFetch 每回合一次；而 :83-84 要求每个库都查 Context7，并允许 1-3 次 WebSearch 直接做。
- **修复方向（保留委派约束）：**
  - (1) 只读检索工具单独设预算：WebSearch、WebFetch、Context7 和明确列名的只读 MCP 每回合最多 3 次。只读内置工具（LSP、ReadMcpResourceTool、ListMcpResourcesTool、TaskOutput/BashOutput）并入白名单。
    - 预算在 PreToolUse 计数，Agent 派发不重置，因为同一条消息里的并发调用会同时通过 PreToolUse。
    - 不能按名字模式（`get_*`、`*search*`）放行 MCP 工具，因为第三方 MCP 可以给有副作用的工具起这种名字。
  - (2) 被其他 hook 拒绝的调用退回名额。只认结构化的 hook 拒绝标记，不认结果文本；结果文本可以伪造，例如一个打印 "PreToolUse:Bash hook error" 再失败的命令。
    - 退额在下一次 PreToolUse 或下一个 prompt 时结算，因为 bash-safety 是独立进程，launcher 拿不到它的判定。
  - (3) 只读 Bash 不计数，需要 owner 决定，因为 CLAUDE.md:48 明文规定了这个上限。
    - 必须基于解析后的命令判断（shell_parse），不能只看首词。
    - 下列都带副作用，必须继续计数：`git log --output`、`git -c core.pager=`、`--ext-diff`、`rg --pre`、`find -delete/-exec/-fprint`、`sort -o`、`sed 'w FILE'`、awk 的 `system()`。
  - (4) 编排者写 session scratch 不计次，需要 owner 决定。只放 TMPDIR 和 session scratch，不得给 gate 会读取的产物路径开例外。

### G2 子代理没有能写的 scratch/输出位置（日常）

- **影响范围：**
  - 所有 harness 角色的子代理；主代理、Explore、general-purpose 都放行。
  - 涉及 Bash 重定向/tee/cp 以及 Write/Edit。
  - 普通上下文和 /dev 表现相同。
- **示例：**
  - dev 执行 `python3 -m pytest -q > /tmp/pytest-out.txt 2>&1`。
  - qa 执行 `python3 -m pytest -q > $TMPDIR/out.txt 2>&1`，目标按字面 `$TMPDIR/out.txt` 判定后被拒。
  - dev 执行 `python3 -m pytest -q > .claude/scratch/out.txt 2>&1`。
  - qa 执行 `... | tee tests/reports/run.txt`。
- **判定代码：**
  - `hooks/pretool-tool-policy.py:425-433`（判定）和 `:1355-1360`（调用点）：任何 /tmp、/var/tmp 路径。
  - `:398-400`、`:422-423`：`.claude/scratch/` 下凡不符合 `<x>/<role>/<agent_id>/` 形状的，一律算作 sibling。
  - `hooks/lib/policy_registry.py:268-275`，经 `pretool-tool-policy.py:1346-1353` 调用：角色写前缀行。
- **原文拒绝行：**
  - `BLOCKED by tool-policy.v1: {"role":"dev","tool":"Write","target":"/tmp/pytest-out.txt","deny_reason":"arbitrary /tmp and /var/tmp are denied for every role; use the managed scratch namespace .claude/scratch/<session>/<role>/<dispatch>/"}`
  - `... "deny_reason":"sibling scratch target denied: actor-exact namespace"}`
  - `... "deny_reason":"write target /tmp/pytest-out.txt not in allowed_write_path_prefixes"}`
- **保护对象：**
  - 默认 state dir 就在 /tmp，里面有 agentic-commit grant、/do sidecar、commit-msg 文件和计数器。
  - 兄弟派发的 scratch。
  - D8 角色分离。
- **复核要点：**
  - 不能直接放开 /tmp 下的新文件，因为并行 lane 会撞上同名文件。
  - dev 行连 `*/tmp/claude-scratch/dev/` 都没有。
  - 没有任何 hook 把 agent_id 交给子代理，所以拒绝信息指向的路径子代理根本拼不出来。
  - agents/dev.md:91 叫 dev 写 `.claude/scratch/`，这个位置本身被拒。
  - scratch 规则跳过含 `$` 的词（`:414-415`），所以 `> $TMPDIR/x` 对 dev 反而能过（拼写依赖）。而前缀层对 qa 按字面判定，又把同一个合法路径拒了。
- **修复方向：**
  - SubagentStart 时给每次派发一个专属 scratch 路径（additionalContext 加 TMPDIR）。
  - 判定前用派发自己的环境展开 `$TMPDIR`、`$(mktemp)`；展开不了的词，对受限角色仍然拒绝。
  - 补上 dev 的 temp 行。
  - 只有当 `rel[1]` 是已知角色、且 `rel[2]` 是另一个派发 id 时，才判为 sibling。
  - harness 状态名单直接复用 `origin/claude/ob-shared-state` 已加的 `hooks/lib/harness_temp_state.py`。
  - 验证类角色另开一个运行日志位置：从 `/tests/` 拒绝中切出 `tests/reports/`。

### G3 权限层的 allow 缺口和 cd 批准提示（默认模式下日常；无头或 overnight 时直接变成拒绝）

- **影响范围：**
  - Bash、Write、WebFetch；主代理和子代理相同。
  - bypassPermissions 模式不受影响。
  - 已注册的 hook 都放行这些调用，是 CLI 自己在问。
- **示例：**
  - `cd src && grep -rn TODO .`、`pytest -q`、`gh pr view 12`、`git -C src log --oneline -3`。
  - Write `src/newmodule.py`。
  - `echo done > /tmp/probe-report.md`。
- **判定位置（settings.json）：**
  - `:236-248`：只要存在任何一条 `Read()` deny，就会打开 CLI 的 cd 复合读守卫。
  - `:38-186`：allow 列表。
  - `:153-163`：Edit 的 allow 只覆盖清单、.claude/agents|commands、docs、scripts、tests/generated。
  - `:84-88`：git 条目锚定在 `git <sub>`，所以 `git -C` 一条都匹配不上。
  - `:167`：`Read(/tmp/**)` 只有一个前导斜杠，按 settings 文件所在目录解析，因此对 /tmp 不生效。
- **原文提示：**
  - `grep reads a file by a relative path after a cd in a compound command; which file that is cannot be resolved statically while a Read() deny rule is configured, so this needs approval.`
  - `This command requires approval`
  - `Claude requested permissions to write to <cwd>/src/newmodule.py, but you haven't granted it yet.`
  - `Output redirection to '/tmp/probe-report.md' needs approval. The path is outside the working directories for this session (...)`
- **保护对象：**
  - 秘密文件（Read deny）。
  - 未列名程序要经过人确认。
  - 工作目录边界。
- **修复方向：**
  - 补具体的只读/测试 allow：pytest、make test/-n、ruff check、mypy、gh pr|issue|run view/list、git fetch、tar -tzf、unzip -l、systemctl status、kubectl logs、`git -C * log|status|diff *`、`rg --files`。
  - 不要加 `Bash(rg:*)`（`--pre` 会执行程序）或 `Bash(git -C:*)`（会绕过 `git push --force` 的 deny）。
  - 项目内写入需要 owner 决定：用 `Edit(./**)` 或 acceptEdits。deny 和 hook 仍然挡住 .claude/settings*.json 与 .claude/hooks/。
  - `Read(/tmp/**)` 改成 `Read(//<scratch 目录>/**)`，并配一条精确的 `Edit(//<scratch 目录>/**)`。
    - 绝不要 additionalDirectories ["/tmp"] 再配 `Edit(//tmp/**)`：那样 agent 可以静默写 /do consent flag（state 根默认在 /tmp）。
  - cd 守卫：保留 Read() 条目，改工作惯例为带路径操作数搜索（`grep -rn PAT src`），写进 CLAUDE.md 和 agents/commands 的散文。

### G4 bash-safety 按原始文本共现判定，数据被当成命令（单条偶发或罕见，合起来约 50 条，同时消耗 G1 的名额）

- **影响范围：**
  - 主代理和子代理；普通上下文和 /dev 相同，因为 bash-safety 不读 span。
  - /do 的出口在大多数规则之前，所以 /do 下多数规则放行。例外是 BS-29 和 MB-1c：/do 下反而更严。
- **子簇与判定代码（均在 `hooks/pretool-bash-safety.sh`）：**
  - 服务、进程、磁盘、docker、workflow：
    - `:1704` docker daemon、`:1711` daemon.json、`:1729` compose down、`:1736` prune -a。
    - `:1747` dd/mkfs/fdisk、`:1754` killall/pkill、`:1763` kill -sig。
    - `:1774`（另见 `:483`）systemctl、`:1788` workflow rm/mv。
    - `:1920` npm -g、`:887` HTTP /stop、`:874` /tmp 下的包装脚本。
  - git 工作树：
    - `:1969` stash push、`:1993` 裸 stash、`:2023` checkout 宽路径、`:2061-2063` restore --source、`:2577-2581` git clean 的兜底扫描。
    - `:2139` force push、`:2176` ref 变更、`:2640` 子代理历史改写、`:2680-2692` revert。
  - 哨兵和工件命名空间：`:900`、`:922`、`:1036`、`:1118`，以及 `:1258`/`:1424-1594`/`:1613`（bulk）。
  - 敏感名：`:1686`、`:1692`。
  - 其它：
    - `:1637` session_dirs.txt。
    - `:1649`/`:1678` 硬禁脚本。
    - 环境变量超过 128 KiB 时的 E2BIG：`:324`→`:410`、`:1165-1177`、`:702-717`。
- **示例：**
  - `kill -0 "$SERVER_PID" 2>/dev/null && echo running`
  - `grep -rn "docker compose down" docs/`
  - `cat > docs/auth-flow.md <<'EOF'` 正文含 `login form -> password check`
  - `rg -n 'claude-bulk-commit-sentinel-' docs`
  - `npm install --save-dev eslint-config-google`
- **原文拒绝行（节选）：**
  - `BLOCKED: kill with signals is forbidden — use graceful shutdown methods`
  - `BLOCKED: Attempting to write to sensitive file via Bash`
  - `BLOCKED: bare 'git stash' (implicit push) requires explicit user approval`
  - `BLOCKED: bulk-commit-sentinel-write — Bash command references protected bulk sentinel path OR sentinel-writer script (write-bulk-commit-sentinel.py) in a compound or write context — FORBIDDEN`
  - `BLOCKED: npm install -g is FORBIDDEN from this environment`
- **保护对象：**
  - 真实的 kill、dd 和 docker/systemd 破坏操作。
  - stash 与宽路径 checkout 组合造成的数据丢失。
  - 伪造 /commit 和 bulk 哨兵。
  - 改写 .env 等秘密文件。
- **修复方向：**每条规则都改为对 `shell_parse.walk` 的「命令字 + 本简单命令自己的参数或写目标」做谓词。三条硬约束：
  - (a) 命令字要识别包装器：sudo、xargs、env、nohup、timeout、command、exec、nice、setsid，以及 `/bin/kill` 这类路径形式。
  - (b) 剥离视图会把 eval 字符串和 `python -c`/`node -e` 的 payload 清空（`eval "git stash push"` 剥离后成了 `eval ""`）。这些 payload 必须保留原始文本检查，或者由解析器暴露出来。否则下面这些今天还能被拒的命令会开始放行：`eval "systemctl restart docker"`、`eval "docker compose down"`、`python3 -c 'os.system("docker system prune -a -f")'`、`eval "git stash push"`。
  - (c) 精确值：
    - kill 只豁免 `-0`、`-l`、`-L` 这几个精确 token；`kill -09` 是 SIGKILL。
    - dd 的 `of=` 若在 `/dev/` 下且不是 null、zero、stdout、stderr 或 `fd/*`，仍然拒绝；`of=` 无法解析时也仍然拒绝。
- **P14 关系：**
  - P14-5 把 BS-25/26/28/29a 删掉并入 git-privilege-guard，于是它们的误报改由 G8 处理。
  - BS-02 和 BS-20 并入 runtime_guard，需要复核存活规则。
  - BS-08 并入 `settings.json:188`。
  - 其余规则在 P14-5 中原样保留。

### G5 权限层 deny 条目过宽（含认证代码的仓库日常；其余偶发或罕见）

- **影响范围：**
  - Read、Write/Edit，以及 Bash 的读写操作数：Read 规则也作用于 cat/grep/sed -n/wc/diff/cp 的源，Edit 规则也作用于 touch、`>`、sed -i。
  - Skill。
  - 主代理和子代理；bypassPermissions 下同样拒绝。
- **示例：**
  - Read `src/auth/ForgotPassword.tsx`（大小写不敏感匹配）。
  - Read `.env.example`、`ls config/secrets`、Read `src/components/Shadow/index.tsx`。
  - Skill `docs`（被 `Skill(do:*)` 前缀命中）。
  - `kubectl apply --dry-run=client -f k8s/deploy.yaml`。
- **判定位置（settings.json）：**
  - Edit：`:220`、`:221`、`:223`、`:225`、`:228`。
  - Read：`:237-239`、`:241-242`、`:245`。
  - Skill：`:249-270`。
  - 整动词：`:192`、`:197-198`、`:201`、`:219`。
- **原文拒绝行：**
  - `File is in a directory that is denied by your permission settings.`（tool_use_error）
  - `Permission to use Bash with command grep -n TODO src/auth/password_reset.py has been denied.`
  - `Skill execution blocked by permission rules`
  - `Permission to use Bash with command kubectl apply --dry-run=client -f k8s/deploy.yaml has been denied.`
- **保护对象：**
  - 秘密文件：password.txt、db_password、.env.*、secrets.*、credentials、shadow。
  - human-only 命令不能被 agent 经 Skill 自调用（lesson 15）。
  - 发布和集群变更。
- **修复方向：**
  - 秘密 glob 改成枚举确切名字。复核者实测，发现者提出的精简名单会放出以下文件：password.txt、db_password、secrets.toml、.env.staging/.development/.test、项目内 .aws/credentials、裸 credentials。所以名单必须包含这些密码存放形式和所有带值的 env 变体。
    - 另一个做法：`.env.*` 改由 hook 实现，只放行模板（.env.example、.env.sample、.env.template）。
  - `**/shadow` 改为 `**/etc/shadow`，`//etc/*` 保留。
  - `*.pem` 接受现状，或改成按内容判断的 hook，且该 hook 必须覆盖 Bash 操作数。
  - Skill 改为精确的 `Skill(<stem>)`；它同样挡带参数的调用。同步修改 `hooks/tests/test_skill_deny_coverage.py:48,63,68` 和 `hooks/tests/test_codex_skill_not_denied.py:93,95`。
  - 整动词需要 owner 决定，可改为 ask。deny 不能开例外，因为 allow 不会覆盖 deny。
- **另见：**`**/` 只作用于 cwd 以下，所以 `~/.aws/credentials` 和 `~/.env` 没有被保护（欠防御，见 §5）。

### G6 写目标抽取器生成幻影目标（偶发；P14-6/P14-10 改用解析器后应消失，只需 pin）

- **影响范围：**除 dev 以外的子代理角色（dev 的 `*` 前缀接纳幻影目标）；M14 也影响主代理。
- **示例：**
  - qa 执行 `sed -n '1,40p' src/user-info.py`，得到幻影目标 `y`。
  - qa 执行 `python3 -m pip install -r requirements.txt`。
  - qa 执行 `grep -rn mv src/ docs/`。
  - 主代理执行 `grep -c mv /tmp/claude-do-task-x.json`。
- **判定代码（`hooks/lib/bash_write_targets.py`）：**
  - `:259-260`、`:759-767`：sed -i。
  - `:262-263`、`:790-806`：install。
  - `:256`、`:717-746`、`:317`、`:337-345`、`:817`、`:865-872`：cp/mv/tee/chmod。
  - `:1324`、`:1329`：rm/mv 的 touched 路径。
- **原文拒绝行：**`BLOCKED by tool-policy.v1: {"role":"qa","tool":"Write","target":"y","deny_reason":"write target y not in allowed_write_path_prefixes"}`
- **保护对象：**让角色写前缀和受保护路径看到真实的写目标。
- **修复方向：**由 P14-6 和 P14-10 覆盖。在这两条 lane 中把上述示例 pin 为 allow。同时 pin 以下仍须识别为写：`-ni`/`-Ei`/`-i.bak`/`--in-place` 和多个文件操作数、`sudo install`、`xargs install`、`/usr/bin/install`、`cp -t`/`--target-directory`。

### G7 角色工具表默认拒绝只读和簿记工具（偶发）

- **影响范围：**子代理角色。agents/*.md 都没有 `tools:` frontmatter，所以 CLI 会提供这些工具，策略再把它们拒掉。
- **示例：**
  - graphify 用 `Grep {pattern:'blast'}`。
  - dev 用 `TodoWrite`。
  - dev 用 `TaskOutput {task_id:'b1'}`：后台 Bash 允许启动，却读不到输出也停不下来。
  - dev 用 `mcp__context7__resolve-library-id {libraryName:'react'}`。
- **判定代码：**
  - `hooks/lib/policy_registry.py:259-265`（`_check_tool_lists`），经 `hooks/pretool-tool-policy.py:1346-1353` 调用。
  - `policies/tool-policy.v1.json:743-744`（graphify）、`:131`（dev）、`:93`（ba）。
- **原文拒绝行：**`BLOCKED by tool-policy.v1: {"role":"dev","tool":"WebSearch","target":null,"deny_reason":"tool WebSearch not in allowed_tools"}`
- **保护对象：**按角色限定能力，减少网络外联和提示注入的入口。
- **修复方向：**
  - 所有角色加 Grep、Glob、TodoWrite。
  - 持有 Bash 的角色加 TaskOutput、BashOutput、TaskStop、KillShell。
  - dev、ba、qa、architect 加 Context7，与 CLAUDE.md:83 一致。
  - dev/qa 是否给 WebFetch/WebSearch 由 owner 决定。
  - 不能一刀切给所有角色网络工具。

### G8 git 守卫把引号、管道、heredoc 和注释里的文本当成调用（偶发）

- **影响范围：**主代理和子代理；普通上下文和 /dev 相同。
- **示例：**
  - `rg -n 'git reset --hard|git push --force' .`
  - `grep -rn 'git push origin\|git merge origin' . | head -5`
  - `cat > docs/recovery.md <<'EOF'` 正文中有一行 `git reset --hard origin/master`
  - `git log --oneline -3  # newest first; git push is not needed`
  - `"$VIRTUAL_ENV/bin/pip" show pytest`
  - `git push --help`
- **判定代码：**
  - `hooks/lib/git_command_classifier.py`：
    - `:1781-1783`、`:1792`：引号内的调用一律保留，除非引号的所有者是 echo/printf/grep。
    - `:1816-1832`：管道接到 head/wc/sort 时被当作未知消费者。
    - `:1754-1769`、`:138`：没有 heredoc 和注释意识。
    - `:1665-1671`：dynamic_git_token。
    - `:1663-1664`：obfuscated。
    - `:1593-1595`：unresolved_shell_string。
  - `hooks/pretool-git-privilege-guard.py`：
    - `:2017`：入口。
    - `:2041-2083`/`:2059`：残余拒绝。
    - `:1807-1817`、`:913-924`：只看子命令名。
  - `hooks/pretool-gitignore-preflight.py:726-833`→`:845`。
- **原文拒绝行：**
  - `BLOCKED: agent git push - agents are not authorized to push to remote from an agent context.`
  - `BLOCKED: agent git command could not be statically classified.`
  - `BLOCKED: agent direct git plumbing is forbidden (R6).`
  - `BLOCKED: gitignored deliverables detected: .pytest_cache/v/cache/lastfailed`
- **保护对象：**被 shell 或解释器实际执行的字符串中的 push、merge、reset --hard、ref 变更、commit 和 plumbing。
- **修复方向：**
  - 文本型所有者加入 rg、git grep、`git log --grep`。rg 只在没有 `--pre` 时算。
  - 不要加入 ag、ack：它们的 `--pager` 走 shell。
  - 管道消费者：head、tail、wc、sort、uniq、cut、tr、less、column、nl 进入 stdin 消费者表，不进入文本所有者表（`sort --compress-program` 会执行程序）。
  - heredoc：喂给 cat/tee 或重定向到文件的 heredoc 是数据；喂给 bash、sh、ssh、`python3 -`、`source /dev/stdin` 的仍然是代码。
  - 去引号：`\git` 和 `git 'push'` 都必须先去引号再判定。今天 `git 'push' --force` 能通过所有 hook，是欠防御。
  - help 和 dry-run：
    - 只豁免 commit 的 `--dry-run`（commit 的 `-n` 是 `--no-verify`），以及 push 的 `-n`/`--dry-run`。
    - help 豁免要求不带 `-c`/`--config-env`，因为 help.browser 会执行命令。
  - dynamic 命令字：只采纳「展开只出现在目录部分」这一支；`${VAR:-default}` 这一支会开出绕过（`G=git; ${G:-kubectl} push`）。
  - unresolved shell string：保留拒绝，只修改提示文案。
  - gitignore 预检：按被派代理的写能力判断，不按 subagent_type 名判断。
- **P14 关系：**
  - P14-2 用解析视图替换引号盲的切分器，应能修好 heredoc 和注释（GIT-2、GIT-M1）。但「文本型所有者」和「管道消费者」属于 P14-2 保留的判定，所以 GIT-1 需要在 P14-2 合并后单开 lane。
  - P14-4 拥有 git-privilege-guard。

### G9 配置、开关和包装器守卫把读当写、把提及当执行（偶发，主要出现在 harness 自身的工作中）

- **影响范围：**主代理和子代理；普通上下文和 /dev 相同。ON-GLOBAL-REGEX 需要同项目里有另一个 session 的 overnight 处于隔离窗口内。
- **示例：**
  - `sed -n '1,40p' ~/.claude/settings.json`
  - `awk 'NR<=20' .claude/settings.json`
  - `git -C ~/.claude diff --stat -- ~/.claude/settings.json`
  - `cp ~/.claude/hooks/pretool-launch.py /tmp/launch-copy.py`
  - `grep -rn "bash hooks/stop.sh" docs/`
  - `./scripts/stop.sh`（项目自己的脚本）
  - Write `/tmp/audit-notes.md`，内容提到 `.harness-switch/`
- **判定代码：**
  - `hooks/pretool-harness-switch-guard.py`：
    - `:437`（writes_settings_file，`:221`）。
    - `:440`（TYPED `:75`、NESTED `:74`）。
    - `:445-454`；WRITES 在 `:76`，会匹配裸 `>` 和 tee/dd 这类词。
    - `:455-459`（settings_writes 在 `:279`/`:312-333`，_written_words 在 `:196`）。
    - `:171-173`：_read_only 把 `-C <dir>` 当成子命令。
    - `:482`、`:486-491`、`:492`、`:508`。
  - `hooks/pretool-claude-config-guard.py:54-71`、`:160-169`、`:309-314`。
  - `hooks/pretool-overnight-hook-guard.py:644/:647`，路径为 `:2461→:739→:728`。
  - `hooks/pretool-bash-views-guard.py:30`、`:93-96`。
  - `hooks/pretool-cp-state-write-guard.py:61-70`、`:113-117`。
  - `hooks/pretool-wrapper-userintent.py:69-80`、`:149`（消耗哨兵）、`:176`、`:186`、`:191`。
- **原文拒绝行：**
  - `BLOCKED: harness-switch: this Bash command writes the harness home's settings.json. Only the owner switches the harness, by typing /harness off or /harness on; nothing an agent runs, writes or schedules does.`
  - `BLOCKED: claude config guard: agent Bash write to .claude/hooks/ is forbidden outside an explicit refactor session.`
  - `USER-INTENT GUARD: direct invocation of the /stop release wrapper is blocked. This wrapper (break-overnight-lock.py / stop.sh) is the only sanctioned setter of isolation_released_at and may run ONLY via the /stop slash command, which writes a single-use user-intent sentinel. No live sentinel was found for this session, so an overnight actor cannot self-release isolation.`
- **保护对象：**
  - 只有 owner 能切换 harness。
  - harness home 的 settings 文件和 CLI 会加载的 settings。
  - harness 的 hooks/ 和 commands/ 文件。
  - views 和 cp-state 只能由 spec-check.py 写。
  - overnight 隔离只能经 /stop 解除。
- **修复方向：**
  - 写入判断改为「受保护路径本身是被写的词」，而且要对 cd 目标解析，不能只对 payload 的 cwd 解析。
    - 今天 `cd ~/.claude && sed -i 's/block/off/' settings.json` 能通过整条管线，是欠防御。
  - READ_ONLY 只加入没有输出操作数的读者：nl、cut、tr、column、od。
  - 不要加入 uniq、`xxd -r`、awk（awk 可在程序里 `print >`）或 `sort -o`。
  - 开关程序和嵌套 claude 只在命令字位置判定，包装器透明处理。
    - 进程替换 `python3 <(cat harness-switch)` 今天能通过，是欠防御，需一并修。
  - claude-config-guard 改用写目标判断，并且必须把 `cp -t` 当作目的地。P14-11 删除 OG-01/02 之后，它是这两类输入唯一的拒绝者。
  - /stop 包装器按解析出的执行判定，按 realpath 匹配 CLAUDE_HOME 下的包装器，只在真正执行时才消耗哨兵。
- **P14 关系：**
  - P14-12 只把 `writes_settings_file` 换到解析器上。我在 `4f4e81dd` 上核对过，READ_ONLY、`_read_only`、TYPED、NESTED 都原样保留。
  - P14-10 改动了 wrapper-userintent 的 heredoc 读取，但没有改它的正则。

### G10 工作流、义务和汇总门作用过宽（偶发）

- **影响范围：**
  - 主代理；只有 search-04 在子代理 payload 带有主 transcript 时也会出现。
  - checklist 命令在第一次 ok TodoWrite 之前，或者完成之后。
- **示例：**
  - `/dev` 后、TodoWrite 前执行 `Grep {pattern:'def'}`。
  - `/test` 被放弃后，再问一个问题并执行 `Read toy/__init__.py`。
  - `/spec` 8 步全部完成后，提交一个 2 项的 TodoWrite。
  - Agent Explore 的 prompt 里提到 `<obligation v="1">`。
  - 无义务的 qa 派发遇上 docs/dev 中被遗弃的 fan-out。
- **判定代码：**
  - `hooks/pretool-workflow-gate.py:1198-1199`、`:1220-1234`（锁在 `hooks/lib/todo_canonical.py:293-298`）。
  - `hooks/pretool-todo-validate.py:461-462`→`:225`、`:471-473`。
  - `hooks/pretool-obligation-gate.py:238`、`:269-271`。
  - `hooks/pretool-aggregate-check.py:639`、`:250`、`:646`。
- **原文拒绝行：**
  - `⚠️  CHECKLIST NOT STARTED: /dev workflow is active.`
  - `BLOCKED TodoWrite (canonical validation):`
  - `OBLIGATION GATE BLOCK (pretool-obligation-gate):`
  - `BLOCKED Agent dispatch (qa): a fan-out's lane reports and canonical aggregate are not all collected.`
- **保护对象：**
  - checklist 的步骤顺序，以及 Stop gate 读取的忠实列表。
  - producer 派发必须带合法义务块。
  - 并行 /dev 的 QA 必须在 canonical 汇总产出之后才运行。
- **修复方向：**
  - not_started 锁放行 Read、Grep、Glob。Bash 保持锁定，除非有严格的只读白名单。
  - 列表全部完成后，接受与 canonical 没有共同步骤文本的外来列表。所有 span 读者必须同时改：workflow gate、Gate 4、Stop gate。
  - 义务门：只有在 `parse_obligation` 返回 Rejection 且 `_block_required` 为 False 时才放行。对 ParsedObligation 不能跳过角色和时钟检查；并确认 SubagentStop 的 producer gate 把 Rejection 当作「无义务」。
  - 汇总检查：无义务且无 span 时只发警告，有作用域的派发仍然拦截。

### G11 杂项单点

**search-03：Read 尺寸守卫**
- 代码：`hooks/pretool-read-size-guard.py:84-90`；问题在 `:52-55` 没有考虑 offset。
- 原文：`[Read Size Guard] File too large: <file_path> (650 lines, limit 600).`
- 修复：按 `min(limit or 2000, total - offset + 1)` 计算实际返回行数。

**search-08：grep 回溯探针把 systemd-run 启动延迟当成爆炸**
- 代码：`hooks/pretool-grep-backtrack-guard.py:1140-1143`。
- 原文：`BLOCKED: this text-search regex catastrophically BACKTRACKS in Claude Code's embedded grep engine.`
- 修复：用 scope 内的启动标记区分两种情况：「从未启动」fail-open；「启动后超时或卡住」仍然拒绝。

**CD-7：ExitPlanMode 永久拒绝**
- 代码：`hooks/pretool-orchestrator-gate.py:313`（`:81`）。
- 原文：`[Orchestrator Gate] Permanently blocked: ExitPlanMode (/do does not unlock it).`
- 修复：只在 payload 的 `permission_mode == 'plan'` 时放行，需要 owner 决定，并修改 CLAUDE.md:50。

**F05：Write 不得覆盖已有文件**
- 代码：`hooks/lib/write_gate/overwrite.py:135-144`。
- 原文：`[Write Guard] BLOCKED: File already exists: <path>`
- 修复：只豁免 temp、scratch、未跟踪的生成输出，需要 owner 决定。

**CD-8、CD-10：已有在途修改**
- 代码：`hooks/pretool-block-background-tasks.py:152`。
- 在途：`claude/harness-newer-tools-design-a` 的 T2（允许给自己已完成的子代理发 SendMessage）和 T5（`/allow Workflow`）。

**CD-9：保留**
- 代码：`:191`。原因：后台进程会活过本回合的各道 gate。

**BS-30、BS-31、GIT-8、HS-NESTED-FIXTURE：暂缓**
- 复核者指出，放开它们会带来 TOCTOU、符号链接或嵌套会话的风险，见 §4。

## 2. 修复 lane（每条一个根因）

**波次：**
- **W1：**不依赖 P14 的 lane，可立即开始。
- **W2：**等 Train C（`origin/claude/train-c`，汇合 P14 各 lane）合并后再开始。lane 内注明它依赖的具体 P14 lane。

**共同重叠：**
- `settings.json` 还被 `claude/harness-newer-tools-design-a` 和 `claude/sharp-albattani-qfl02k` 改动。
- `CLAUDE.md` 被多个在途分支改动，P14-8 会重写其中的 Branches 一节。
- removal-policy lane（`origin/claude/fix-removal-data-args`，任务 #31）拥有 `hooks/lib/bash_execution_boundary.py`、`hooks/lib/shell_parse.py`、`bash_active_syntax_census.py`。下面任何一条 lane 都不改这三个文件。凡是需要解析器新视图的，都向 P14-1 或 removal lane 提需求。

### G1 编排者上限

**OB-L01 只读和检索工具的每回合预算（W1）**
- 覆盖：search-02、CD-1、CD-2、CD-5、caps/MB-2。
- 文件：`hooks/pretool-orchestrator-gate.py`（ALWAYS_ALLOWED 与一个新的 read budget）、CLAUDE.md:49/:84（统一措辞）、对应测试。
- 必须放行：
  - 同一回合的第 2、3 次 WebSearch 和 WebFetch。
  - 第 2 次 `mcp__context7__resolve-library-id` 和 `get-library-docs`。
  - 第 2 次 LSP、BashOutput/TaskOutput、ReadMcpResourceTool。
- 必须仍拒绝：
  - 同一回合的第 4 次 WebSearch，即使中间插入了 Agent 派发。
  - 同一回合的第 2 次 Edit。
  - 第 2 次 `mcp__github__create_pull_request`。
  - 名字形如 `get_*` 但没有列名的第三方 MCP 工具。
- 重叠：`claude/harness-newer-tools-design-a` 的 T4 改了同一个文件的白名单（Monitor、TaskStop、ListAgents、PushNotification），需在它之上 rebase。

**OB-L02 被其他 hook 拒绝的调用退还名额（W1）**
- 覆盖：CD-4。
- 文件：`hooks/pretool-orchestrator-gate.py`（在下一次 PreToolUse 或 prompt 时，按 tool_result 中的结构化 hook 拒绝标记退额）。
- 必须放行：/dev 中 TodoWrite 之前有 3 次 Bash 被 checklist 锁拒绝；写入 canonical TodoWrite 之后，5 次 `git status --short` 全部执行。
- 必须仍拒绝：
  - 第 6 次实际执行的 Bash，包括退出码非零的那些。
  - 一个先打印 `PreToolUse:Bash hook error` 再失败的命令，它照样计数。
- 重叠：同 L01（同一文件），与 L01 和 L03 串行。

**OB-L03 只读 Bash 不计入 5 次上限 [owner]（W2，依赖 P14-1）**
- 覆盖：search-01、CD-3。
- 文件：`hooks/pretool-orchestrator-gate.py`（经 `lib/shell_parse`）、CLAUDE.md:48。
- 必须放行：同一回合内 `git status --short`、`git log --oneline -5`、`rg -n def src`、`ls src`、`wc -l f`、`git show --stat HEAD` 共 6 次以上。
- 必须仍拒绝（全部继续计数）：`python3 x.py` 这类命令的第 6 次；`git log --output=/tmp/x`、`rg --pre sh x`、`find . -delete`、`sort -o f x`、`git -c core.pager=sh log`、含 `$(...)` 或重定向的命令。

**OB-L04 编排者写 session scratch 不计次 [owner]（W1）**
- 覆盖：CD-6。
- 文件：`hooks/pretool-orchestrator-gate.py`。
- 必须放行：同一回合先 Write `docs/report.md`，再 Write `<session scratch>/notes.md`。
- 必须仍拒绝：同一回合第 2 次 Write/Edit 项目源码；不得为 `docs/dev/qa-report-*.json` 等会被 gate 读取的产物开例外。
- 重叠：同 L01。

### G2 子代理写入

**OB-L05 子代理有一个可以命名的、按派发隔离的 scratch（W2，依赖 P14-6）**
- 覆盖：F01、M-SCR、search-07、F02 中 `$VAR` 的部分。
- 文件：
  - `hooks/pretool-tool-policy.py`：scratch actor-exactness（`:398-433`），以及前缀层对 `$` 词的展开。
  - `policies/tool-policy.v1.json`：dev 的 temp 行。
  - `hooks/subagentstart-record.py`：下发每次派发的 TMPDIR 或 scratch 路径。
  - `agents/dev.md:91`。
  - `hooks/lib/harness_temp_state.py`，来自 `origin/claude/ob-shared-state`，只读复用。
- 必须放行：
  - TMPDIR 为本次派发 scratch 时，dev 执行 `python3 -m pytest -q > "$TMPDIR/out.txt" 2>&1`。
  - qa 执行 `> $TMPDIR/qa/out.txt`。
  - dev 执行 `f=$(mktemp) && ... > "$f"`。
  - dev 执行 `> .claude/scratch/out.txt`（平铺文件，不属于任何其他派发）。
- 必须仍拒绝：
  - dev 执行 `> /tmp/hits.txt`（公共名字，并行 lane 会撞）。
  - 写入 `.claude/scratch/<sid>/qa/<另一 agent_id>/x`。
  - 写入 `<state>/claude-do-task-x.json` 或 `<state>/agentic-commit/...`。
  - 受限角色写 `$UNRESOLVED/x`。
- 重叠：
  - P14-6 拥有 `pretool-tool-policy.py`，本 lane 在它之后进行。
  - `ob-shared-state` 提供状态判定，不要再造一份名单。

**OB-L06 验证类角色的运行日志位置（W1）**
- 覆盖：F02 中 reports 的部分。
- 文件：`policies/tool-policy.v1.json`（qa 和 test-executor 从 `/tests/` 拒绝中切出 `*/tests/reports/`）。
- 必须放行：qa 执行 `python3 -m pytest -q > tests/reports/run.txt 2>&1`。
- 必须仍拒绝：
  - qa Write `tests/test_x.py`。
  - qa 执行 `> src/app.py`。
  - test-writer Write `tests/test_new_feature.py`（在 `tests/generated/` 之外，违反 D8）。
  - qa Write 一个未声明的 `docs/new-report.md`。
- 重叠：与 L22、L23 改同一个 JSON 文件，需串行。

### G3 权限 allow 缺口

**OB-L07 只读和测试命令的 allow 条目（W1）**
- 覆盖：perm-allow-gap-runners、perm-allow-gap-git-C、perm-allow-gap-misc-reads。
- 文件：settings.json 的 permissions.allow。
- 必须放行（默认模式下不弹提示）：
  - `pytest -q`、`make test`、`make -n`、`ruff check .`、`mypy src`。
  - `gh pr view 12`、`gh run view 1`、`git fetch origin`。
  - `tar -tzf release.tar.gz`、`unzip -l release.zip`、`systemctl status nginx`、`kubectl logs web-1`。
  - `git -C src log --oneline -3`、`git -C src status`、`rg --files`。
- 必须仍拒绝或提示：
  - `git -C x push --force`、`git -C x reset --hard`：拒绝。
  - `gh api -X POST repos/o/r/pulls`、`psql -c 'drop table t'`、`rg --pre sh x`、`sqlite3 app.db`：提示。
- 注意：
  - npm/pnpm 的测试在完整管线里先被 protected-runtime-guard 拒绝，而且只在 `~/.config/claude/protected-runtime.json` 缺失时才发生。所以只加 allow 条目解不开它们。
  - `./scripts/*.sh` 的风险与 `Bash(bash:*)` 相同，可以加。

**OB-L08 项目内写入的 allow [owner]（W1）**
- 覆盖：perm-allow-gap-project-writes。
- 文件：settings.json（`Edit(./**)` 或 defaultMode acceptEdits）。
- 必须放行：Write `src/newmodule.py`、`echo hi > notes.md`、写到项目根的 heredoc。
- 必须仍拒绝：
  - `echo '{}' > .claude/settings.json`：deny。
  - Write `.claude/settings.local.json`：上线前要先实测 harness-switch guard 是否覆盖 Write 工具。
  - `echo x > .claude/hooks/x.sh`：claude-config-guard。
  - Write `.env`。

**OB-L09 `Read(/tmp/**)` 改为精确的 scratch 目录（W1）**
- 覆盖：perm-tmp-outside-workdir。
- 文件：settings.json `:62-65`、`:113-115`、`:167`。
- 必须放行：`cat <session scratch>/notes.md`、`echo done > <session scratch>/report.md`、`ls <session scratch>`。
- 必须仍提示或拒绝：
  - `echo true > /tmp/claude-orchestrator-consent-abc.flag`。
  - `echo '{}' > /tmp/claude-tool-streak-abc.json`。
  - 不得加入 additionalDirectories ["/tmp"]。
- 另记：`python3 -c open(<consent flag>,'w')` 今天就能通过，交给 hook 方面处理（§5）。

**OB-L10 不用 cd 的搜索惯例（W1，只改散文）**
- 覆盖：perm-read-deny-arms-cd-guard。
- 文件：CLAUDE.md 的 Working Practice、`agents/*.md`、`commands/*.md` 的散文。Read() 条目不动。
- 必须放行：agent 写出的是 `grep -rn TODO src`、`rg -n TODO src`；`git -C src log` 依赖 L07。
- 必须仍拒绝：`cd config && cat .env`（守卫仍然生效）、`cat .env`（deny）。
- 重叠：P14-8 和其他在途分支也改 CLAUDE.md，需 rebase。

### G4 bash-safety（全部为 W2：P14-5 合并后改 `hooks/lib/bash_safety_rules.py`；P14-5 之前对应的是 `hooks/pretool-bash-safety.sh`）

**OB-L11 服务、进程、磁盘、docker、workflow 规则锚定到命令位置**
- 覆盖：BS-12..BS-19、bs/MB-2、search-14、search-M2、search-M3。
- 文件：`bash_safety_rules.py` 的 `service_rules`，读取 `shell_parse.walk`。
- 必须放行：
  - `kill -0 12345 && echo alive`、`kill -l`、`grep -rn kill -i src/`。
  - `fdisk -l`、`dd if=/dev/zero of=/tmp/blob.bin bs=1k count=4`。
  - `grep -rn "docker compose down" docs/`。
  - `sed -n 1,20p /etc/docker/daemon.json`、`grep tcp /etc/docker/daemon.json`。
  - `rg -n "systemctl restart nginx" docs`。
  - `jq .platform .claude/workflow-abc.json`、`grep -rn killall ~/.claude/hooks/`。
- 必须仍拒绝：
  - `pgrep -f vite | xargs kill -9`、`sudo kill -9 4242`、`timeout 5 kill -TERM 4242`、`kill -09 4242`。
  - `eval "systemctl restart docker"`、`eval "docker compose down"`、`python3 -c 'import os; os.system("docker system prune -a -f")'`。
  - `dd if=/dev/zero of=/dev/sda`、`dd if=/dev/zero of=$TARGET bs=1M count=1`。
  - `cp a /etc/docker/daemon.json`、`sed -i s/a/b/ /etc/docker/daemon.json`。
  - `T=~/.claude/todos/; rm -rf "$T"`、`pkill -f claude`。
- 重叠：
  - P14-5 拥有此文件，且它的 bar 1 禁止在 P14-5 中改变这些判定。
  - P14-5 会删除 `bash_context_strip.py`，所以 eval 和解释器 payload 的检查要改由 shell_parse 提供。
  - removal lane 只涉及 rm 的去除规则，与 workflow 路径无冲突。

**OB-L12 git 工作树规则改用调用视图**
- 覆盖：BS-21..BS-24、BS-27、search-10。
- 文件：`bash_safety_rules.py` 的 `worktree_git_rules` 和 git clean 规则。
- 必须放行：
  - `grep -rn "git stash push" docs/`。
  - heredoc 写文档，正文中有 `run git stash`。
  - `git restore --staged src/app.py && git show -s --format=%H HEAD && git diff -- docs/`。
  - `git restore --staged --source=HEAD -- src/`。
  - `echo Tip: git clean -n previews what would be removed`。
- 必须仍拒绝：
  - `git stash`、`git stash push -u`、`git -C x stash push`、`bash -c "git stash push"`。
  - `eval "git stash push"`、`python3 -c 'import os; os.system("git stash push -u")'`。
  - `git checkout HEAD -- .`、`git restore --source=HEAD --worktree -- src/`、`git clean -fd`。
  - 把今天能通过的这些也补上拒绝：`eval "git clean -fdx"`，以及 `python3 -c`/`node -e` 形式的 git clean。
- 重叠：P14-5 拥有此文件；P14-2 拥有分类器（eval 和解释器字符串的暴露）。

**OB-L13 哨兵和工件命名空间规则绑定到同一个简单命令**
- 覆盖：BS-05、BS-06、BS-07、search-13。
- 文件：`bash_safety_rules.py` 的 `writes_namespace` 和 `bulk_sentinel_decision`。
- 必须放行：
  - `python3 -m json.tool <state>/claude-commit-dispatch-a.json`（只有一个位置参数）。
  - `touch /tmp/marker && cat <state>/claude-commit-grant-a-n1.json`。
  - `rg -n write-bulk-commit-sentinel.py`、`grep -rn write-bulk-commit-sentinel.py commands/ | head -20`。
  - `git diff -- scripts/write-bulk-commit-sentinel.py | head -40`。
  - `grep -n argv scripts/write-bulk-commit-sentinel.py # don't edit`。
  - `ls <state>/claude-bulk-commit-sentinel-* 2>/dev/null`。
- 必须仍拒绝：
  - `python3 -m json.tool a.json <ns>`（两个位置参数，第二个是输出文件）、`echo {} > <ns>`。
  - `python3 scripts/write-bulk-commit-sentinel.py`。
  - 今天能通过、必须补上的：`git -c alias.x='!python3 scripts/write-bulk-commit-sentinel.py' x`、`sed -n '1w <state>/claude-bulk-commit-sentinel-x.json' /tmp/forged.json`。
  - `rg --pre ./x <sentinel>`、`echo <ns> | xargs cp src`。
- 重叠：P14-5 的 Q6 先重写 BS-17，本 lane 在其之上进行。

**OB-L14 敏感文件名：bash 层改用精确名单**
- 覆盖：BS-10、BS-11。search-09 及引号、heredoc 的部分已由 P14-5 的 O6 修好，需 pin。
- 文件：`bash_safety_rules.py` 的 `SENSITIVE_NAME`。
- 必须放行：
  - `cat > tests/test_password_reset.py <<'EOF' ... EOF`。
  - `ls -la src/ > /tmp/secret-scan-report.txt`。
  - `python3 -m pytest tests/test_auth_password.py > /tmp/pytest.log 2>&1`。
  - `curl -s https://example.com/docs/password-policy > /tmp/policy.html`。
  - `cat > src/config.ts <<'EOF'`，正文含 `=> process.env.PORT`。
- 必须仍拒绝：
  - `cat > .env <<'EOF'`、`echo x > .env.local`、`cat .env > x`、`cat ~/.aws/credentials > x`。
  - `> .git-credentials`、`> secrets.yaml`、`> id_rsa`、`> db_password`、`> passwords.csv`。
  - 无法解析的 heredoc 回退为拒绝。
- 重叠：P14-5 的 bar 5 禁止在 P14 中改名单，所以本 lane 放在 P14-5 之后。名单与 L19 共用同一份定义。

**OB-L15 HTTP /stop 和 npm -g 并入 runtime_guard 后复核存活规则**
- 覆盖：BS-02、search-15、BS-20。
- 文件：`hooks/lib/runtime_guard/*`（P14-3 拥有）。先复测；只在存活规则仍然误拒时才改。
- 必须放行：
  - `curl -s http://localhost:8000/stops/42`、`curl -s http://127.0.0.1:5000/stopwords?lang=en`。
  - `grep -n 'localhost:8080/stop' tests/test_requests_client.py`。
  - `npm install --save-dev eslint-config-google`、`npm i node-gyp`、`pnpm i -D vite-plugin-gzip`。
- 必须仍拒绝：
  - `curl -X POST http://localhost:8080/stop`、`python3 -c 'import requests; requests.post("http://localhost:8080/stop")'`、`http POST localhost:8080/stop`。
  - `npm i -g foo`、`npm install --global foo`、`npm i --location=global foo`、`bash -c "npm i -g foo"`。
- 重叠：P14-3 与 P14-5。P14-5 最新提交 `8a932eb0` 已经把 BS-34 并入 guard。

**OB-L16 session_dirs.txt 的「提及」 [owner]**
- 覆盖：BS-08、search-12、perm-session-dirs-mention。
- 文件：settings.json:188，必要时再加一个解析型 hook。
- 必须放行：`grep -rn session_dirs.txt docs/`、`git log --oneline -S session_dirs.txt`、`rg -n 'session_dirs.txt' hooks/`。
- 必须仍拒绝：
  - `cat session_dirs.txt`、`grep -f session_dirs.txt x`。
  - `python3 -c "open('session_dirs.txt','w')"`、`bash -c 'cat session_dirs.txt'`。
  - `find / -name session_dirs.txt -exec cat {} \;`、`cat $(echo session_dirs.txt)`、`cat session_dirs.tx?`。
- 注意：规则原文写的是「never reference」，属于有意设计。P14-5 合并后只剩 settings.json:188 一层，而发现者提出的修法会打开解释器和嵌套 shell 的路径。

**OB-L17 硬禁脚本：`bash -n` 视为不执行**
- 覆盖：BS-09 在 P14-5 O1 之后剩下的部分。
- 文件：`bash_safety_rules.py` 的 `hard_ban_rule`。
- 必须放行：`bash -n scripts/session-recovery.sh`、`[[ ! -f scripts/restart-all-sessions.sh ]] && echo missing`。
- 必须仍拒绝：`bash scripts/session-recovery.sh`、`! ./scripts/session-recovery.sh`、`bash --norc scripts/session-recovery.sh`（`--norc` 不是 noexec）。

**OB-L18 /do 的 pre-clean 守卫改用 stdin 传递**
- 覆盖：MB-1c。MB-1a/1b 已由 P14-5 修好，需 pin。
- 文件：`hooks/pretool-bash-safety.sh` 的 `_preclean_snapshot_guard`（P14-5 head 仍在 `:43` 用 `CMD_INPUT=`）、`hooks/lib/git_clean_guard.py`。
- 必须放行：/do 下一个 138 KB、不含 git clean 的 heredoc fixture 写入。
- 必须仍拒绝：/do 下的 `git -C /x clean -fd`；快照失败的已授权 clean；rc 126/127 时给出独立的部署错误文案并拒绝。
- 重叠：
  - P14-5 拥有前者，P14-2 拥有 `git_clean_guard.py`。
  - removal-policy 的 `CMD_INPUT` 环境变量传递（P14-5 `bash_safety_rules.py:962`）有同样的 E2BIG 问题，交给 removal lane。

### G5 权限 deny 过宽

**OB-L19 秘密文件 glob 改为枚举（W1）**
- 覆盖：perm-password、perm-secret、perm-env、perm-credentials、perm-shadow。
- 文件：settings.json `:220-248`。
- 必须放行：
  - Read `src/auth/ForgotPassword.tsx`、`src/secret_scanner.py`、`docs/secrets-management.md`、`.env.example`。
  - Read `src/components/Shadow/index.tsx`、`src/auth/CredentialsProvider.ts`。
  - `grep -n TODO src/auth/password_reset.py`。
- 必须仍拒绝：
  - Read `.env`、`.env.local`、`.env.staging`、`.env.development`、`.env.test`、`.env.production`。
  - Read `config/secrets.yaml`、`secrets.toml`、`credentials.json`、项目内的 `.aws/credentials`、`config2/credentials`。
  - Read `password.txt`、`db_password`、`passwords.csv`、`rootfs/etc/shadow`。
  - `cat .env.staging`。
- 重叠：与 L14 共用名单；settings.json 也被其他分支改动。

**OB-L20 Skill deny 改为精确拼写（W1）**
- 覆盖：perm-skill-prefix。
- 文件：settings.json `:249-270`、`hooks/tests/test_skill_deny_coverage.py:48,63,68`、`hooks/tests/test_codex_skill_not_denied.py:93,95`。
- 必须放行：Skill `docs`、`devops`、`commit-message`、`domain-model`、`testing`。
- 必须仍拒绝：Skill `do`、带参数 `fix the bug` 的 Skill `do`、Skill `dev`、`push`、`commit`、`code-review`。

**OB-L21 整动词 deny 改为 ask [owner]（W1）**
- 覆盖：perm-dry-run-whole-verb。
- 文件：settings.json `:192`、`:197`、`:198`、`:201`。
- 必须放行：`kubectl apply --dry-run=client -f k8s/deploy.yaml`、`kubectl create deployment web --image=nginx --dry-run=client -o yaml`（改为提示，而不是 deny）。
- 必须仍拒绝或提示：`kubectl apply -f k8s/deploy.yaml`、`kubectl apply --dry-run=none -f x`、`npm publish --dry-run=false`，都不能自动放行。
- 注意：`yarn publish --dry-run` 不能当作无害示例，因为 yarn classic 没有这个 flag。

### G7 角色工具表

**OB-L22 只读和簿记工具开放给所有角色（W1）**
- 覆盖：search-05、F13 中 Grep/Glob/TodoWrite 的部分、M26。
- 文件：`policies/tool-policy.v1.json`。
- 必须放行：
  - graphify 使用 Grep、Glob。
  - dev、qa 使用 TodoWrite。
  - dev 对自己的后台作业使用 TaskOutput、BashOutput、TaskStop、KillShell。
- 必须仍拒绝：graphify 使用 Edit；qa Edit `src/app.py`；user 角色读取 denied_path_prefixes 下的路径。

**OB-L23 Context7 开放给生成代码的角色（W1）**
- 覆盖：search-M1、F13 中 Context7 的部分。
- 文件：`policies/tool-policy.v1.json`。
- 必须放行：dev 调用 `mcp__context7__resolve-library-id react` 和 `query-docs`/`get-library-docs`；ba、qa、architect 调用 Context7。
- 必须仍拒绝：dev 使用 WebFetch、WebSearch（等 owner 决定）；dev 调用 `mcp__github__create_pull_request`。

### G8 git 守卫（W2）

**OB-L24 分类器：文本型所有者和管道消费者**
- 覆盖：GIT-1。也覆盖 BS-25/26/28/29a、search-11、search-M4 在 GP 中的存活规则，以及 P14-2 之后 GIT-2、GIT-M1 剩下的部分。
- 文件：`hooks/lib/git_command_classifier.py`（P14-2 合并后）。
- 必须放行：
  - `rg -n 'git reset --hard|git push --force' .`、`grep -rn 'git push origin\|git merge origin' . | head -5`。
  - 子代理执行 `rg -n "git rebase -i" docs`、`grep -rn 'git revert HEAD~1' docs/`。
  - `cat > /tmp/notes.md <<'EOF'`，正文中有一行 `git push origin master`。
  - `git log --oneline -3  # newest first; git push is not needed`。
- 必须仍拒绝：
  - `bash -c "x; git push"`、`echo "git push" | sh`。
  - `bash <<'EOF'`，正文为 `git push origin master`。
  - `cat <<'EOF' | bash`、`ssh host <<'EOF'`、`python3 - <<'EOF'`。
  - `ag --pager 'true; git push origin master' foo`、`rg --pre 'git push' x`。
- 重叠：P14-2 拥有此文件。P14-2 的「text-only 谓词」是保留下来的判定，本 lane 修改它。

**OB-L25 动态命令字：只有目录部分是展开时不再拦截**
- 覆盖：GIT-3。
- 文件：`hooks/lib/git_command_classifier.py:1665-1671`。
- 必须放行（只看 git 守卫）：`"$VIRTUAL_ENV/bin/pip" show pytest`、`"$CLAUDE_HOME/scripts/session-index.py" init`、`"$HOME/bin/helm" status myrelease`。
- 必须仍拒绝：`$GIT push`、`${G}it commit`、`G=git; ${G:-kubectl} push origin master`、`"$X/bin/$Y" push`。
- 重叠：
  - 这些输入同时被 removal-policy 的 dynamic_command_head 拒绝（removal lane）；两边都修好之后命令才真正放行。
  - P14-2。

**OB-L26 git 命令字和子命令先去引号再判定**
- 覆盖：GIT-5，并顺带修复一处欠防御。
- 文件：`hooks/lib/git_command_classifier.py`。
- 必须放行：`\git status`。
- 必须仍拒绝：`\git push origin master`、`\git 'push'`；今天能通过、需要补上的：`git 'push' --force origin master`、`git p\ush origin master`、`git "pu"sh origin master`、`git 'reset' --hard HEAD~1`。
- 重叠：P14-2。与 L24、L25 改同一个文件，需串行。

**OB-L27 只读形式：help、dry-run、show-current-patch**
- 覆盖：GIT-6。
- 文件：`hooks/pretool-git-privilege-guard.py`（P14-4 合并后）。
- 必须放行：`git push --help`、`git merge --help`、`git push --dry-run origin HEAD`、`git push -n origin HEAD`、`git commit --dry-run`、`git rebase --show-current-patch`、`git am --show-current-patch`。
- 必须仍拒绝：
  - `git commit -n -m x`（`-n` 是 `--no-verify`）。
  - `git push --help; git push origin master`（豁免按调用逐个判断）。
  - `git -c browser.x.cmd=sh push --help`。

**OB-L28 unresolved_shell_string 的拒绝提示改为可执行的出路（只改文案）**
- 覆盖：GIT-4。
- 文件：`hooks/pretool-git-privilege-guard.py:2041-2083`。
- 必须放行：不涉及判定变化；提示里应写出 `bash -c 'cd "$1" && git status' _ "$d"`，或不套 bash -c 的写法。
- 必须仍拒绝：`for d in */; do bash -c "cd $d && git status"; done`，判定保持不变，因为目录名可以携带 `;git push`。

**OB-L29 gitignore 预检按被派代理的写能力限定（W1）**
- 覆盖：GIT-10。
- 文件：`hooks/pretool-gitignore-preflight.py`。
- 必须放行：Agent Explore（没有 Write/Edit）被要求读取并总结一份已引用的 dev 报告，而该报告的 files_created 含 `.pytest_cache/...`。
- 必须仍拒绝：该 cycle 的 dev/qa 派发；引用同一报告的 general-purpose 派发（它有 Write）。

**OB-L30 git_clean_guard 把 grep 模式和 heredoc 文本当成 clean**
- 覆盖：BS-29。
- 文件：`hooks/lib/git_clean_guard.py`（P14-2 合并后先复测，P14-2 已把 `_lex` 换成解析器）。
- 必须放行（/do 下）：`grep -rn "git clean -fd" docs/`、`echo "git clean -fd"`、`rg -n 'git clean' docs/`、heredoc 中的 `CI runs git clean -fdX`。
- 必须仍拒绝（/do 下，快照失败时）：`g''it clean -fd`、`git cl\ean -fd`、`eval "git clean -fdx"`；`git -C /x clean -fd`。
- 注意：不能在检测器前加分类器前置过滤（`:678-685` 有意不设前置过滤）。

### G9 配置、开关和包装器（W2）

**OB-L31 claude-config-guard 按真实写目标判定**
- 覆盖：F07、ON-GLOBAL-REGEX 中 hooks/commands 的部分。
- 文件：`hooks/pretool-claude-config-guard.py`（不属于任何 P14 lane）。
- 必须放行：
  - `cp ~/.claude/hooks/pretool-launch.py /tmp/launch-copy.py`、`cp -r ~/.claude/commands/ /tmp/commands-snapshot`。
  - `grep -rn 'mv ' ~/.claude/hooks/ | head -20`、`rg -n 'tee ' ~/.claude/hooks/`。
  - `cp README.md docs/README-copy.md && ls ~/.claude/hooks/`、`cp .claude/commands/hello.md docs/hello-command.md`。
- 必须仍拒绝：
  - `cp x ~/.claude/hooks/y.py`、`cp -t .claude/hooks/ x`、`cp --target-directory=.claude/commands x`。
  - `echo x > .claude/hooks/a.sh`、`tee .claude/commands/x.md`、`sed -i s/a/b/ .claude/hooks/x.py`。
  - `mv .claude/hooks/a /tmp/`、`rm .claude/commands/x.md`、`cd .claude/hooks && cat > x.py <<'EOF'`。
- 重叠：P14-11 删除 OG-01/02 时，以本 hook 作为存活者并写测试证明「存活者拒绝每一个用例」。本 lane 须保持那组用例全部拒绝，并在 P14-11 合并后进行。

**OB-L32 开关守卫的 `_read_only` 正确跳过 git 全局选项**
- 覆盖：HS-GIT-C。
- 文件：`hooks/pretool-harness-switch-guard.py` 的 `_read_only`。
- 必须放行：`git -C ~/.claude diff --stat -- ~/.claude/settings.json`、`git -C ~/.claude log --oneline -3 -- scripts/harness-switch`、`git -C <project> log --oneline -- .claude/settings.json`。
- 必须仍拒绝：
  - `git -C ~/.claude checkout -- settings.json`。
  - `git -C ~/.claude -c alias.x='!sh' x`。
  - 任何设置 alias.*、core.hooksPath、core.fsmonitor、core.sshCommand 或以 `!` 开头值的 `-c`。
- 重叠：P14-12、settings-switch PR、Train C。L32–L36 改同一个文件，需串行。

**OB-L33 开关守卫：只有被写的词才算写**
- 覆盖：F09、F10、F11 中状态的部分、HS-HOME-SETTINGS、HS-PROJECT-SETTINGS-READERS、HS-STATE-DIR、HS-DAH-READ。
- 文件：`hooks/pretool-harness-switch-guard.py`（written-word 模型，按 cd 目标解析）。
- 必须放行：
  - `sed -n '1,40p' ~/.claude/settings.json`、`cp ~/.claude/settings.json /tmp/settings-backup.json`。
  - `grep -n '"hooks"' ~/.claude/settings.json > /tmp/hook-lines.txt`。
  - `awk 'NR<=20' .claude/settings.json`、`nl .claude/settings.json`。
  - `wc -c ~/.claude/.harness-switch/* > /tmp/count.txt`。
  - `python3 -c "import json; print(json.load(open('.claude/settings.json')).get('disableAllHooks'))"`。
- 必须仍拒绝：
  - `sed -i x ~/.claude/settings.json`、`cp /tmp/evil.json ~/.claude/settings.json`。
  - 今天能通过、需要补上的：`cd ~/.claude && sed -i 's/block/off/' settings.json`。
  - `uniq /tmp/evil.json .claude/settings.json`、`awk '{print > ".claude/settings.json"}' /tmp/x`。
  - `python3 -m json.tool --indent 1 F F`（F 为 home settings）。
  - `touch ~/.claude/.harness-switch/off`、`cd ~/.claude && touch .harness-switch/off`、`echo x>settings.json`（P14-12 的 pin）。
- 注意：harness home 的文件保持「非读者程序的每个词都算被写」这一模型，只放宽明确列名的读者。

**OB-L34 开关程序和嵌套 claude 只在命令字位置判定**
- 覆盖：F11 中运行的部分、HS-SWITCH-PROGRAM、HS-TYPED-NESTED、writes-M6。
- 文件：同上。
- 必须放行：
  - `sed -n '1,60p' ~/.claude/scripts/harness-switch`、`shellcheck ~/.claude/scripts/harness-switch`、`bash -n ~/.claude/hooks/userprompt-harness-switch.sh`。
  - `grep -n '/harness' ~/.claude/commands/harness.md; claude --version`、`rg -n '/harness off' ~/.claude/commands; which claude`。
- 必须仍拒绝：
  - `~/.claude/scripts/harness-switch hook <<< '{...}'`、`env harness-switch off`。
  - 今天能通过、需要补上的：`python3 <(cat ~/.claude/scripts/harness-switch) hook <<< ...`。
  - `p='/harness off'; setsid claude -p "$p"`、`printf '/harness off' > /tmp/p; setsid claude -p < /tmp/p`。
- 注意：对 claude 只豁免非会话形式（`--version`、`--help`、doctor、mcp、config）；读者要按白名单列出，不能用排除法推定。

**OB-L35 开关守卫的 Write 内容规则看文件种类和取值**
- 覆盖：F12、HS-NAMES-STATE、HS-DISABLEALLHOOKS-ANYNAME。
- 文件：同上，`:482`、`:492`。
- 必须放行：
  - Write `/tmp/audit-notes.md` 或 `docs/notes.md`，内容只是提到 `~/.claude/.harness-switch/`。
  - Write `tests/fixtures/settings.example.json`，内容为 `{"disableAllHooks": false}`。
- 必须仍拒绝：
  - Write `scripts/x.sh`，内容含 `touch ~/.claude/.harness-switch/off`。
  - Write `notes.md`，内容含 `rm -rf ~/.claude/.harness-switch`（名字附近有写操作的写法）。
  - Write 任何 `.json`/yaml/toml 且提到状态目录的文件（只豁免 .md/.txt/.rst）。
  - Write `.claude/settings.json`，内容为 `{"disableAllHooks": true}` 或 `"true"`/`1`。
- 注意：HS-NESTED-FIXTURE 不在本 lane 内，见 owner 决定。

**OB-L36 定时 prompt 规则改用开关自身的 parse_prompt**
- 覆盖：HS-PROMPT-MENTION。
- 文件：同上，`:505-510`；直接调用 `scripts/harness-switch` 的 `parse_prompt`。
- 必须放行：CronCreate 的 prompt 为 "Summarize last night's CI failures; leave /harness alone."。
- 必须仍拒绝：CronCreate、ScheduleWakeup 或 SendMessage 的 prompt 为 `/harness off`、`  /harness on`，或 command-name 标签形式。

**OB-L37 views 和 cp-state 守卫锚定到真实的 spec 根目录**
- 覆盖：F14、F15。
- 文件：`hooks/pretool-bash-views-guard.py`、`hooks/pretool-cp-state-write-guard.py`。
- 必须放行：`npm ls --all --json > /tmp/deps.lock.json`、`cat README.md > build-info.lock.json`；dev Write `tests/fixtures/specs/demo/cp-state-dev.json`。
- 必须仍拒绝：
  - `echo x > docs/dev/specs/s1/views/manifest.json.lock`、`> .claude/specs/s1/cp-state-qa.json`。
  - dev Write `.claude/specs/x/cp-state-qa.json`、`docs/dev/specs/x/cp-state-qa.json`，以及它们的 dot-claude 镜像和符号链接形式。
- 重叠：P14-10 删除了 cp-state 守卫中没用的 import，本 lane 在它之后进行。

**OB-L38 /stop 包装器守卫：按执行解析、按路径匹配、只在执行时消耗哨兵**
- 覆盖：CD-11、caps/MB-1、WU-ANY-STOP-SH。
- 文件：`hooks/pretool-wrapper-userintent.py`。
- 必须放行：
  - `grep -rn "bash hooks/stop.sh" docs/`、`rg -n "start.sh|stop.sh" scripts/`。
  - `bash -n hooks/stop.sh`、`command -v stop.sh`。
  - `./scripts/stop.sh`（项目自己的）。
  - 输入 /stop 后先执行一次 grep 提及，再执行 `bash "$HOME/.claude/hooks/stop.sh"`，后者仍然放行。
- 必须仍拒绝（无 /stop 哨兵时）：
  - `bash ~/.claude/hooks/stop.sh`、`python3 ~/.claude/scripts/break-overnight-lock.py`。
  - `cd ~/.claude/hooks && ./stop.sh`、`ln -s ~/.claude/hooks/stop.sh /tmp/s && /tmp/s`、`bash -c 'bash ~/.claude/hooks/stop.sh'`。
- 重叠：P14-10 改过此文件的 heredoc 读取；`scripts/break-overnight-lock.py:84-110` 的 token 校验必须保留。

### G10 工作流、义务和汇总（W1）

**OB-L39 checklist 未开始的锁放行 Read、Grep、Glob**
- 覆盖：search-04、WF-ABANDONED-SPAN。
- 文件：`hooks/pretool-workflow-gate.py`。
- 必须放行：`/dev` 后、TodoWrite 前的 Grep、Glob、Read；`/test` 被放弃后的 `Read toy/__init__.py`。
- 必须仍拒绝：TodoWrite 之前的 Write、Edit、Agent、Bash；Stop gate 仍然要求 checklist。
- 重叠：`claude/readme-reconstruction-p12-r4r7ip` 这个旧分支（2026-11-10）改过此文件。

**OB-L40 checklist 全部完成后接受外来的 TodoWrite**
- 覆盖：TV-AFTER-COMPLETION。
- 文件：`hooks/pretool-todo-validate.py`，以及所有 span 读者：`pretool-workflow-gate.py`、Gate 4、`stop-command-gate.py`。
- 必须放行：`/spec` 8 步全部完成后，一个不相关的 2 项 TodoWrite。
- 必须仍拒绝：
  - `/dev` 进行中的自定义列表。
  - 完成后复用 canonical 步骤文本的列表。
  - gated 命令的 Stop gate 读到外来列表而不是 canonical。
- 重叠：`stop-command-gate.py` 也被 P14-10、P14-11、P14-12 和 Train C 带入的提交改动。

**OB-L41 只是提到义务标签不算义务块**
- 覆盖：OB-TOKEN-MENTION。
- 文件：`hooks/pretool-obligation-gate.py`；另需核对 SubagentStop 的 producer gate 对 Rejection 的处理。
- 必须放行：在不要求义务块的 span 外，Agent Explore 的 prompt 在散文中提到 `<obligation v="1">` 或 `<obligation> blocks`。
- 必须仍拒绝：
  - span 内已声明的角色没有带块。
  - 要求块时块格式错误。
  - 能解析出合法块、但角色不符或时钟失效。

**OB-L42 QA 汇总检查在无义务且无 span 时不做全局扫描拦截**
- 覆盖：AG-GLOBAL-SCAN。
- 文件：`hooks/pretool-aggregate-check.py`。
- 必须放行：docs/dev 中存在被遗弃的 fan-out 时，一个无义务、无 span 的 qa 派发。
- 必须仍拒绝：带义务、且其 cycle 缺 canonical 的 qa 派发；/dev span 内的 qa 派发（G1 本就要求义务）。

### G11 杂项

**OB-L43 Read 尺寸守卫按实际返回行数判断（W1）**
- 覆盖：search-03。
- 文件：`hooks/pretool-read-size-guard.py` 的 `is_bounded_chunk`。
- 必须放行：Read `big.md`（650 行），offset:600、不带 limit。
- 必须仍拒绝：Read `big.md` 不带 limit；limit:2000；offset:10 不带 limit（返回 641 行）。

**OB-L44 grep 探针区分「从未启动」和「启动后爆炸」（W2，依赖 P14-7/P14-5）**
- 覆盖：search-08。
- 文件：`hooks/pretool-grep-backtrack-guard.py`。
- 必须放行：systemd-run 启动被延迟 11 秒时的 `grep -rnE 'def .*\(.*\):' src`。
- 必须仍拒绝：灾难型模式的探针已启动并以 rc 124/137 结束；或在 scope 内写下启动标记后卡住（例如被 MemoryHigh 限流）。

**OB-L45 用户自己开启 plan 模式时允许 ExitPlanMode [owner]（W1）**
- 覆盖：CD-7。
- 文件：`hooks/pretool-orchestrator-gate.py` 的 PERMANENTLY_BLOCKED、CLAUDE.md:50。
- 必须放行：payload 的 `permission_mode` 为 `'plan'` 时的 ExitPlanMode。
- 必须仍拒绝：EnterPlanMode；`permission_mode` 不是 plan 时的 ExitPlanMode；只在 tool_input 里自称 plan 的调用。
- 重叠：同 L01（同一文件）。

**OB-L46 Write 覆盖守卫豁免 scratch、temp 和未跟踪的生成输出 [owner]（W1）**
- 覆盖：F05。
- 文件：`hooks/lib/write_gate/overwrite.py`。
- 必须放行：Write 覆盖已有的 `<session scratch>/report.md`。
- 必须仍拒绝：Write 覆盖已跟踪的 `src/app.py`、`.claude/settings.json`、已跟踪的配置文件（即使长度相同）。
- 注意：Edit 这条路径始终存在，所以优先级低。

## 3. 已被 P14 或在途分支覆盖的发现（不另开 lane，只在相应 lane 中 pin）

| 发现 | 覆盖方 | 状态与要求 |
|---|---|---|
| BS-01 | P14-5：把 P14 的 BS-11 判为 DEAD 并删除（O6） | 删除即修复；pin `bash /tmp/repro_parse.sh` 放行 |
| BS-03 | P14-5：P14 的 BS-13 随 BS-09 一起删除（O6 中的 `cat <flag> \| cat`） | pin 两个示例 |
| BS-04 | P14-5 O6（P14 的 BS-14） | pin `ls <ns> 2>/dev/null`、`cat <ns>` 放行，`echo x > <ns>` 拒绝 |
| search-09，以及 BS-10 中引号和 heredoc 的部分 | P14-5 O6（`sensitive_redirect` 改走解析器） | pin；名字子串部分转 L14 |
| BS-09 中 `[[ ]]` 的部分 | P14-5 O1 | pin；`bash -n` 转 L17 |
| MB-1a、MB-1b | P14-5（payload 走 stdin，剥离器在进程内） | pin 一个 138 KB 的 heredoc；MB-1c 转 L18 |
| BS-25/26/28/29a、search-11、search-M4 | P14-5 删除 P14 的 BS-41/42/44/45，并入 GP-08/06/04 | 误报转移到 GP，由 L24 处理 |
| BS-08、search-12 | P14-5 把 P14 的 BS-18 并入 settings.json:188 | 转 L16（owner） |
| BS-02、BS-20、search-15 | P14-5 并入 runtime_guard（P14-3） | 转 L15 复核 |
| F03、F04、writes-M2、M14 | P14-6/P14-10 改用 `shell_parse.write_targets` | pin 示例与必须仍识别为写的形式（见 G6） |
| F06 | P14-6 删除 TP-13/TP-14（Q5 (a)） | P14-6 head 上已经没有 `_INFLIGHT_MSG_NAME` |
| ON-GLOBAL-REGEX | P14-11：O7 修 OG-03；OG-01/02 删除并入 claude-config-guard | OG-03 部分在 P14-11 中 pin；hooks/commands 部分转 L31 |
| GIT-2、GIT-M1 | P14-2：解析视图带 heredoc 和注释意识 | pin；剩余部分转 L24 |
| GIT-7、GIT-9、GIT-M2、GIT-M3 | P14-8 删除 BB-02..08（owner 2026-11-16 决定允许分支和 PR） | 随删除消失；注意 §5 中 refs/checkpoints 的欠防御 |
| CD-8 | `claude/harness-newer-tools-design-a` T2 和 Train A 的 `lib/send_policy.py` | 复核者建议把放宽限于只读代理类型，或在 Stop 前要求回复 |
| CD-10 | 同一分支的 T5：`/allow Workflow` 授权可以通过 no-background hook | 在途 |
| caps/MB-2 中 TaskStop 的部分 | 同一分支的 T4 把 TaskStop 加入白名单 | LSP、TaskOutput、BashOutput、ReadMcpResourceTool 仍转 L01 |

## 4. 需要 owner 决定的事项

- **L03：**只读 Bash 是否不计入 5 次上限。CLAUDE.md:48 明确写了这个上限，`commands/dev.md:41` 按它安排了步骤预算。
- **L04 和 L46：**编排者写 scratch 是否不计次；Write 覆盖守卫是否放开 scratch。
- **L08：**是否用 `Edit(./**)` 或 acceptEdits 放开项目内写入。
- **L16：**session_dirs.txt 的「never reference」是否放宽为「只允许作为 grep/rg/git grep 的模式，或出现在 commit 消息里」。
- **L21：**kubectl apply/create、npm publish 是否从 deny 改为 ask。
- **L23 的延伸：**dev/qa 是否可以使用 WebFetch、WebSearch。
- **L45：**plan 模式下是否允许 ExitPlanMode；CLAUDE.md:50 写的是 always refused。
- **暂不修、建议保持现状的：**
  - BS-30：GP 另行拒绝所有 agent commit。
  - BS-31：词法解析加 `git init` 会被符号链接绕过（`ln -s ~/.claude /tmp/fx9`）。
  - GIT-8：scratch 仓库里的 commit/merge。路径在 hook 运行时尚不存在，无法解析，还有符号链接竞态；可靠的修法反而让发现者给的例子仍被拒绝。
  - HS-NESTED-FIXTURE：任何子目录都可能在那里启动 claude 会话。
  - CD-9：后台 Bash 会活过 gate。
  - perm-pem：名字区分不了公钥证书和私钥。

## 5. 审计中暴露的欠防御（不属于本报告的 lane，建议另开）

- `git -c alias.x='!python3 scripts/write-bulk-commit-sentinel.py' x` 和 `sed -n '1w <state>/claude-bulk-commit-sentinel-x.json' /tmp/forged.json` 都能通过 bash-safety（BS-07 复核）。L13 会一并修。
- `eval "git clean -fdx"`、`python3 -c 'import os; os.system("git clean -fdx")'`、`node -e '...execSync("git clean -fdx")'` 能通过整条管线（BS-27 复核）。L12 会一并修。
- `git 'push' --force origin master`、`git p\ush ...`、`git 'reset' --hard`、`git 'branch' -D master`、`git 'commit' -am x`、`git 'merge' feature` 能通过所有 PreToolUse hook（GIT-5 复核）。L26 会一并修。
- `cd ~/.claude && sed -i 's/block/off/' settings.json`、`cd ~/.claude && cp /tmp/evil.json settings.json` 能通过整条管线（HS-HOME-SETTINGS 复核）。L33 会一并修。
- `python3 <(cat ~/.claude/scripts/harness-switch) hook <<< '{"prompt": "/harness off"}'` 能通过（HS-SWITCH-PROGRAM 复核）。L34 会一并修。
- `python3 -c open(...)` 可以写入 /do consent flag（state 根默认在 /tmp）。这已经超出 permission 层的范围，需要一条 hook lane（perm-tmp 复核）。
- `**/` 形式的 Read/Edit deny 管不到 cwd 以外的文件，例如 `~/.aws/credentials`、`~/.env`（permissions 单元）。
- settings.json `:189` `Bash(curl:* | sh:*)` 和 `:218` `Bash(wget:* | sh:*)` 是死规则，永远匹配不到。
- P14-8 删除 BB-05 之后，`git fetch origin refs/checkpoints/master:refs/checkpoints/master` 会覆盖本地自动提交的 checkpoint ref，而 GP 不管 fetch 的目的地（GIT-M3 复核）。
- F01 中：scratch 规则跳过含 `$` 的词，所以写 `$TMPDIR/…` 就能绕过 /tmp 限制。
- CD-6 中：编排者可以用 Bash heredoc 写 gate 会读取的 QA 报告（`e2e_enforcement.status`）。
- BS-20 中：`NPM_CONFIG_GLOBAL=true npm install left-pad` 能通过。
- BS-26 中：`eval "git branch -D old"` 能通过 bash-safety。
- GIT-2 中：`bash push.sh`、`python3 -c 'subprocess.run(["git","push"])'` 能通过（git 守卫是词法级的）。
- GIT-7 中：`echo main:newbranch | git fetch --stdin origin`、`git -c remote.origin.fetch=+refs/heads/*:refs/heads/* fetch origin` 能通过。P14-8 删除 BB-05 之后，这一项已经不算问题。

## 6. 存活发现全表

列说明：
- 单元：bs=bash-safety，se=search，cd=caps-dispatch，wr=writes，gi=git，sg=state-gates，pm=permissions。
- 主/子：主=主代理，子=子代理。
- 复核：确=确认，部=部分，补=复核者补充。
- 严重度：日=日常，偶=偶发，罕=罕见。

| # | 单元 | id | 工具 | 主/子 | 判定代码 | 规则 | 严重度 | 复核 | 组 | 去向 |
|---|---|---|---|---|---|---|---|---|---|---|
| 1 | bs | BS-01 | Bash | 主子 | pretool-bash-safety.sh:874 | daemon-restart-wrapper 1.C | 偶 | 确 | G4 | P14-5 删除 |
| 2 | bs | BS-02 | Bash | 主子 | :887-888 | daemon-restart-http-stop 1.D | 罕 | 确 | G4 | L15 |
| 3 | bs | BS-03 | Bash | 主子 | :900-901 | daemon-restart-sentinel-write 1.E | 罕 | 确 | G4 | P14-5 删除 |
| 4 | bs | BS-04 | Bash | 主子 | :922-923 | commit-userintent-sentinel-write 1.E2 | 罕 | 确 | G4 | P14-5 O6 |
| 5 | bs | BS-05 | Bash | 主子 | :1036 | commit-dispatch-attestation-write 1.E3 | 罕 | 确（已记录的残差） | G4 | L13 |
| 6 | bs | BS-06 | Bash | 主子 | :1118 | commit-grant-raw-write 1.E4 | 罕 | 确 | G4 | L13 |
| 7 | bs | BS-07 | Bash | 主子 | :1258, :1424-1594, :1613 | bulk-commit-sentinel-write 1.F | 偶（harness 仓） | 确 | G4 | L13 |
| 8 | bs | BS-08 | Bash | 主子 | :1637 | session_dirs.txt ban | 罕 | 确（按设计） | G4 | L16 owner |
| 9 | bs | BS-09 | Bash | 主子 | :1649, :1678 | hard-banned scripts | 罕 | 确 | G4 | P14-5 O1 + L17 |
| 10 | bs | BS-10 | Bash | 主子 | :1686 | sensitive file write | 偶 | 确 | G4 | P14-5 O6 + L14 |
| 11 | bs | BS-11 | Bash | 主子 | :1692 | sensitive redirect from/to | 偶 | 确 | G4 | L14 |
| 12 | bs | BS-12 | Bash | 主子 | :1704 | Docker daemon operations | 罕 | 确 | G4 | L11 |
| 13 | bs | BS-13 | Bash | 主子 | :1711 | Docker daemon config | 罕 | 确 | G4 | L11 |
| 14 | bs | BS-14 | Bash | 主子 | :1729 | docker compose down/stop/restart | 罕 | 确 | G4 | L11 |
| 15 | bs | BS-15 | Bash | 主子 | :1736 | docker system prune -a | 罕 | 确 | G4 | L11 |
| 16 | bs | BS-16 | Bash | 主子 | :1747 | dd/mkfs/fdisk/shred | 罕 | 确 | G4 | L11 |
| 17 | bs | BS-17 | Bash | 主子 | :1763 | kill with signals | 偶 | 确 | G4 | L11 |
| 18 | bs | BS-18 | Bash | 主子 | :1774 (:483) | systemctl non-dev units | 罕 | 确 | G4 | L11 |
| 19 | bs | BS-19 | Bash | 主子 | :1788 | workflow state rm/mv | 罕 | 确 | G4 | L11 |
| 20 | bs | BS-20 | Bash | 主子 | :1920 | npm install -g | 偶 | 确 | G4 | L15 |
| 21 | bs | BS-21 | Bash | 主子 | :1969 | git stash push | 罕 | 确 | G4 | L12 |
| 22 | bs | BS-22 | Bash | 主子 | :1993 | bare git stash | 罕 | 确 | G4 | L12 |
| 23 | bs | BS-23 | Bash | 主子 | :2023 | git checkout ref -- wide | 罕 | 确 | G4 | L12 |
| 24 | bs | BS-24 | Bash | 主子 | :2061-2063 | git restore --source wide | 罕 | 确 | G4 | L12 |
| 25 | bs | BS-25 | Bash | 主子 | :2139-2140 | force/delete push | 罕 | 确 | G8 | P14-5 删除 → L24 |
| 26 | bs | BS-26 | Bash | 主子 | :2176 | direct ref mutation | 罕 | 确 | G8 | P14-5 删除 → L24 |
| 27 | bs | BS-27 | Bash | 主子 | :2577-2581 | git clean fallback scan | 罕 | 确 | G4 | L12 |
| 28 | bs | BS-28 | Bash | 子 | :2640 | subagent history mutation | 偶 | 确 | G8 | P14-5 删除 → L24 |
| 29 | bs | BS-29a | Bash | 主 | :2680-2692 | git revert ref modifier | 罕 | 确 | G8 | P14-5 删除 → L24 |
| 30 | bs | BS-29 | Bash | 主（/do） | :705-717 (:789), lib/git_clean_guard.py | pre-clean snapshot guard | 罕 | 确 | G8 | L30 |
| 31 | bs | BS-30 | Bash | 主子 | :356, :394 | commit-hook-bypass | 罕 | 部 | — | 不修 |
| 32 | bs | BS-31 | Bash | 主子 | :393 | config-keystone-write | 罕 | 确 | — | 暂缓 |
| 33 | bs | MB-1a | Bash | 主子 | :324 → :410 | commit-guard FAIL-CLOSED (E2BIG) | 罕 | 补 | G4 | P14-5 pin |
| 34 | bs | MB-1b | Bash | 主子 | :1165-1177 | stripper E2BIG → raw view | 罕 | 补 | G4 | P14-5 pin |
| 35 | bs | MB-1c | Bash | 主（/do） | :702-717 (:789) | pre-clean guard E2BIG | 罕 | 补 | G4 | L18 |
| 36 | bs | MB-2 | Bash | 主子 | :1754 | killall/pkill claude/docker | 罕 | 补 | G4 | L11 |
| 37 | se | search-01 | Bash | 主 | pretool-orchestrator-gate.py:234 | Bash cap 5 | 日 | 确 | G1 | L03 owner |
| 38 | se | search-02 | WebSearch/WebFetch/MCP | 主 | :237 | non-whitelist 1/turn | 偶 | 确 | G1 | L01 |
| 39 | se | search-03 | Read | 主 | pretool-read-size-guard.py:84-90 | Read size >600 | 偶 | 部（只有 offset 情形） | G11 | L43 |
| 40 | se | search-04 | 除 TodoWrite 外全部 | 主（子） | pretool-workflow-gate.py:1230-1234 | CHECKLIST NOT STARTED | 偶 | 部 | G10 | L39 |
| 41 | se | search-05 | Grep/Glob | 子（graphify） | lib/policy_registry.py:263-264; tool-policy.v1.json:743 | allowed_tools | 罕 | 确 | G7 | L22 |
| 42 | se | search-07 | Bash | 子 | pretool-tool-policy.py:1355-1360 | scratch /tmp denial | 偶 | 部 | G2 | L05 |
| 43 | se | search-08 | Bash | 主子 | pretool-grep-backtrack-guard.py:1140-1143 | probe outer timeout | 罕 | 部 | G11 | L44 |
| 44 | se | search-09 | Bash | 主子 | pretool-bash-safety.sh:1686-1687, :1692-1693 | sensitive regex on raw text | 偶 | 确 | G4 | P14-5 O6 pin |
| 45 | se | search-10 | Bash | 主子 | :1969-1972, :1993-1994 | git stash raw text | 偶 | 确 | G4 | L12 |
| 46 | se | search-11 | Bash | 子 | :2640-2642 | subagent history raw text | 偶 | 确 | G8 | L24 |
| 47 | se | search-12 | Bash | 主子 | :1637-1638 | session_dirs.txt | 罕 | 确 | G4 | L16 owner |
| 48 | se | search-13 | Bash | 主子 | :1258-1260 (:1614) | bulk sentinel reference | 罕 | 确（范围更窄） | G4 | L13 |
| 49 | se | search-14 | Bash | 主子 | :1704-1705, :1711-1712, :1729-1730, :1736-1737 | docker raw text | 偶 | 确 | G4 | L11 |
| 50 | se | search-15 | Bash | 主子 | :887-889 | http-stop raw text | 罕 | 确 | G4 | L15 |
| 51 | se | search-M1 | WebSearch/WebFetch/context7 | 子 | lib/policy_registry.py:259-265; json :131, :93 | role allowed_tools | 偶 | 补 | G7 | L23 |
| 52 | se | search-M2 | Bash | 主子 | pretool-bash-safety.sh:1788-1789 | workflow (rm\|mv)\s in words | 罕 | 补 | G4 | L11 |
| 53 | se | search-M3 | Bash | 主子 | :1774-1779 (:483-507) | systemctl raw text | 罕 | 补 | G4 | L11 |
| 54 | se | search-M4 | Bash | 主 | :2680-2693 | git revert raw text | 罕 | 补 | G8 | L24 |
| 55 | cd | CD-1 | WebSearch | 主 | pretool-orchestrator-gate.py:237 | non-whitelist 1/turn | 日 | 确 | G1 | L01 |
| 56 | cd | CD-2 | WebFetch | 主 | :237 | non-whitelist 1/turn | 日 | 确 | G1 | L01 |
| 57 | cd | CD-3 | Bash | 主 | :234 | Bash cap 5 | 日 | 确（有文档的策略） | G1 | L03 owner |
| 58 | cd | CD-4 | 所有受上限约束的工具 | 主 | :341 | count before verdict | 偶 | 确（有意设计） | G1 | L02 |
| 59 | cd | CD-5 | mcp context7/github | 主 | :237 | non-whitelist 1/turn | 偶 | 确 | G1 | L01 |
| 60 | cd | CD-6 | Write/Edit | 主 | :237 | non-whitelist 1/turn | 偶 | 部 | G1 | L04 owner |
| 61 | cd | CD-7 | ExitPlanMode | 主 | :313 | PERMANENTLY_BLOCKED | 偶 | 确 | G11 | L45 owner |
| 62 | cd | CD-8 | SendMessage | 主 | pretool-block-background-tasks.py:152 | SendMessage refused | 偶 | 确 | G11 | 在途（T2/Train A） |
| 63 | cd | CD-9 | Bash（后台） | 主 | :191 | run_in_background refused | 罕 | 部 | — | 保留 |
| 64 | cd | CD-10 | Workflow | 主 | :152 | Workflow refused | 罕 | 部 | G11 | 在途（T5） |
| 65 | cd | CD-11 | Bash | 主子 | pretool-wrapper-userintent.py:186 (:69-80) | /stop wrapper guard | 偶 | 确 | G9 | L38 |
| 66 | cd | MB-1 | Bash | 主 | :191 (:149) | sentinel spent by mention | 罕 | 补 | G9 | L38 |
| 67 | cd | MB-2 | LSP/TaskOutput/BashOutput/ReadMcpResourceTool | 主 | pretool-orchestrator-gate.py:237 (:66-79) | non-whitelist 1/turn | 偶 | 补 | G1 | L01（TaskStop 由 T4 处理） |
| 68 | wr | F01 | Bash/Write/Edit | 子 | pretool-tool-policy.py:425-433, :1355-1360 | raw /tmp denied every role | 日 | 确 | G2 | L05 |
| 69 | wr | F02 | Bash/Write | 子（非 dev） | lib/policy_registry.py:268-275 via :1346-1353 | role write prefixes | 日 | 部 | G2 | L05（$VAR）+ L06 |
| 70 | wr | F03 | Bash | 子（非 dev） | lib/bash_write_targets.py:259-260, :759-767 | sed -i phantom | 偶 | 确 | G6 | P14-6/10 pin |
| 71 | wr | F04 | Bash | 子（非 dev） | :262-263, :790-806 | install phantom | 偶 | 确 | G6 | P14-6/10 pin |
| 72 | wr | F05 | Write | 主子 | lib/write_gate/overwrite.py:135-144 | overwrite refused | 偶（复核下调） | 部 | G11 | L46 owner |
| 73 | wr | F06 | Write/Bash | 主子 | pretool-tool-policy.py:776-777, :803-815 | in-flight commit-msg | 偶 | 确 | — | P14-6 删除 TP-13 |
| 74 | wr | F07 | Bash | 主子 | pretool-claude-config-guard.py:54-71, :160-169, :309-314 | config guard regex | 偶 | 确 | G9 | L31 |
| 75 | wr | F09 | Bash | 主子 | pretool-harness-switch-guard.py:444-454 | home settings write | 偶 | 确 | G9 | L33 |
| 76 | wr | F10 | Bash | 主子 | :312-333, :455-459 | CLI settings write | 偶 | 确 | G9 | L33 |
| 77 | wr | F11 | Bash | 主子 | :446-451 | runs switch / changes state | 罕 | 确 | G9 | L34 + L33 |
| 78 | wr | F12 | Write/Edit | 主子 | :492-493 | names switch state | 罕 | 确 | G9 | L35 |
| 79 | wr | F13 | WebFetch/WebSearch/context7/TodoWrite/Grep/Glob | 子 | lib/policy_registry.py `_check_tool_lists` via :1346-1353 | role allowed_tools | 偶 | 部 | G7 | L22 + L23 |
| 80 | wr | F14 | Write/Edit | 子 | pretool-cp-state-write-guard.py:61-70, :113-117 | cp-state any */specs/* | 罕 | 确 | G9 | L37 |
| 81 | wr | F15 | Bash | 主子 | pretool-bash-views-guard.py:30, :93-96 | *.lock.json redirect | 罕 | 确 | G9 | L37 |
| 82 | wr | M-SCR | Bash/Write/Edit | 子 | pretool-tool-policy.py:398-400, :422-423 | sibling scratch | 偶 | 补 | G2 | L05 |
| 83 | wr | M2 | Bash | 子（非 dev） | lib/bash_write_targets.py:256, :717-746, :317, :337-345, :817, :865-872 | cp/mv/tee/chmod in arg position | 偶 | 补 | G6 | P14-6/10 pin |
| 84 | wr | M14 | Bash | 主子 | lib/bash_write_targets.py:1324, :1329; pretool-tool-policy.py:1486, :1424, :1430 | rm/mv word = delete protected | 罕 | 补 | G6 | P14-6/10 pin |
| 85 | wr | M6 | Bash | 主子 | pretool-harness-switch-guard.py:73-74, :440-442 | typed /harness nested claude | 罕 | 补 | G9 | L34 |
| 86 | wr | M26 | TaskOutput/BashOutput/TaskStop/KillShell | 子 | lib/policy_registry.py:259 | role allowed_tools | 偶 | 补 | G7 | L22 |
| 87 | gi | GIT-1 | Bash | 主子 | lib/git_command_classifier.py:1781-1783, :1792, :1816-1832; guard :2017 | quote-blind invocation scan | 偶 | 确 | G8 | L24 |
| 88 | gi | GIT-2 | Bash | 主子 | classifier :1754-1769, :138; guard :2017, :2094-2105 | heredoc body lines | 偶 | 确 | G8 | P14-2 pin → L24 |
| 89 | gi | GIT-3 | Bash | 主子 | classifier :1665-1671; guard :2059 | dynamic_git_token | 偶 | 部 | G8 | L25 |
| 90 | gi | GIT-4 | Bash | 主子 | classifier :1593-1595; guard :2059 | unresolved_shell_string | 偶 | 部（保留拒绝） | G8 | L28（文案） |
| 91 | gi | GIT-5 | Bash | 主子 | classifier :1663-1664; guard :2059 | obfuscated_git_token | 罕 | 确 | G8 | L26 |
| 92 | gi | GIT-6 | Bash | 主子 | pretool-git-privilege-guard.py:1807-1817, :913-924 | subcommand name only | 罕 | 确 | G8 | L27 |
| 93 | gi | GIT-7 | Bash | 主子 | pretool-block-branch-pr-worktree.py:504, :534-550 | fetch refspec branch | 罕 | 确 | — | P14-8 删除 BB-05 |
| 94 | gi | GIT-8 | Bash | 主子 | pretool-git-privilege-guard.py:1475, :2102-2103 | commit/merge default deny | 罕 | 部 | — | 暂缓（owner） |
| 95 | gi | GIT-9 | Bash | 主子 | pretool-block-branch-pr-worktree.py:804-805, :865 | checkout -b branch creation | 罕 | 部 | — | P14-8 删除 BB-02 |
| 96 | gi | GIT-10 | Agent | 主 | pretool-gitignore-preflight.py:726-833, :845 | gitignored deliverables | 罕 | 确 | G8 | L29 |
| 97 | gi | GIT-M1 | Bash | 主子 | classifier :1754-1769 (:138) | comment text | 罕 | 补 | G8 | P14-2 pin → L24 |
| 98 | gi | GIT-M2 | Bash | 主子 | pretool-block-branch-pr-worktree.py:605-611 | gh pr create --help | 罕 | 补 | — | P14-8 删除 BB-07 |
| 99 | gi | GIT-M3 | Bash | 主子 | :540-550 | refs/pull destination | 罕 | 补 | — | P14-8 删除 BB-05（见 §5） |
| 100 | sg | HS-HOME-SETTINGS | Bash | 主子 | pretool-harness-switch-guard.py:452 (:445) | home settings write | 偶 | 确 | G9 | L33 |
| 101 | sg | HS-SWITCH-PROGRAM | Bash | 主子 | :448 | runs the switch | 罕 | 确 | G9 | L34 |
| 102 | sg | HS-STATE-DIR | Bash | 主子 | :450 (:445) | changes switch state | 罕 | 确 | G9 | L33 |
| 103 | sg | HS-PROJECT-SETTINGS-READERS | Bash | 主子 | :455-459 (:279, :196, :69) | CLI settings write | 罕 | 确 | G9 | L33 |
| 104 | sg | HS-NAMES-STATE | Write/Edit | 主子 | :492 | names switch state | 罕 | 确 | G9 | L35 |
| 105 | sg | HS-DISABLEALLHOOKS-ANYNAME | Write/Edit | 主子 | :482 | disableAllHooks any settings*.json | 罕 | 确 | G9 | L35 |
| 106 | sg | HS-NESTED-FIXTURE | Write/Edit | 主子 | :486-491 (:84) | nested .claude/settings.json | 罕 | 确 | — | 暂缓（owner） |
| 107 | sg | HS-TYPED-NESTED | Bash | 主子 | :440 (:74, :75) | typed /harness nested | 罕 | 确 | G9 | L34 |
| 108 | sg | HS-PROMPT-MENTION | CronCreate/ScheduleWakeup/SendMessage | 主 | :508 (:75) | scheduled prompt /harness | 罕 | 确 | G9 | L36 |
| 109 | sg | OB-TOKEN-MENTION | Agent | 主 | pretool-obligation-gate.py:238, :269-271 | G1 obligation parse | 偶 | 确 | G10 | L41 |
| 110 | sg | AG-GLOBAL-SCAN | Agent | 主 | pretool-aggregate-check.py:639, :250, :646 | QA collection global scan | 罕 | 确 | G10 | L42 |
| 111 | sg | WF-ABANDONED-SPAN | 除 TodoWrite 外全部 | 主 | pretool-workflow-gate.py:1198-1199, :1230; lib/command_span.py:5 | checklist lock after abandon | 偶 | 确 | G10 | L39 |
| 112 | sg | TV-AFTER-COMPLETION | TodoWrite | 主 | pretool-todo-validate.py:461-462, :225 | canonical validation | 偶 | 确 | G10 | L40 |
| 113 | sg | ON-GLOBAL-REGEX | Bash | 主子 | pretool-overnight-hook-guard.py:647, :644 via :2461→:739→:728 | overnight global regex | 罕 | 确 | G9 | P14-11 O7 + L31 |
| 114 | sg | WU-ANY-STOP-SH | Bash | 主子 | pretool-wrapper-userintent.py:78, :176 | any stop.sh | 罕 | 确 | G9 | L38 |
| 115 | sg | HS-DAH-READ | Bash | 主子 | pretool-harness-switch-guard.py:437 (:221, :196) | disableAllHooks write | 罕 | 补 | G9 | L33 |
| 116 | sg | HS-GIT-C | Bash | 主子 | :171-173 | `_read_only` git -C | 偶 | 补 | G9 | L32 |
| 117 | pm | perm-read-deny-arms-cd-guard | Bash | 主子 | settings.json:236-248 | Read() arms cd guard | 日（默认模式） | 确 | G3 | L10 |
| 118 | pm | perm-password-substring | Read/Edit/Bash | 主子 | :238, :220 | `**/*password*` | 日（认证仓） | 确 | G5 | L19 |
| 119 | pm | perm-secret-substring | Read/Edit/Bash | 主子 | :239, :221 | `**/*secret*` | 偶 | 确 | G5 | L19（bash 写入部分 → L14） |
| 120 | pm | perm-env-dot-star | Read/Edit/Bash | 主子 | :241, :223 | `**/.env.*` | 偶 | 确 | G5 | L19 |
| 121 | pm | perm-skill-prefix | Skill | 主子 | :249-270 | `Skill(<stem>:*)` prefix | 偶 | 确 | G5 | L20 |
| 122 | pm | perm-session-dirs-mention | Bash | 主子 | :188 | `Bash(*session_dirs.txt*)` | 偶 | 部 | G4 | L16 owner |
| 123 | pm | perm-credentials-prefix | Read/Edit | 主子 | :242, :225 | `**/credentials*` | 偶 | 确 | G5 | L19 |
| 124 | pm | perm-allow-gap-runners | Bash/WebFetch | 主子 | :38-186 | allow gap | 日（默认模式） | 确 | G3 | L07 |
| 125 | pm | perm-tmp-outside-workdir | Bash/Write | 主子 | :62-65, :113-115, :167 | /tmp outside workdir | 偶 | 部 | G3 | L09 |
| 126 | pm | perm-dry-run-whole-verb | Bash | 主子 | :192, :197, :198, :201, :219 | whole-verb deny | 罕 | 部 | G5 | L21 owner |
| 127 | pm | perm-shadow-dir | Read/Edit/Bash | 主子 | :245, :228 | `**/shadow` | 罕 | 确 | G5 | L19 |
| 128 | pm | perm-pem | Read/Bash | 主子 | :237 | `**/*.pem` | 罕 | 确 | — | 接受现状 |
| 129 | pm | perm-allow-gap-project-writes | Write/Bash | 主子 | :153-163 | Edit allow gap | 日（默认模式） | 补 | G3 | L08 owner |
| 130 | pm | perm-allow-gap-git-C | Bash | 主子 | :84-88 | git -C allow gap | 偶 | 补 | G3 | L07 |
| 131 | pm | perm-allow-gap-misc-reads | Bash | 主子 | :38-186 | rg --files / make -n / ./scripts | 罕 | 补 | G3 | L07 |

重复与同源（修一处，这几条一起解决）：
- search-09 与 BS-10/11 同源。
- search-10 与 BS-21/22 同源。
- search-11 与 BS-28 同源。
- search-12、BS-08、perm-session-dirs 同源。
- search-13 与 BS-07 同源。
- search-14 与 BS-12..15 同源。
- search-15 与 BS-02 同源。
- search-M2 与 BS-19 同源。
- search-M3 与 BS-18 同源。
- search-M4 与 BS-29a 同源。
- search-01 与 CD-3 同源。
- search-02 与 CD-1/2/5 同源。
- search-05、search-M1 都包含在 F13 中。
- search-07 与 F01/F02 同源。
- F09 与 HS-HOME-SETTINGS 同源。
- F10 与 HS-PROJECT-SETTINGS-READERS 同源。
- F11 与 HS-SWITCH-PROGRAM + HS-STATE-DIR 同源。
- F12 与 HS-NAMES-STATE 同源。
- M6 与 HS-TYPED-NESTED 同源。
- caps/MB-1、CD-11、WU-ANY-STOP-SH 同源。

## 7. 复核过、没有发现误报的规则（每个单元一行）

- **bash-safety：**
  - `:158`：解释器 fail-closed，正常时不可达。
  - `:291`：protected-runtime-guard。在 bootstrap 生成的空表配置下，131 条无害命令加 6000 条 fuzz 输入，0 次拦截。但配置文件缺失时，STEP1 会拒绝 `npm test`、`node --version`、`kill -0`。
  - `:297-304`：fallback，未触达。
  - `:408`：unregistered-settings-filter，只针对 commit。
  - `:410`：commit-guard fail-closed，例外是 MB-1a 的大小问题。
  - `:688`、`:722`、`:741`：pre-clean 的失败路径。
  - `:786`（/do）和 `:815-833`（/allow）：放行路径。
  - `:839`、`:860`：Layer 1.A/1.B，在未设置 CLAUDE_PROTECTED_DAEMON_PREFIX 时不生效。
  - `:1718`：docker family，在未设置 CLAUDE_PROTECTED_PROCESS_FAMILY 时不生效。
  - `:1933`：kill PID，只命中真正的 kill。
  - `:2116`：reset --hard，grep 和 heredoc 都放行。
  - 未执行：`:522-653` daemon grant 的消耗路径。
- **search：**
  - `pretool-grep-backtrack-guard.py:1181-1205`：正常延迟下 38 种形态都放行。
  - read-size-guard：除 offset 以外的部分。
  - orchestrator 的 `:313`：搜索不会触达。
  - workflow-gate 的 Codex 路径 `:1166-1169`、`:913-932`。
  - tool-policy bootstrap 的 `:149-167`，以及 write-gate 20 秒预算的 fail-closed（均未触发）。
  - tool-policy 的 protected、declared、grant、clean 检查：只看写目标，不涉及 Read、Grep、Glob。
  - block-background-tasks、do-block-subagents、cp-checkin（无拒绝路径）、worktree-guard（只提示）、harness_switch 的 exit_if_off。
  - 本单元约 160 条搜索载荷没有触发：wrapper-userintent、attribution-pre、block-branch-pr-worktree、bulk-commit-detector、git-privilege-guard、bash-views、claude-config、harness-switch、overnight-boundary。其他单元对这些规则另有发现。
- **caps-dispatch：**
  - `pretool-orchestrator-gate.py:328`：写已有文件不计数的豁免。
  - `:290`：Agent 派发重置计数。
  - `pretool-block-background-tasks.py:181`：Agent 未带 `run_in_background:false`。CLI 默认是否后台无法核实，代价是一次重试。
  - `pretool-subagent-enforce.py:271`：只在 overnight 下生效。
  - `pretool-capability-gate.py:136/:113/:151`：未在 settings.json 注册。若 core profile 注册它，会拒绝除 codex 以外的所有 Skill。
  - `pretool-orchestrator-prompt-purity.py:254`：只发警告。
  - 工具名为 Task 时每回合第 2 次被拒：只有 CLI 发送 Task 而非 Agent 时才会出现。
  - ToolSearch：已由 `ENABLE_TOOL_SEARCH=false` 关闭。
- **writes：**
  - `pretool-write-gate.py:93-122` 与 `lib/write_gate/__init__.py:142-149`：组合逻辑与 fail-closed。
  - `pretool-tool-policy.py:143-167`、`:928-937`：import 失败时 fail-closed。
  - `:1403-1504`：受保护路径，按设计；也拒绝 harness /dev cycle 改 `scripts/check-public-core.sh` 等文件（P5 R2）。
  - `:1540-1558`：ScheduleWakeup。
  - `:918-1057`：declared writes，没有已启动的派发时未触达。
  - `:1266-1297`：/clean。
  - `:733-754`：grant 目录。
  - `:845-915`：test-writer 的 in-flight 条目。
  - `policy_registry.py:278-282`：只针对 user 角色，按设计。
  - `bash_write_targets.py` 的普通重定向、tee、cp、mv（`2>/dev/null`、`2>&1`、引号、heredoc 正文都处理正确）。
  - `overwrite.py:100-108`（bulk 哨兵）、`:119-133`（grant 不匹配）。
  - `pretool-cp-checkin.py:258-271`：无拒绝路径。
  - `pretool-overnight-hook-guard.py:2452-2474`：overnight 之外不生效。
  - `harness-switch-guard.py:478-479`、`:484-485`、`:486-491`（按设计）、`:496-502`。
  - F08（claude-config 的 Write/Edit 路径）未通过复核。
- **git：**
  - `pretool-git-privilege-guard.py:241`：内部错误 fail-closed。
  - `:1638-1649`：/do 的受保护移动。
  - `:1652-1662`：内联 env，P14 判为 DEAD。
  - `:1749-1755`：force push 本身没有误报，误报来自 GIT-1/2 的词法问题。
  - `:1680-1729`、`:1279-1386`、`:1120-1141`、`:620-866`：grant 和 provenance 路径。
  - `:1397-1411`：auto-bulk。
  - `pretool-block-branch-pr-worktree.py:213-243`（内部错误）、`:799-803`（worktree add）、`:693-709`（gh pr checkout）、`:719-770`（gh api POST）。
  - bulk-commit-detector、worktree-guard：只提示。
  - block-enterworktree：按设计。
  - 普通 git 读命令（status、log、diff、show、blame、branch -a、fetch、remote -v、stash list、`gh pr view` 等）都放行。
- **state-gates：**
  - `harness-switch-guard.py:437`：理论上会被提到 disableAllHooks 的 commit 消息命中，见 HS-DAH-READ；`:478`、`:484`、`:500`。
  - `pretool-overnight-hook-guard.py:2457`：AskUserQuestion；`:690`、`:696`、`:704`：配置路径；`:2480-2530`：只针对 overnight actor。
  - `pretool-workflow-gate.py:1167`、`:932`：Codex 路径。
  - `pretool-todo-validate.py:189-203`（步骤顺序，契约）、`:401-420`（Gate 4）、`:423-433`（wake）。
  - `pretool-quality-gate.py:349`：只发警告。
  - `pretool-obligation-gate.py:256`（R17）、`:262`（R5），只在块合法时生效。
  - `pretool-aggregate-check.py:653`（有作用域的检查）、`:605`（G3 屏障）。
  - `pretool-grep-backtrack-guard.py:1205`：沙箱里没有引擎，fail-open。
  - `pretool-do-block-subagents.py:117`：只在 /do 下。
  - `pretool-read-size-guard.py:90`：有文档的上限。
  - attribution-pre、cp-checkin、runcode-watchdog：没有拒绝路径。
- **permissions：**
  - Bash deny：
    - `:190` dd（会写）、`:191` docker rm（词边界正确）。
    - `:193-195` git push --force/-f、reset --hard。
    - `:196`、`:202`、`:203`、`:207` halt/poweroff/reboot/shutdown。
    - `:199` kubectl delete（未测 dry-run）、`:200` mkfs。
    - `:204-206` rm -rf（会删除）。
    - `:208` su（`sum` 不受影响）、`:209` sudo。
    - `:210-217` systemctl 的各个变更动词（status 是提示不是拒绝）。
  - Edit deny：`:222`、`:224`、`:226`、`:227`、`:229-235`。
  - Read deny：`:236`（`*.key`，只有 Keynote 文件会罕见误中）、`:240`、`:243`、`:244`、`:246-248`。这些条目都会连带打开 cd 守卫，见 perm-read-deny-arms-cd-guard。
  - `:189`、`:218` 是死规则（欠防御，不是误报）。
