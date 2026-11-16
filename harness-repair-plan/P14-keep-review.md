# P14 KEEP 规则复核表（111 条，请勾选要删的）

**结论（5 行）**
1. 111 条 KEEP 规则逐条对了 2,325 次真实回放里的 Bash 调用（97 次回放：70 次流水线回放 + 27 次回放，含 7 次故障回放）。
2. 真正拒绝过的只有 1 条：GP-30（`/clean` 的 cleaner 子代理无授权 `git commit`，2 次）。其余 110 条拒绝都是 0，其中 53 条连要看的命令都没出现过。
3. 建议删 6 条：TP-13、TP-14（Q5 已定）、BS-13（守的东西随 BS-09 一起没了）、BS-24（开关出厂关闭）、BS-27、BS-30（`settings.json` deny 已经拦同样的命令）。
4. 其余 105 条建议留。其中 67 条是安全底线：不留，代理就能推送、提交、改历史或删文件，或者解析一崩就放行这些操作。剩下的大多很便宜，放到共享解析器上只要几行。
5. 全部接受：少 6 条规则，今天的代码少约 249 行，共享解析器版本少写约 57 行。删 BS-27、BS-30 会改变 bash-safety 自己的判决（拒绝改由 `settings.json` deny 给出），要写进计划第 4 节的“允许的差异”。

**表头说明**：“触及”是指这条规则要看的那类命令出现了几次（比如所有 `git commit`）；“从未见到”是指拒绝和触及都是 0。行数格式是“现在行数 / 共享解析器上的估计行数”。

| 编号 | 拦什么 | 真实会话遇到几次 | 删了会怎样 | 现在行数 / 估计行数 | 建议 | 安全底线 |
|---|---|---|---|---|---|---|
| BS-13 | `touch $TMPDIR/claude-allow-daemon-restart-x.flag` | 从未见到 | 无实际影响：它守的 BS-09 授权旗标已随 BS-09 合并掉，仓库里也没有写旗标的程序。 | 11 / 5 | **删**：从未见到；守的东西随 BS-09 消失；还误拦 `cat 旗标 \| cat` |  |
| BS-24 | `docker restart demo-prod` | 从未见到 | 无变化：出厂 settings 不设 CLAUDE_PROTECTED_PROCESS_FAMILY，这条本来就不生效；`docker rm` 还在 settings.json deny 里。 | 10（+辅助函数 27） / 8 | **删**：从未见到；配置开关出厂关闭；要用时由 runtime_guard 的 protected_proc_idents 接手 |  |
| BS-27 | `dd if=/dev/zero of=/dev/sda` | 从未见到 | hook 不再拦，但 settings.json deny 里的 `Bash(dd:*)` `Bash(mkfs:*)` `Bash(fdisk:*)` 照样拦；shred 由 BS-32 拦。 | 8 / 4 | **删**：从未见到；重复（settings.json deny + BS-32）；它本身也只看第一行开头，不比 deny 宽 |  |
| BS-30 | `systemctl restart nginx` | 从未见到 | hook 不再拦，但 settings.json deny 有全部 8 个 systemctl 动词；`bash -c '…'` 包装形式只剩 BS-02 拦。 | 14（+辅助函数 25） / 10 | **删**：从未见到；重复（settings.json deny 的 8 个动词，且 deny 比它的白名单更严） |  |
| TP-13 | `echo x > /tmp/commit-msg-abc.txt` | 从未见到 | 无变化：只照顾 train 2 之前开始的会话，已不存在。 | 58（含注释 20） / 15 | **删**：Q5 已定；从未见到 |  |
| TP-14 | 写 `.claude/dev-registry/<id>/test-writer.json` | 从未见到 | 无变化：同 TP-13。 | 96（含注释 22） / 15 | **删**：Q5 已定；从未见到 |  |
| BB-01 | `git worktree add ../w` | 从未见到（worktree add 0 次；`git worktree list` 4 次） | 代理在 /dev-overnight 之外也能随手建 worktree。 | 约 5（共用框架另计） / 5 | **留**：主人只放开了分支和 PR，没放开 worktree |  |
| BS-01 | `CLAUDE_PYTHON_BIN=/bin/false` 时的任何命令 | 拒绝 0 / 触及 2325（每次调用都过） | Python 坏掉时整个 bash-safety 直接放行一切。 | 28 / 5 | **留**：解析器的兜底 | 安全底线 |
| BS-02 | `npm install -g foo` | 从未见到（kill/systemctl/npm/pip/docker 等词一次没出现；引擎每次都跑） | 代理能杀进程、重启服务、全局装包。 | 40（+runtime_guard 引擎） / 10 | **留**：本机服务和进程的唯一守卫 |  |
| BS-03 | 引擎崩溃时的 `kill 1` | 从未见到（后备从未触发） | BS-02 引擎一崩，杀进程/重启服务就放行。 | 95 / 5 | **留**：兜底；并入“解析失败即拒” | 安全底线 |
| BS-04 | `git commit --no-verify -m x` | 拒绝 0 / 触及 20（git commit 20 次） | 有授权的提交可以跳过 pre-commit 检查。 | 100（04/05/06 共用块） / 25 | **留**：提交检查的完整性，/do 也放不开 |  |
| BS-05 | `git config --global core.hooksPath /tmp/h` | 从未见到（git config 0 次） | 代理可改 hooksPath 或 alias，把 `git commit` 伪装成别的子命令绕过提交授权。 | （含在 BS-04 的 100 行） / 25 | **留**：否则提交授权可被绕开 | 安全底线 |
| BS-06 | `settings.json` 有改动且过滤器未注册时 `git commit -m x` | 拒绝 0 / 触及 20（git commit 20 次） | 本机 settings 覆盖层会被提交进仓库。 | （含在 BS-04 的 100 行） / 20 | **留**：防止本机配置泄进提交 |  |
| BS-07 | 提交检查 Python 超时后的 `git commit` | 拒绝 0 / 触及 68（进入预检 68 次：含 git 且含 commit/config；后备从未触发） | BS-04..06 一崩溃就放行 hooksPath/alias 改写。 | 1 / 3 | **留**：兜底 | 安全底线 |
| BS-08 | 有授权时 `git -C /x clean -fd` | 拒绝 0 / 触及 12（上限：/do 流水线里主代理的调用¹） | 已授权的 clean 打到别的目录，或不先做快照就删未跟踪文件。 | 107 / 15 | **留**：授权内的最后一道快照 |  |
| BS-14 | `echo x > <state>/claude-commit-userintent-a.flag` | 从未见到 | 代理可伪造“用户想提交”的旗标，进而自己铸提交授权。 | 20 / 5 | **留**：否则可无授权提交 | 安全底线 |
| BS-15 | `echo x > <state>/claude-commit-dispatch-a.json` | 从未见到 | 代理可伪造 changelog-analyst 的派发证明。 | 116 / 8 | **留**：否则可无授权提交 | 安全底线 |
| BS-16 | `echo {} > <state>/claude-commit-grant-x-y.json` | 从未见到 | 代理可手写提交授权。 | 82 / 5 | **留**：否则可无授权提交 | 安全底线 |
| BS-17 | `touch <state>/claude-bulk-commit-sentinel-x.json` | 从未见到 | 代理可手写批量提交哨兵，走 auto-bulk 通道提交。 | 502 / 20 | **留**：否则可无授权提交（Q6 还要收紧） | 安全底线 |
| BS-19 | `bash session-recovery.sh` | 从未见到 | 代理能跑主人禁掉的会话恢复脚本。 | 38 / 8 | **留**：默认开启；主人明确禁的脚本 |  |
| BS-20 | `echo hi > .env` | 从未见到 | 代理能覆盖 .env/凭据文件。 | 7 / 6 | **留**：与 BS-21 合成一条 |  |
| BS-21 | `cat .env > out.txt` | 从未见到 | 代理能把凭据文件内容倒到别处。 | 6 / 2 | **留**：与 BS-20 合并；修掉误拦 |  |
| BS-23 | `cp a /etc/docker/daemon.json` | 从未见到 | 代理能改 Docker 守护进程配置，影响所有容器。 | 6 / 3 | **留**：便宜，影响面大 |  |
| BS-25 | `docker compose down` | 从未见到 | 代理能停掉整套 compose 服务。 | 6 / 3 | **留**：便宜，停服代价大 |  |
| BS-26 | `docker system prune -a` | 从未见到 | 代理能清掉所有未用镜像。 | 6 / 3 | **留**：便宜 |  |
| BS-28 | `pkill -f claude` | 从未见到 | 代理能杀掉 claude/docker 进程（有 runtime 配置文件时 BS-02 不再兜）。 | 6 / 5 | **留**：杀会话代价大 |  |
| BS-29 | `kill -9 1234` | 从未见到 | 代理能带信号杀任意进程。 | 8 / 6 | **留**：与 BS-35 合成一条 |  |
| BS-31 | `mv workflow-x.json /tmp/` | 从未见到 | 代理能挪走工作流状态文件，让流程门禁读不到。 | 10 / 6 | **留**：mv 部分别处没有 |  |
| BS-32 | `rm -rf build` | 拒绝 0 / 触及 2（删除类 2 次，都是 `git rm -q`；分析器每次都跑） | 代理能 rm/unlink/shred 用户文件。 | 71（+分析器库） / 15 | **留**：删文件的主守卫 | 安全底线 |
| BS-33 | 分析器超时时的 `ls *.txt` | 从未见到（后备从未触发） | BS-32 分析器一失败，rm 就放行。 | 48 / 5 | **留**：兜底 | 安全底线 |
| BS-35 | `kill 1234` | 从未见到 | 代理能按 PID 杀进程。 | 11 / 2 | **留**：与 BS-29 合并 |  |
| BS-36 | `git stash push -u` | 从未见到 | 代理能把未提交改动和未跟踪文件收进 stash，再 `stash drop`（没人拦）就没了。 | 31 / 8 | **留**：与 BS-37 合并 | 安全底线 |
| BS-37 | `git stash` | 从未见到 | 同 BS-36。 | 19 / 2 | **留**：与 BS-36 合并 | 安全底线 |
| BS-38 | `git checkout HEAD -- .` | 从未见到 | 代理能用 HEAD 覆盖整个工作区，丢掉未提交改动。 | 32 / 10 | **留**：与 BS-39 合并 | 安全底线 |
| BS-39 | `git restore --source=HEAD -- .` | 拒绝 0 / 触及 18（git restore 18 次，都是 `--staged`，不在被拦形式内） | 同 BS-38。 | 40 / 3 | **留**：与 BS-38 合并 | 安全底线 |
| BS-43 | `git clean -fd` | 从未见到 | 代理能删掉所有未跟踪文件。 | 432 / 30 | **留**：删文件；git 守卫不管 clean | 安全底线 |
| GC-01 | `g\it push` | 拒绝 0 / 触及 958（可能跑 git 的调用 958 次） | 混淆写法的 git 不再被识别，推送/提交规则全部看不见它。 | 9 / 5 | **留**：推送/提交规则的输入 | 安全底线 |
| GC-02 | `$GIT push` | 拒绝 0 / 触及 958（同上） | 变量当命令名的 git 绕过所有 git 规则。 | 43 / 15 | **留**：同上 | 安全底线 |
| GC-03 | `$(which git) push` | 拒绝 0 / 触及 958（同上） | 命令替换当命令名的 git 绕过所有 git 规则。 | 2 / 3 | **留**：同上 | 安全底线 |
| GC-04 | `bash -c "git $SUB"` | 拒绝 0 / 触及 32（走进 -c/嵌套层 32 次） | 运行时才知道内容的 `bash -c` 串里的 git 放行。 | 26 / 10 | **留**：同上 | 安全底线 |
| GC-05 | `bash -c "echo $X \| sh"` | 拒绝 0 / 触及 32（同上） | 运行时代码可以执行任意 git。 | 455（含词表 154） / 60 | **留**：同上；词表并进解析器 | 安全底线 |
| GC-06 | 读不懂的 `sh -c` 串里像 git 的内容 | 拒绝 0 / 触及 32（同上） | 解析器读不懂的 -c 串直接放行。 | 17 / 5 | **留**：兜底 | 安全底线 |
| GC-07 | 嵌套超过 4 层的 `bash -c` | 拒绝 0 / 触及 32（同上） | 套 5 层就能藏 `git push --force`。 | 3 / 3 | **留**：兜底 | 安全底线 |
| GC-08 | 扫描抛异常的命令 | 拒绝 0 / 触及 958（同上） | 分类器一崩，git 规则就看不到命令。 | 4 / 3 | **留**：兜底 | 安全底线 |
| GC-09 | `python3 -c "x; git push origin"` | 拒绝 0 / 触及 149（引号里找到 git 调用 149 次） | 要么引号里的 git 全放行（`python3 -c` 推送），要么全误拦。 | 79 / 20 | **留**：推送/提交规则的输入 | 安全底线 |
| GC-10 | `bash -c "git push"` | 拒绝 0 / 触及 32（走进 -c 层 32 次） | `bash -c` 里的 git 不按原样判断。 | 86 / 10 | **留**：同上 | 安全底线 |
| GC-11 | `timeout 30 git push` | 拒绝 0 / 触及 4（命令词前有前缀的 git²） | `env`/`timeout`/`if` 后面的 git 不再被识别。 | 121 / 5 | **留**：同上；并进解析器的包装表 | 安全底线 |
| GCL-01 | 有授权时 `git -C /x clean -fd` | 拒绝 0 / 触及 12（上限¹） | 授权的 clean 可以打到另一个仓库。 | 62 / 10 | **留**：授权内的保护 |  |
| GCL-02 | 有授权时 `timeout 60 git clean -fd` | 拒绝 0 / 触及 12（上限¹） | 包装前缀让 clean 目标不明却放行。 | 28 / 8 | **留**：同上 |  |
| GCL-03 | 有授权时 `bash -c "git clean -fd"` | 拒绝 0 / 触及 12（上限¹） | 藏在参数或嵌套里的 clean 不先快照。 | 136 / 25 | **留**：同上 |  |
| GCL-04 | 有授权时 4 层 `bash -c` | 拒绝 0 / 触及 12（上限¹） | 深嵌套里的 clean 看不到。 | 10 / 3 | **留**：兜底 |  |
| GCL-05 | 有授权时 `export GIT_DIR=/x; git clean -fd` | 拒绝 0 / 触及 12（上限¹） | clean 被重定向到别的仓库。 | 15 / 5 | **留**：同上 |  |
| GCL-06 | 有授权时 `git clean -fd && cd /x` | 拒绝 0 / 触及 12（上限¹） | cd 之后 clean 的目录不明。 | 20 / 5 | **留**：同上 |  |
| GCL-07 | 有授权时 `git clean -n $(echo --no-dry-run)` | 拒绝 0 / 触及 12（上限¹） | 假装 dry-run 的真删除不先快照。 | 10 / 5 | **留**：同上 |  |
| GCL-08 | 判断时抛异常 | 拒绝 0 / 触及 12（上限¹） | 判断一崩，授权的 clean 不快照就删。 | 15 / 3 | **留**：兜底 |  |
| GP-01 | 分类器坏掉时的 `git push` | 拒绝 0 / 触及 958（可能跑 git 958 次） | privilege guard 一崩就放行推送和提交。 | 59 / 5 | **留**：兜底 | 安全底线 |
| GP-02 | `$GIT push` | 拒绝 0 / 触及 958（同上） | 读不懂的 git 写法放行推送和提交。 | 49（+覆盖通道 138） / 10 | **留**：兜底 | 安全底线 |
| GP-03 | /do 下 `git reset --hard HEAD~1`（在 master 上） | 从未见到 | /do 下代理能重置或删除默认分支。 | 124 / 40 | **留**：改历史 | 安全底线 |
| GP-08 | `git push --force origin x` | 从未见到（代理 git push 0 次） | 代理能强推、删远端分支和 tag，/do 和 /allow 都放不开它，删了就没有任何拦截。 | 16 / 15 | **留**：Q1：唯一的强推/删除拦截 | 安全底线 |
| GP-09 | `git push origin master` | 从未见到（代理 git push 0 次） | 代理不经 /push 授权就能推送。 | 16 / 10 | **留**：推送 | 安全底线 |
| GP-14 | `git merge foo` | 从未见到 | 代理能自己合并分支。 | 22 / 5 | **留**：改历史 | 安全底线 |
| GP-15 | 没有哨兵时提交 `auto-bulk: end-of-cycle commit for x` | 从未见到（auto-bulk 提交 0 次） | 代理写上 auto-bulk 消息就能提交。 | 7 / 6 | **留**：无授权提交 | 安全底线 |
| GP-16 | /commit 授权未用时的 auto-bulk 提交 | 从未见到 | auto-bulk 提交会抢在 /commit 前面。 | 8 / 8 | **留**：调度规则，便宜 |  |
| GP-17 | `minted_by.origin` 不对的授权 | 拒绝 0 / 触及 20（git commit 20 次，18 次持授权放行） | 伪造的授权也能用来提交。 | 78 / 15 | **留**：无授权提交 | 安全底线 |
| GP-18 | 主代理花掉提交授权 | 拒绝 0 / 触及 20（同上；主代理提交 0 次） | 主代理能用给 changelog-analyst 的授权提交。 | 16 / 5 | **留**：授权绑定角色 | 安全底线 |
| GP-19 | 没有 changelog-analyst 派发证明的提交 | 拒绝 0 / 触及 20（同上） | 任何子代理都能花掉授权。 | 11 / 10 | **留**：无授权提交 | 安全底线 |
| GP-20 | 授权有 task_id 但消息缺 `Task-id:` 行 | 拒绝 0 / 触及 20（同上） | 授权能被用来提交别的任务。 | 21 / 10 | **留**：授权绑定任务 | 安全底线 |
| GP-21 | 环境里带 GIT_DIR 时的授权提交 | 拒绝 0 / 触及 20（同上） | 授权提交可以落到另一个仓库。 | 20 / 6 | **留**：授权绑定仓库 | 安全底线 |
| GP-22 | `bash -c "git commit …"`（两个读取器不一致） | 拒绝 0 / 触及 20（同上） | 两个读取器意见不一时放行。 | 9 / 0 | **留**：功能留；一个解析器后自然不需要单独写 | 安全底线 |
| GP-23 | 一次调用里两个 `git commit` | 拒绝 0 / 触及 20（同上） | 一个授权提交多次。 | 15 / 5 | **留**：无授权提交 | 安全底线 |
| GP-24 | `cd x && git commit -F m` | 拒绝 0 / 触及 20（同上） | 授权提交被重定向到别的仓库或目录。 | 20 / 8 | **留**：授权绑定仓库 | 安全底线 |
| GP-25 | `git -C a -C b commit` | 拒绝 0 / 触及 20（同上） | 同上。 | 8 / 3 | **留**：同上 | 安全底线 |
| GP-26 | `git -C "${GIT_ROOT}" commit -F m` | 拒绝 0 / 触及 20（同上） | 同上。 | 9 / 3 | **留**：同上 | 安全底线 |
| GP-27 | 授权 repo_root 与目标仓库不同 | 拒绝 0 / 触及 20（同上） | 授权能提交到别的仓库。 | 21 / 8 | **留**：同上 | 安全底线 |
| GP-28 | 授权分支与当前分支不同 | 拒绝 0 / 触及 20（同上） | 授权能提交到别的分支。 | 13 / 5 | **留**：同上 | 安全底线 |
| GP-29 | 授权 expected_head 与 HEAD 不同 | 拒绝 0 / 触及 20（同上） | 授权能提交到移动过的 HEAD 上。 | 25 / 8 | **留**：同上 | 安全底线 |
| GP-30 | `git commit -m x` | 拒绝 2 / 触及 20（git commit 20 次；2 次拒绝都是 /clean 里 cleaner 无授权提交） | 任何代理不经授权就能提交。 | 16 / 8 | **留**：无授权提交；唯一真的拒绝过的规则 | 安全底线 |
| OG-03 | `rm .claude/overnight-state-x.json` | 拒绝 0 / 触及 52（overnight 中提到状态文件 52 次，全是读³） | 代理能改 overnight 状态，关掉其余 overnight 规则。 | 25 / 8 | **留**：其余 overnight 底线规则的开关 | 安全底线 |
| OG-04 | `echo x > <home>/elsewhere/a` | 拒绝 0 / 触及 134（overnight 中有写目标 134 次³） | 无人值守时代理能写 worktree 外的文件，包括主人的 checkout。 | 23 / 20 | **留**：覆盖主人文件 | 安全底线 |
| OG-05 | owner/child 写自己 worktree 外 | 拒绝 0 / 触及 134（同上³） | 同上。 | 31 / 25 | **留**：同上 | 安全底线 |
| OG-07 | 状态里没有 worktree_path 的 owner/child | 拒绝 0 / 触及 318（overnight 调用 318 次都过³） | 隔离信息缺失时照常放行。 | 13 / 13 | **留**：兜底 | 安全底线 |
| OG-08 | `git -c core.hooksPath=/dev/null status` | 从未见到 | overnight 中能临时关掉 git 钩子。 | 127 / 30 | **留**：钩子完整性 |  |
| OG-09 | `git config core.hooksPath /dev/null` | 从未见到 | overnight 中能在任意仓库改 hooksPath。 | 134 / 40 | **留**：同上 |  |
| OG-10 | `echo x > w1/.git/config.worktree` | 从未见到 | 能直接改 worktree 的 git 配置。 | 63 / 15 | **留**：同上 |  |
| OG-11 | `git --git-dir=$P/.git log` | 从未见到 | 从 worktree 直接操作主仓库的 git 目录。 | 29 / 10 | **留**：绕开 OG-14 | 安全底线 |
| OG-12 | `git --work-tree=$P status` | 从未见到 | 从 worktree 直接操作主仓库的工作区。 | 32 / 10 | **留**：绕开 OG-14/17 | 安全底线 |
| OG-13 | `python3 -c 'subprocess.run(["git","checkout","master"])'` | 拒绝 0 / 触及 200（overnight 中解释器调用 200 次³） | 用 python 包一层就能对主仓库做危险 git 操作。 | 98 / 60 | **留**：同上 | 安全底线 |
| OG-14 | `git -C $P status` | 拒绝 0 / 触及 24（overnight 中 git 调用 24 次，都是 log/rev-parse³） | 无人值守时代理能在主人的 checkout 里跑任意 git。 | 6 / 6 | **留**：主仓库的总闸 | 安全底线 |
| OG-15 | `cd $X && git checkout foo` | 从未见到 | cd 到不明目录后能移动 HEAD。 | 13 / 10 | **留**：兜底 | 安全底线 |
| OG-16 | `git checkout master` | 从未见到 | 能切到受保护分支或覆盖主仓库文件。 | 9 / 9 | **留**：覆盖主人文件 | 安全底线 |
| OG-17 | `git restore file`（在主仓库） | 从未见到 | 能丢掉主人 checkout 里的未提交改动（BS-39 只拦 --source 整树）。 | 7 / 7 | **留**：删用户改动 | 安全底线 |
| OG-18 | `git stash pop`（在主仓库） | 从未见到 | 能把 stash 弹进主人 checkout，造成冲突。 | 8 / 8 | **留**：便宜 |  |
| OG-22 | `git worktree add ../w` | 从未见到（overnight 中 0；`git worktree list` 4 次在 merge 流水线） | overnight 中代理能自建 worktree（BB-01 在 overnight 里放行）。 | 4 / 5 | **留**：要收窄到会改东西的子命令 |  |
| OG-23 | 没有状态的 worktree_context 里跑 git | 拒绝 0 / 触及 224（overnight 中 git/解释器调用 224 次³） | 状态缺失时放行 git 和解释器。 | 34 / 20 | **留**：兜底 | 安全底线 |
| OG-24 | `echo x > $P/.git/refs/heads/master` | 从未见到 | 能直接改主仓库的分支引用。 | 49 / 15 | **留**：改历史 | 安全底线 |
| OG-25 | 无 bwrap 时 `echo x > $P/a.txt` | 拒绝 0 / 触及 274（overnight 中有写目标或解释器 274 次³） | 没有 bwrap 时对主仓库的写全部放行。 | 52 / 40 | **留**：兜底 | 安全底线 |
| TP-01 | `lib` 导入失败时的 `echo hi` | 拒绝 0 / 触及 2325（每次调用都过） | tool-policy 一崩，所有受保护路径都放行。 | 24 / 5 | **留**：兜底 | 安全底线 |
| TP-02 | `echo x > ~/.claude/.gitattributes` | 从未见到（有写目标的 352 次都不碰这些路径） | 代理能改 harness 的 .git/config、.git/hooks、pre-commit，从而绕过提交检查。 | 50 / 30 | **留**：提交授权/钩子 | 安全底线 |
| TP-03 | `echo x > docs/dev/requirement-answers-x.json` | 从未见到（同上） | 代理能伪造主人的回答。 | 4 / 3 | **留**：便宜 |  |
| TP-04 | `echo x > <config>/logs/lifecycle.jsonl` | 从未见到（同上） | 代理能伪造生命周期日志。 | 2 / 2 | **留**：便宜 |  |
| TP-05 | `echo x > ~/.claude/projects/p/s.jsonl` | 从未见到（同上） | 代理能改会话记录（恢复靠它）。 | 2 / 2 | **留**：便宜 |  |
| TP-06 | `echo x > <state>/claude-do-task-1.json` | 从未见到（同上） | 代理能伪造 /do 同意，放开 reset --hard、rebase、merge。 | 2 / 2 | **留**：改历史 | 安全底线 |
| TP-07 | `echo x > <state>/agentic-commit/push-analyst/a/b/c.json` | 从未见到（同上） | 代理能伪造推送授权或推送令牌。 | 51 / 45 | **留**：推送 | 安全底线 |
| TP-08 | `rm -rf ~/.claude/scripts` | 拒绝 0 / 触及 4（删除/移动 4 次） | 删整个目录就能绕过 TP-02..07。 | 11 / 10 | **留**：同 TP-02..07 | 安全底线 |
| TP-09 | 主代理 `echo x > docs/dev/qa-report-<id>.json` | 拒绝 0 / 触及 350（有写目标 350 次） | 别的代理能代写 QA 报告等产物。 | 141 / 120 | **留**：产物归属 |  |
| TP-10 | declared-paths 导入失败时的写 | 拒绝 0 / 触及 350（同上） | TP-09 一崩就放行。 | 9 / 9 | **留**：兜底 |  |
| TP-11 | /clean 期间别人写 cleaner 的已批准路径 | 拒绝 0 / 触及 8（/clean 中有写目标 8 次） | 别的代理能改 cleaner 的产物。 | 33 / 30 | **留**：产物归属 |  |
| TP-12 | 非所有者写 `<state>/agentic-commit/<role>/` | 拒绝 0 / 触及 18（写 agentic-commit 18 次，都是 locks） | 别的代理能写 analyst 的授权目录。 | 22 / 20 | **留**：提交/推送授权 | 安全底线 |
| TP-16 | ba 角色 `echo x > proj/src.py` | 拒绝 0 / 触及 70（子代理有写目标 70 次） | 各角色能写出自己的允许范围。 | 13 / 12 | **留**：角色边界 |  |
| TP-17 | 写兄弟派发的 `.claude/scratch/<rs>/<role>/<id>/` | 从未见到 | 并行的派发能互相改草稿区。 | 60 / 55 | **留**：与 TP-18 共用代码，删了省不了多少 |  |
| TP-18 | dev 角色 `echo x > /tmp/foo` | 拒绝 0 / 触及 36（子代理写 /tmp 36 次，都在角色例外内） | 子代理能随意写 /tmp。 | 44 / 40 | **留**：命中频繁，例外表在用 |  |

## 合计

| 项 | 数 |
|---|---|
| 规则总数 | 111 |
| 建议删 | 6（BS-13、BS-24、BS-27、BS-30、TP-13、TP-14） |
| 建议留 | 105 |
| 安全底线（全部是“留”） | 67 |
| 从未见到（拒绝 0，触及 0） | 53 |
| 真拒绝过 | 1 条（GP-30，2 次） |
| 全部接受后，今天少的行数 | 规则本身 155 行（11+10+8+14+38+74）；加上只给它们用的辅助函数（`check_docker_targets_all_dev` 27 行、`check_systemctl_targets_all_dev` 25 行）和 TP-13/TP-14 的说明注释块（20+22 行），共 **249 行** |
| 全部接受后，共享解析器上少写的行数 | 约 **57 行**（5+8+4+10+15+15） |

**删之前要知道的事**
- BS-27、BS-30：hook 不再拒，但 `settings.json` `permissions.deny` 照样拦（`Bash(dd:*)`、`Bash(mkfs:*)`、`Bash(fdisk:*)`，以及 systemctl 的 8 个动词）。计划把 BS-18 并进 deny 也是这个做法。被它们钉住的测试要改成断言 deny 条目还在：`test_bash_safety_context_rules.py` 里 dd/mkfs 的测试，`test_env_configured_defaults.py` 里 systemctl 的两个测试。`bash -c 'systemctl restart x'` 这种包装形式，删后只剩 BS-02 拦，而且要在没有 runtime 配置文件时才拦。
- BS-24：被 `test_env_configured_defaults.py::test_process_family_rules` 钉住。如果某台机器设了 `CLAUDE_PROTECTED_PROCESS_FAMILY`，要改用 runtime_guard 的 `protected_proc_idents`。
- BS-22 原计划并进 BS-30；BS-30 删掉以后，它的接手方就是 `settings.json` deny 加 BS-02。
- BS-13 写旗标的那一半没有测试钉住；它误拦 `cat <flag> | cat`（计划 O6）。

**脚注**
- ¹ BS-08 和 GCL-01..08 只在两个授权出口运行：`/do` 同意，或 `/allow` 哨兵匹配。转储不记录当时同意是否生效，所以 12 是上限：两次 `do` 回放里主代理的全部 Bash 调用。转储里看不出有没有 `/allow` 哨兵匹配过。
- ² GC-11：分类器的 `_command_token_index` 在命令词前面跳过了前缀、而且那个词是 git 的分段，共 4 次（`if git rev-parse …`）。
- ³ OG 规则只在有 overnight 运行时才生效，所以只在 overnight 回放里数（318 次调用）。状态文件不一定每次调用都在，所以也是上限。
- 截断：TSV 的命令列截在 300 个字符，1,542 条不同命令里有 374 条被截断。计数没用截断后的文本，用的是回放目录里 `invocations.jsonl` 的完整命令；完整命令的 sha256 前 12 位与 TSV 的 `cmd_sha12` 逐条一致（2,325 条）。所以没有因为截断而判断不了的行。

## 方法

- **数据来源**：`$SCRATCH/baseline/artifact-check-bash-decisions.tsv`（1,494 条）和 `replay-partial-bash-decisions.tsv`（831 条）。完整命令来自生成这两份 TSV 的回放目录（`$SCRATCH/artifact-work`、`$SCRATCH/replay-partial`），读法与 `tools/p14/dump_replay_decisions.py` 相同，条数一致。
- **拒绝计数**：读 `hook_verdicts` 列。非 `ok/0` 的只有 12 个：`pretool-launch.py` 6 个（它是汇总）、`pretool-orchestrator-gate.py` 4 个（不在这 111 条里）、`pretool-git-privilege-guard.py` 2 个。bash-safety、write-gate（TP、OG）、branch-pr 和 worktree 守卫每次都是 `ok/0`。那 2 个 GP 拒绝，在一次性 HOME 里重跑了一遍：HOME 是 `$SCRATCH/keep-review/home`，`.claude` 是 HEAD 的 `git archive`，`GIT_CONFIG_GLOBAL` 指向空文件，`CLAUDE_STATE_DIR` 在 scratch 里，工作目录是一次性仓库。消息来自 `_block_default_deny_commit`，也就是 GP-30。
- **触及计数**：git 子命令用 `hooks/lib/git_command_classifier.py` 的 `classify_git_command`。`-c` 层用 `iter_shell_texts`，引号里的调用用 `_segment_invocations(tagged=True)`，GP-01 用 `_may_run_git`。写目标用 `hooks/lib/bash_write_targets.py` 的 `extract_bash_write_paths`（F）和 `extract_bash_touched_paths`（T）。文件名、命令词类的规则用正则匹配完整命令。每条的触发族写在“真实会话遇到几次”一列里。
- **对抗语料**：`corpus-decisions.tsv` 的 39 个用例全部 `pass`，不计入上面的“真实会话”。
- **行数**：“现在行数”取自 `P14-inventory/` 里的行号区间。多段区间相加；几条规则共用的代码块只算一次，标在第一条上。“估计行数”是改成共享解析器 `hooks/lib/shell_parse.py` 上一个判断后的粗估。TP、OG 里的大部分代码是转录、派发或状态读取，不是 Bash 解析，所以估计值降得不多。
- **核对 111 条名单**：与清单一致，BS 33 + GP 22 + GC 11 + GCL 8 + TP 17 + OG 19 + BB-01 = 111。有三处措辞差异，不影响名单：
  - 清单把 GP-08、GP-09 归为 GITHUB，计划按 Q1 (b) 把它们改成 KEEP；
  - 清单说 BS-13 只在 BS-09 还在时才算 KEEP，而计划把 BS-09 归为 MERGE；
  - 计划 1.1 节正文写“The 109 KEEP rules”，同一节的表里是 111。
