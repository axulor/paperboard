# Codex 本地实现检查

日期：2026-11-26（Asia/Shanghai）。基线：`e0a119e`，工作分支：`10-skill`。

本记录是 Codex 执行的离线检查，不是 Codex 或 Claude Code 的 120 条真实模型触发率测试。

| 检查 | 结果 |
|---|---|
| 请求集结构与数量 | 通过：120 条，五类正例各中英文 10 条，负例中英文各 10 条 |
| 插件结构与引用路径 | 通过：正文唯一、引用文件在插件内、默认无令牌只读端点 |
| 描述与技术栈一致 | 通过：frontmatter 仅 name/description，与第 5.2 节原文一致 |
| 五条工具说明及 instructions | 通过：五条说明含规定中英文词，长度均不超过 600 字符 |
| Python 标准库单元测试 | 通过：19 项；覆盖污染环境、连接失败、未知 Skill 字段、运行中工具失败、负例直接调工具、重复事件、超时、触发阈值及 shell 隔离等 |
| Ruff 检查与格式 | 通过：使用 API 的 lint 规则，目标 Python 3.9 |
| skill-creator quick_validate | 通过 |
| 第二阶段补丁预检 | `git apply --check skill/integration.patch` 通过；补丁未应用 |
| Claude Code 插件原生验证 | 未运行：本机未安装 Claude Code，用户选择由 Codex 开发 |
| 120 条真实模型实测 | 未运行；无触发率数据 |
| 完整调研、公开留言、撤回 | 未运行：基线尚未包含 #9 的三个工具及开发令牌入口 |
| GitHub CI | 未运行：尚未推送或创建 PR |

执行命令（仓库根目录）：

```sh
python3 skill/scripts/check_requests.py
python3 skill/scripts/check_package.py
python3 -m unittest discover -s skill/tests -v
ruff check skill/scripts skill/tests --config api/pyproject.toml --target-version py39
ruff format --check skill/scripts skill/tests --config api/pyproject.toml --target-version py39
git apply --check skill/integration.patch
```

单元测试中的流事件为明确构造的离线测试数据，不是从真实客户端采集的样本；真实 `Skill` 输入字段必须先经 pilot 确认。未将任何模拟数据写成客户端验收结果。

结论：第一 PR 的实现和离线检查已准备好，Issue #10 尚未完整验收。后续需 #9 合并和真实客户端验证；若团队决定将指定的 Claude Code 验收改为 Codex，需同步验收口径，不能把本表改名充当实测。
