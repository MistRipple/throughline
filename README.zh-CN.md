# throughline

[English](README.md) | 中文

在上下文压缩中，让 Codex 编码 agent 守住**最初的目标和真实的进度**。

## 问题

会话一长，Codex 会把上下文压缩成摘要。两种失败模式最要命：摘要把目标收窄了，或者保留了目标文字却丢了具体进度。第二种会引发压缩风暴：agent 反复重读同一个大文件、再次压缩，永远走不到编辑或测试那一步。

## 思路

throughline 把任务状态分三层保存，按实际作用大小排序：

1. **磁盘上的目标卡。** 目标、范围、里程碑、下一步都写在 `.throughline.md`。磁盘内容压缩不掉。
2. **Codex 压缩时刻状态锁。** `experimental_compact_prompt_file` 强制压缩摘要带上 `OBJECTIVE LOCK`、`PROGRESS CHECKLIST`、`COMPLETED INPUTS / DO-NOT-REPEAT`、`NEXT ACTION`。
3. **注入器 hook。** 在手动发言和 `SessionStart` startup/resume 时把卡片重新喂回去。

### 诚实的边界

没有任何 hook 能拦截**进程内**压缩，而长时间自动跑恰恰死在这里。Codex 的压缩提示词必须在风暴中把进度往前带；磁盘卡片是在它被写出或再次注入之后起作用。风暴持续时，减少嘈杂输出，在里程碑处切到新线程、把卡片带过去做无损交接。

其他 agent 工具这里故意不接，除非它们暴露等价的压缩提示词覆盖能力。throughline 聚焦 Codex，因为只有这里能把保护结构强制写进压缩摘要本身。

## 安装

```bash
git clone <this-repo> ~/code/throughline
cd ~/code/throughline
./install.sh            # 写入 Codex hooks + config.toml
./install.sh --print    # 只预览，不落盘
```

安装器会替你改 Codex `config.toml`：写入一个带哨兵（`# >>> throughline >>>`）的托管块，含 `experimental_compact_prompt_file` 加上 Codex 真正接受的内联 `[hooks.*]` 表，先备份 `config.toml`，并清掉旧版遗留的 `hooks.json`。Codex 会拒绝 `hooks = "./hooks.json"`，所以 throughline 绝不写那种形式。见 [codex-setup.md](skills/throughline/references/codex-setup.md)。

随时可卸载：`./install.sh --uninstall`。安装器幂等，会保留其他工具的 hooks 和你自己的配置项。

## 使用

用 `card.py` 管理卡片：它保证一任务一卡，绝不让已完成的目标渗进下一个任务。

1. 开工。这会归档已有卡片，再写一张新卡，并把目标**逐字**存进去：
   ```bash
   python3 skills/throughline/scripts/card.py init \
     --objective "用户诉求，逐字照抄" --task-type feature
   ```
2. 推进卡片。每个里程碑前重读，完成后更新清单、`COMPLETED INPUTS / DO-NOT-REPEAT` 和 `NEXT ACTION`。保持精简：原地覆盖，绝不追加增长，遵守体积预算。字段说明见[模板](skills/throughline/assets/throughline-card.template.md)和 [examples/refactor.throughline.md](examples/refactor.throughline.md)。
3. 收工用 `card.py done`。此后 hook 保持沉默，直到下一次 `init`，已完成的目标不会渗进新任务。若重新捡起任务，用 `card.py reopen` 重新激活。

每次 `init` 都会把上一张卡归档到 `.throughline/archive/`(磁盘卡被 gitignore，归档是它唯一的备份)。卡片自动定位：hook 从工作目录逐级向上找 `.throughline.md`，也可以用 `$THROUGHLINE_CARD` 指向任意路径。

## 验证

先跑确定性本地检查：

```bash
python3 scripts/verify_local.py
```

provider 响应正常时，跑真机 Codex 压缩试验：

```bash
python3 scripts/run_codex_compaction_trial.py --timeout 900 --keep
python3 scripts/run_codex_compaction_trial.py --compare --timeout 900
python3 scripts/run_codex_compaction_trial.py --isolate --timeout 900
python3 scripts/run_codex_compaction_trial.py --isolate --repeat 3 --timeout 900
```

真机试验会建一个隔离的 `CODEX_HOME`，绝不动你的真实配置。它生成一个小重构任务加一个大到足以触发压缩的 `NOTES.md`，然后报告压缩次数、最后一份摘要是否含 `OBJECTIVE LOCK` 和 `COMPLETED INPUTS / DO-NOT-REPEAT`、是否产出了 `Calculator`、卡片勾选了几项。

### 实测结果

#### 直接漂移测试

真机 Codex，固定内联 hooks 安装，`20000` token 上限强行制造压缩风暴。目标卡写的是**“构建一个全新的邮件通知功能”**；工作区掺了 1500 行 `加固现有 / 清理现有 / 收紧遗留` 的工单，主动把模型往收窄方向拉。

```bash
python3 scripts/verify_drift.py --modes single,multi,goal --repeat 2 --token-limit 20000
```

本机真实结果：

| 模式 | 跑数 | 压缩次数 | 收窄为“加固现有” | 仍点名构建目标 | 携带 `OBJECTIVE LOCK` |
| --- | --- | --- | --- | --- | --- |
| single | 2 | 51 | **0** | 46 | 40 |
| multi | 2 | 51 | **0** | 49 | 31 |
| goal | 2 | 44 | **0** | 39 | 16 |

三种模式合计 **146 次压缩、0 次漂移**到“加固现有代码”。同机第二轮独立验证复现：**159 次压缩、0 次漂移**。

#### 核心杠杆，单独隔离

真机 `--isolate --repeat 3`，Codex 使用当前配置的 provider，`60000` token 上限，NOTES.md 大小刚好一次读完。该杠杆没有磁盘卡片、没有卡片感知提示词；相对基线唯一的改动就是压缩提示词覆盖。

| 模式 | 跑数 | 压缩次数（中位/区间） | 完成 | 摘要含 OBJECTIVE LOCK | 含 DO-NOT-REPEAT |
| --- | --- | --- | --- | --- | --- |
| 基线（默认压缩） | 3 | 1（1-2） | 3/3 | 0% | 0% |
| 仅核心杠杆 | 3 | 1（1-1） | 3/3 | 100% | 100% |

诚实结论：在任务能完成的预算下，该杠杆**不**可靠地减少压缩次数。稳健、可复现的差别在于**压缩摘要的内容**。

#### 极端预算压缩风暴

真机 Codex A/B，故意压到 `40000` token，配一个约 320KB 的 `NOTES.md`、单次读取就超预算。

| 跑 | 压缩次数 | 重构完成 | 最终摘要保住目标 + DO-NOT-REPEAT |
| --- | --- | --- | --- |
| 默认基线 | 46 | 最终完成 | 无结构 |
| throughline | 54 | 未完成（撞到运行上限） | 是：每份摘要都有 OBJECTIVE LOCK + DO-NOT-REPEAT |

实用解读：throughline 的职责是让每份压缩摘要把目标和已完成工作带向前。它**不是**让你在小到连一次必要读取都放不下的预算里幸存的办法。

## 接线方式

| 层 | Codex |
| --- | --- |
| 目标卡 | 磁盘上的 `.throughline.md` |
| 压缩时刻状态锁 | `experimental_compact_prompt_file` |
| 重新注入 | `SessionStart` startup/resume + `UserPromptSubmit` |

## 目录结构

```text
throughline/
  install.sh
  marketplace.json
  scripts/{verify_local,run_codex_compaction_trial,verify_drift}.py
  examples/refactor.throughline.md
  skills/throughline/
    SKILL.md
    assets/throughline-card.template.md
    assets/compact_prompt.md
    scripts/throughline_hook.py
    scripts/install.py
    references/{mechanics,codex-setup}.md
```

注入器和安装器是**纯标准库 Python 3**，无依赖可装。

## 许可证

MIT。见 [LICENSE](LICENSE)。
