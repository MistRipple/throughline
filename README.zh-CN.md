# throughline

[English](README.md) | 中文

在上下文压缩中，让编码 agent 守住**最初的目标和真实的进度**。同时支持 **Codex** 和 **Claude Code**。

## 问题

会话一长，agent 会把上下文压缩成摘要。两种失败模式最要命：摘要把目标收窄了，或者保留了目标文字却丢了具体进度。第二种会引发压缩风暴——agent 反复重读同一个大文件、再次压缩，永远走不到编辑或测试那一步。

## 思路

throughline 把任务状态分三层保存，按实际作用大小排序：

1. **磁盘上的目标卡（核心）。** 目标、范围、里程碑、下一步都写在磁盘文件 `.throughline.md` 里。磁盘内容压缩不掉。
2. **压缩时刻的状态锁。** 强制 agent 在压缩时写的摘要带上 `OBJECTIVE LOCK`、`PROGRESS CHECKLIST`、`COMPLETED INPUTS / DO-NOT-REPEAT`、`NEXT ACTION`。Codex 上这是真正的压缩提示词覆盖；Claude 上由卡片配合 `PreCompact` 快照承担。
3. **注入器 hook。** 在手动发言、resume、会话启动时把卡片重新喂回去。同一个 hook 服务两个工具。

### 诚实的边界

没有任何 hook 能拦截**进程内**压缩，而长时间自动跑恰恰死在这里。Codex 的压缩提示词必须在风暴中把进度往前带；磁盘卡片是在它被写出或再次注入之后起作用。风暴持续时，减少嘈杂输出，在里程碑处切到新线程、把卡片带过去做无损交接。

## 安装

```bash
git clone <this-repo> ~/code/throughline
cd ~/code/throughline
./install.sh            # 同时接 Codex + Claude（hooks + Codex config.toml）
./install.sh --print    # 只预览要写入的 hook，不落盘
```

在 **Codex** 上，安装器会替你改 `config.toml`：写入一个带哨兵（`# >>> throughline >>>`）的托管块，含 `experimental_compact_prompt_file` 加上 Codex 真正接受的内联 `[hooks.*]` 表，先备份 `config.toml`，并清掉旧版遗留的 `hooks.json`。Codex 会拒绝 `hooks = "./hooks.json"`，所以 throughline 绝不写那种形式。见 [codex-setup.md](skills/throughline/references/codex-setup.md)。
在 **Claude** 上，加一个 `PreCompact` 快照，压缩后由 `SessionStart:compact` hook 重新注入。见 [claude-setup.md](skills/throughline/references/claude-setup.md)。

随时可卸载：`./install.sh --uninstall`。安装器幂等，会保留其他工具的 hooks 和你自己的配置项。

> 单独装 Codex：`python3 skills/throughline/scripts/install.py --codex`。

## 使用

1. 长任务开工时，把[模板](skills/throughline/assets/throughline-card.template.md)复制成仓库根目录的 `.throughline.md`，并把用户诉求**逐字**填进 `OBJECTIVE LOCK`。参见 [examples/refactor.throughline.md](examples/refactor.throughline.md)。
2. 每个里程碑前重读卡片；完成后更新清单、`COMPLETED INPUTS / DO-NOT-REPEAT` 和 `NEXT ACTION`。
3. 保持精简：原地覆盖，绝不追加增长，遵守体积预算。

卡片自动定位：hook 从工作目录逐级向上找 `.throughline.md`，也可以用 `$THROUGHLINE_CARD` 指向任意路径。

> 卡片是**每个任务一张**的本地工作文件。可以让 agent 在开工时自动建（命中 skill 后按约定建卡并维护），也可以你手动 `cp` 模板。机器级安装只装一次底座，不会替你凭空生成卡片。

## 验证

先跑确定性本地检查：

```bash
python3 scripts/verify_local.py
```

验证 Claude 保护流程（确定性，不调真模型）。Claude 没有可脚本化触发压缩的开关，所以这步用真实 Claude 事件载荷在隔离 `HOME` 里驱动已装的 hook，端到端检查快照 + 恢复路径：

```bash
python3 scripts/verify_claude_flow.py
```

provider 响应正常时，跑真机 Codex 压缩试验：

```bash
python3 scripts/run_codex_compaction_trial.py --timeout 900 --keep            # 仅 throughline
python3 scripts/run_codex_compaction_trial.py --compare --timeout 900         # 对照默认 A/B
python3 scripts/run_codex_compaction_trial.py --isolate --timeout 900         # 基线 vs 仅核心杠杆
python3 scripts/run_codex_compaction_trial.py --isolate --repeat 3 --timeout 900  # 各跑 3 次取中位数
```

真机试验会建一个隔离的 `CODEX_HOME`（绝不动你的真实配置），生成一个小重构任务加一个大到足以触发压缩的 `NOTES.md`，然后报告压缩次数、最后一份摘要是否含 `OBJECTIVE LOCK` 和 `COMPLETED INPUTS / DO-NOT-REPEAT`、是否产出了 `Calculator`、卡片勾选了几项。`--compare` 把默认基线和 throughline 背靠背各跑一遍并打印 A/B 表。`--isolate` 把基线对照**仅核心杠杆**（只开 `compact_prompt.md`，无卡片、无卡片感知提示词），任何差异都可归因于压缩提示词覆盖本身。`--repeat N` 每种模式跑 N 次，报告压缩次数中位数、区间、完成率，以及最终摘要带 `OBJECTIVE LOCK` 和 `COMPLETED INPUTS / DO-NOT-REPEAT` 的比例。

### 实测结果

#### 直接漂移测试：目标能扛过压缩吗？（核心问题）

真机 Codex，固定内联 hooks 安装，`20000` token 上限强行制造压缩风暴。目标卡写的是**“构建一个全新的邮件通知功能”**；工作区掺了 1500 行 `加固现有 / 清理现有 / 收紧遗留` 的工单，主动把模型往收窄方向拉。问题是：压缩后的摘要会不会把“构建功能”收窄成“加固现有代码”。自己跑：

```bash
python3 scripts/verify_drift.py --modes single,multi,goal --repeat 2 --token-limit 20000
```

它隔离 `CODEX_HOME`、装好 hooks、在每种模式下强制压缩风暴，并解析**每一份**压缩摘要。`single` 是单轮长任务；`multi` 是一轮加两次 `codex exec resume`（让 resume hook 跨轮重新注入卡片）；`goal` 给卡片加一行 `TOKEN BUDGET` 来对齐 goal 模式。本机真实结果：

| 模式 | 跑数 | 压缩次数 | 收窄为“加固现有” | 仍点名构建目标 | 携带 `OBJECTIVE LOCK` |
| --- | --- | --- | --- | --- | --- |
| single | 2 | 51 | **0** | 46 | 40 |
| multi | 2 | 51 | **0** | 49 | 31 |
| goal | 2 | 44 | **0** | 39 | 16 |

三种模式合计 **146 次压缩、0 次漂移**到“加固现有代码”，而噪声正是为诱发这种漂移而设计的。同机第二轮独立验证复现了结果：**159 次压缩、0 次漂移**（single 52、multi 56、goal 51）。无论单轮、多轮 resume，还是带预算的 goal，目标从不被收窄。（在这种病态紧的 20k 预算下，任务会在进度上反复打转、可能跑不完编辑；本测试隔离的是目标保持能力，真实预算下这种打转会消失。）

这一切的 token 开销有界。这里的目标卡是 **735 字节（约 183 token）**，注入器对喂给模型的内容硬截断在 9000 字符（约 2250 token），无论卡片多大，所以这套保护本身不会变成新的上下文泄漏（`verify_local.py` 用一个 50KB 卡片断言了这点）。

#### 核心杠杆，单独隔离（能扛过进程内压缩的那部分）

真机 `--isolate --repeat 3`，Claude Opus 4.8 provider，`60000` token 上限，NOTES.md 大小刚好一次读完。该杠杆没有磁盘卡片、没有卡片感知提示词；相对基线唯一的改动就是压缩提示词覆盖。各跑 3 次取中位数：

| 模式 | 跑数 | 压缩次数（中位/区间） | 完成 | 摘要含 OBJECTIVE LOCK | 含 DO-NOT-REPEAT |
| --- | --- | --- | --- | --- | --- |
| 基线（默认压缩） | 3 | 1（1-2） | 3/3 | 0% | 0% |
| 仅核心杠杆 | 3 | 1（1-1） | 3/3 | 100% | 100% |

诚实结论：在任务能完成的预算下，该杠杆**不**可靠地减少压缩次数，小重构两边都能完成。稳健、可复现的差别在于**压缩摘要的内容**。每一次杠杆跑都逐字复现了目标、把 NOTES 读取标 `[x]`、并在 `COMPLETED INPUTS / DO-NOT-REPEAT` 里记下 `cat NOTES.md` 已执行加内容摘要，NEXT ACTION 直指编辑 `calc.py`。没有一次基线带这两层结构。这种“带向前”就是防漂移机制：即便压缩次数相同，摘要是否保住原目标和已完成工作，决定了 resume 后的模型是往前推进还是重新推导出一个被收窄的目标。

#### 极端预算压缩风暴（用户真正的痛点）

真机 A/B，Claude Opus 4.8 provider，故意压到 `40000` token，配一个约 320KB 的 `NOTES.md`、单次读取就超预算。这会制造真正的压缩风暴，也就是催生本 skill 的长时自动跑失败场景。一次有代表性的跑：

| 跑 | 压缩次数 | 重构完成 | 最终摘要保住目标 + DO-NOT-REPEAT |
| --- | --- | --- | --- |
| 默认基线 | 46 | 最终完成 | 无结构（目标以散文残留；无防重读） |
| throughline | 54 | 未完成（撞到运行上限） | 是：每份摘要都有 OBJECTIVE LOCK + DO-NOT-REPEAT |

这场风暴的两个诚实发现：

1. 结构保证在极端压力下依然成立：每份 throughline 摘要都带 OBJECTIVE LOCK 和 COMPLETED INPUTS / DO-NOT-REPEAT，而基线两者都没有。这个重构任务里两边的目标都没被收窄成“加固/验证”；这里的主导失败是**进度丢失 / 重读**，不是目标收窄。
2. 在病态紧的预算下结果高方差，覆盖**不**保证更少压缩。这一跑里 throughline 比基线打转*更多*，在上限前没落地编辑。当每轮工作集（resume 摘要 + 工具 schema + 文件读取）逼近整个预算时，任何压缩提示词都救不回来。

实用解读：throughline 的职责是让每份压缩摘要把目标和已完成工作带向前，这点它做得可靠。它**不是**让你在小到连一次必要读取都放不下的预算里幸存的办法。在现实预算（`120000`）下任务零压缩完成；真实 Codex 在 `300000` 附近才压缩，那里根本不发生风暴，带向前是纯收益。

## 接线方式

| 层 | Codex | Claude Code |
| --- | --- | --- |
| 目标卡（SSOT） | 磁盘上的 `.throughline.md` | 磁盘上的 `.throughline.md` |
| 压缩时刻状态锁 | `experimental_compact_prompt_file` | `PreCompact` 快照 |
| 重新注入 | `SessionStart`（startup/resume）+ `UserPromptSubmit` | `SessionStart`（startup/resume/**compact**）+ `UserPromptSubmit` |

### 两个工具的保护强度并不相等

要诚实面对：进程内压缩摘要在哪一端真正受我们控制。

| | Codex | Claude Code |
| --- | --- | --- |
| 操控模型在压缩时写的摘要 | **能** —— `experimental_compact_prompt_file` 把 OBJECTIVE LOCK + DO-NOT-REPEAT 强进摘要本身 | **不能** —— 无受支持的提示词覆盖；`PreCompact` 输出是附加上下文，改写不了摘要 |
| 摘要退化时也能扛住 | 磁盘卡片 + 注入器 | `PreCompact` 快照到 `.throughline.precompact.bak` + 磁盘卡片 |
| 压缩后恢复目标/进度 | `SessionStart` resume 注入 | `SessionStart:compact` 重新注入（压缩后立即触发） |
| 保证落在哪 | 摘要**内部** | 摘要**外部**（之前快照、之后重注入） |

Codex 上目标和已完成输入保证落在**每一份**压缩摘要内部（已验证：3/3）。Claude 上摘要本身仍可能中途收窄目标；卡片快照和压缩后重注入是把它拉回来的手段。对长时自动跑的 Claude，磁盘卡片才是真正的锚，每个里程碑更新 COMPLETED INPUTS / DO-NOT-REPEAT 在那边比在 Codex 上更要紧。

## 目录结构

```
throughline/
  install.sh
  marketplace.json
  scripts/{verify_local,run_codex_compaction_trial}.py
  examples/refactor.throughline.md
  skills/throughline/
    SKILL.md
    assets/throughline-card.template.md
    assets/compact_prompt.md
    scripts/throughline_hook.py
    scripts/install.py
    references/{mechanics,codex-setup,claude-setup}.md
```

注入器和安装器是**纯标准库 Python 3**，无依赖可装。

## 许可证

MIT。见 [LICENSE](LICENSE)。
