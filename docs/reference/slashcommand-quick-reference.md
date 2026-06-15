# Slash Command Quick Reference

**28 global slash commands** available in all projects. No approval prompts required.

## 🧠 AI Thinking & Analysis

| Command | Usage | Description |
|---------|-------|-------------|
| `/think [hard\|harder\|ultra]` | `/think hard "solve algorithm"` | Extended thinking modes (2k-10k tokens) |
| `/ultrathink` | `/ultrathink "complex problem"` | Maximum depth reasoning (20k+ tokens) |
| `/explain-code [path]` | `/explain-code src/main.py` | Deep code explanation with educational focus |
| `/code-review [path]` | `/code-review src/**/*.py` | Comprehensive code review with best practices |
| `/security-check [path]` | `/security-check src/` | Security vulnerability analysis and recommendations |
| `/debug-help [error]` | `/debug-help "TypeError: ..."` | Debug assistance and troubleshooting guidance |

---

## 🔍 Research & Search

| Command | Usage | Description |
|---------|-------|-------------|
| `/deep-search <domain> <goal>` | `/deep-search example.com "find docs"` | Deep website exploration with iterative search |
| `/research-deep <topic>` | `/research-deep "FSRS algorithm"` | Multi-source research (15-20 searches) |
| `/search-tree <problem>` | `/search-tree "optimize query"` | Tree search with MCTS-inspired evaluation |
| `/reflect-search <goal>` | `/reflect-search "API usage examples"` | Reflection-driven iterative search with goal evaluation |
| `/site-navigate <url> <task>` | `/site-navigate https://... "find pricing"` | Intelligent site navigation simulating click-through |

**When to use**:
- `/deep-search` - When you need to explore a specific website thoroughly
- `/research-deep` - When you need comprehensive research from multiple sources
- `/search-tree` - When exploring solution spaces with multiple paths
- `/reflect-search` - When you need goal-driven iterative searching
- `/site-navigate` - When you need to navigate through a multi-page site

---

## 🛠️ Code Generation & Refactoring

| Command | Usage | Description |
|---------|-------|-------------|
| `/refactor [path]` | `/refactor src/utils.py` | Refactoring suggestions for code quality |
| `/optimize [path]` | `/optimize src/algorithm.py` | Performance optimization opportunities |
| `/test-gen [path]` | `/test-gen src/calculator.py` | Generate comprehensive test cases |
| `/doc-gen [path]` | `/doc-gen src/api.py` | Generate comprehensive documentation |

**Best practices**:
- Run `/code-review` before `/refactor` for context
- Use `/optimize` after profiling to identify bottlenecks
- Generate tests with `/test-gen` before major refactors
- Update docs with `/doc-gen` after API changes

---

## 🎨 Artifact Creation

| Command | Usage | Description |
|---------|-------|-------------|
| `/artifact-react [name] [libs]` | `/artifact-react dashboard d3,recharts` | Create standalone React app with libraries |
| `/artifact-mermaid [type]` | `/artifact-mermaid flowchart` | Create interactive Mermaid diagrams |
| `/quick-prototype [desc]` | `/quick-prototype "Task board with drag-drop"` | Rapid prototyping combining multiple tools |

**Artifact types**:
- **React apps**: Full-stack applications with state management
- **Mermaid diagrams**: Flowcharts, sequence diagrams, class diagrams
- **Excel analyzer**: Formula extraction and data visualization
- **Quick prototypes**: Interactive demos and proofs of concept

**Output**: All artifacts saved as standalone HTML files

---

## 📊 File Analysis

| Command | Usage | Description |
|---------|-------|-------------|
| `/file-analyze [path] [question]` | `/file-analyze data.xlsx "extract formulas"` | Analyze PDF, Excel, Word, images with deep insights |

**Supported formats**:
- **PDF**: Text extraction, OCR, structure analysis
- **Excel**: Formula extraction, data statistics, cross-sheet references
- **Word**: Structure analysis, style extraction
- **Images**: OCR, object detection, visual description

---

## 🚀 Git Workflow

| Command | Usage | Description |
|---------|-------|-------------|
| `/push` | `/push` | Validated git push with auto-staging and safety checks |
| `/pull` | `/pull` | Pull with automatic stash management |
| `/quick-commit [prefix]` | `/quick-commit "fix"` | Auto-generated commit with well-formatted message |
| `/checkpoint` | `/checkpoint` | Create git checkpoint without pushing |

**Safety features**:
- `/push`: Detects untracked files, offers auto-staging, validates remote
- `/pull`: Stashes changes, pulls, reapplies stash automatically
- `/quick-commit`: Analyzes changes and generates descriptive commit message
- `/checkpoint`: Creates local checkpoint for experimental work

---

## ⚙️ System Management

| Command | Usage | Description |
|---------|-------|-------------|
| `/status` | `/status` | Show current Claude Code configuration and capabilities |
| `/fswatch` | `/fswatch` | File watching utility for auto-reload workflows |
| `/playwright-helper` | `/playwright-helper` | Guide for using Playwright MCP with deep search |

---

## 💡 Pro Tips

### Combining Commands

**Research → Implement → Test**:
```
/research-deep "FastAPI authentication patterns"
/artifact-react auth-demo fastapi
/test-gen src/auth.py
```

**Analyze → Optimize → Document**:
```
/code-review src/processor.py
/optimize src/processor.py
/doc-gen src/processor.py
```

**Deep Thinking → Code Review → Refactor**:
```
/ultrathink "How to improve this architecture?"
/code-review src/
/refactor src/core.py
```

### Command Aliases (Mental Model)

Think of commands by purpose:

| I want to... | Use command |
|--------------|-------------|
| Think deeply | `/ultrathink` |
| Search thoroughly | `/deep-search` or `/research-deep` |
| Fix code | `/code-review` → `/refactor` |
| Speed up code | `/optimize` |
| Create a demo | `/quick-prototype` or `/artifact-react` |
| Understand code | `/explain-code` |
| Create tests | `/test-gen` |
| Commit changes | `/quick-commit` |
| Push safely | `/push` |

### When to Use Extended Thinking

| Complexity | Command | Token Budget | Use Case |
|-----------|---------|--------------|----------|
| **Simple** | (none) | Default | Standard queries, direct tasks |
| **Moderate** | `/think` | 2,048 | Multi-step problems, analysis |
| **Complex** | `/think hard` | 5,000 | Architecture decisions, algorithms |
| **Very Complex** | `/think harder` | 10,000 | System design, optimization |
| **Maximum** | `/ultrathink` | 20,000+ | Research, deep exploration, novel solutions |

**Rule of thumb**: Use extended thinking when:
- Multiple solution paths exist
- Trade-offs need careful evaluation
- Problem requires breaking into sub-problems
- Edge cases need thorough analysis

---

## 📖 Additional Resources

### Full Documentation
- Complete command list: `~/.claude/commands/README.md`
- Individual command details: `~/.claude/commands/*.md`
- Hook system: `~/.claude/hooks/README.md`

### Configuration
- Global settings: `~/.claude/settings.json`
- Permission rules: `~/.claude/settings.json` → `permissions`
- Environment variables: `~/.claude/settings.json` → `env`

### Audit Logging
- Command usage: `~/.claude/logs/slashcommand-audit.log`
- Session logs: `~/.claude/session.log`

### Getting Help
```bash
# In Claude Code
/help                          # Shows available commands
/status                        # Shows configuration
cat ~/.claude/commands/README.md   # Full command documentation
```

---

## 🔐 Security Note

All slash commands respect:
- **Permission rules** in `settings.json`
- **File deny patterns** (no access to `.env`, credentials, etc.)
- **PreToolUse hooks** for dangerous operations
- **PostToolUse hooks** for audit trails

Commands themselves are low-risk (they're just prompts), but the **tools they invoke** (Bash, Write, Edit, etc.) are still subject to permission checks.

---

## 📊 Usage Analytics

View your command usage:
```bash
# Show command frequency
cat ~/.claude/logs/slashcommand-audit.log | cut -d'|' -f3 | sort | uniq -c | sort -nr

# Show recent commands
tail -20 ~/.claude/logs/slashcommand-audit.log

# Find commands used in specific project
grep "knowledge-system" ~/.claude/logs/slashcommand-audit.log
```

---

**Last Updated**: 2026-05-28
**Version**: 1.1
**Total Commands**: 28

## Graphify Integration

The `/dev`, `/dev-command`, `/dev-overnight`, and `/redev` commands include Graphify knowledge graph integration (spec-20260527-061433). Pass `--no-graphify` to disable per-invocation. `/pull` triggers a non-blocking incremental cache update. `/clean` has graphify disabled. See `docs/reference/graphify-integration.md` for full architecture.
