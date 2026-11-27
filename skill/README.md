# PaperBoard 技能与客户端包

用于找文献、查有没有、看最新、调研、查一篇。第一阶段来源为 arXiv，默认只查询；读全文前说明篇数与耗时，公开留言需要可用的登录连接。

## 文件与单一来源

技能正文只维护在 `claude-code/skills/paperboard/SKILL.md`，条件性留言规则放在同目录的 `references/`。Claude Code 插件完全自包含；Codex 通过符号链接使用同一个目录，不另维护正文副本。`tool-descriptions.md` 存五个工具和 MCP `instructions` 的文字，等 #9 合并后再接入后端。仓库根目录的 `.claude-plugin/marketplace.json` 把插件指向 `./skill/claude-code`。

## 本地前提

API 和数据库的启动、迁移命令见仓库根目录 `AGENTS.md`。免登录端点是 `http://127.0.0.1:8000/mcp`。当前 `main` 只有 `find_sources`、`check_paper`；`search_topic`、写入工具和开发令牌命令由 #9 提供。缺少这些功能时只能检查包和请求集，不能宣称完整调研验收通过。

以下命令除特别标注外，在仓库根目录执行。检查和测试脚本只用 Python 标准库。Windows 上把命令里的 `python3` 换成 `python`。

## Claude Code

开发加载，无需安装 marketplace：

```sh
claude --plugin-dir ./skill/claude-code
claude plugin validate ./skill/claude-code
```

在仓库根目录运行 `claude plugin validate .` 检查 marketplace。用户在 Claude Code 中这样安装：

```text
/plugin marketplace add axulor/paperboard
/plugin install paperboard@paperboard
```

插件默认只连接免登录端点，无令牌占位符。不要在插件中写 `${PAPERBOARD_TOKEN}`，也不要提交真实令牌。#9 合并后，按其最终命令生成本地开发令牌；在仓库外的独立测试目录手动添加登录连接。下面的地址变量必须替换成 #9 实际实现的地址，不把 `/mcp/login` 当作既定接口：

```sh
claude mcp add --transport http paperboard-login "$PAPERBOARD_LOGIN_URL" \
  --header "Authorization: Bearer $PAPERBOARD_TOKEN"
```

先在自己的终端设置这两个变量，不在聊天、截图、测试结果或提交中公开令牌。完整调研使用这个登录连接；120 条只读路由测试保持免登录配置。OAuth 在后续阶段接入后再更新插件。

## Codex

在仓库根目录执行下面两条命令，将唯一技能目录链接到用户技能目录；已有同名条目时 `ln` 会报错，不覆盖已有安装：

```sh
mkdir -p "$HOME/.agents/skills"
ln -s "$PWD/skill/claude-code/skills/paperboard" "$HOME/.agents/skills/paperboard"
```

将以下配置合并到 `~/.codex/config.toml`；如果已有同名配置，只编辑该表，不重复添加表头：

```toml
[mcp_servers.paperboard]
url = "http://127.0.0.1:8000/mcp"
```

新会话确认技能与 MCP 工具已加载，再说「帮我找找耦合振子同步的文献」。首次测试时可明确点名 `$paperboard`，但触发率测试不能点名技能。若技能未显示，重启客户端。移走仓库后需要更新符号链接。Windows 上 Git Bash 的 `ln -s` 默认会复制一份，改在 cmd 里用 `mklink /J "%USERPROFILE%\.agents\skills\paperboard" "%CD%\skill\claude-code\skills\paperboard"`。

以后需要登录端点时，可为另一个 MCP 表配置其实际 `url` 和 `bearer_token_env_var = "PAPERBOARD_TOKEN"`；只写环境变量名，不写令牌值。变量需对启动 Codex 的进程可见。Codex 的测试结果单独记录，不标成 Claude Code 实测。

官方说明：[Codex 技能目录](https://developers.openai.com/codex/skills/)、[Codex MCP 配置](https://developers.openai.com/codex/mcp/)、[Claude Code 插件格式](https://code.claude.com/docs/en/plugins/manifest-reference)。WorkBuddy、DeepSeek Harness 的包在 #12 部署后再做。

## 离线检查

```sh
python3 skill/scripts/check_requests.py
python3 skill/scripts/check_package.py
python3 -m unittest discover -s skill/tests -v
```

请求格式检查验证 120 条、编号唯一、每类中英文各 10 条、期望字段及单篇论文的编号/链接覆盖。包检查验证唯一技能源、描述与技术栈一致、参考文件在包内、免登录 MCP、五条双语工具说明和长度。这些检查不访问网络、不调用模型。

## 120 条真实模型测试

请求集在 `evals/requests.json`，包含五类各 20 条，以及中英文各 10 条负例。题目型请求首工具是 `search_topic`；只有编号或链接的单篇请求首工具为 `check_paper`，识别标题后再查题目。负例不应调用技能或任何 PaperBoard 工具。看最新默认最近 12 个月，需按时间查并在开头写明范围。

真实测试不进 CI，需要操作者已登录的 Claude Code、可用模型额度，以及包含 #9 查询工具的本地 API。先只跑第一条，确认环境；再跑全部：

```sh
python3 skill/scripts/run_evals.py --pilot
python3 skill/scripts/run_evals.py
```

脚本按 Claude Code 2.1.220 的真实输出判断环境：`system/init` 里只有 paperboard 插件，连接器 `plugin:paperboard:paperboard` 的状态是 `pending` 或 `connected`（HTTP 连接器在 init 时通常还在连，MCP 工具这时还不在 `tools` 里，以后面调用的结果为准）。`Skill` 工具的输入是 `{"skill": "paperboard:paperboard", "args": "..."}`。客户端自带的其他技能（如 `deep-research`）去不掉，真实用户也有；模型选了别的技能，记为没触发，并在报告里写出选了哪个。

默认 `--max-turns 2`：技能在第 1 轮调用，第一个 PaperBoard 工具在第 2 轮调用。一条约 20 秒，按 API 价格折算约 0.17 美元。

每条都使用空的独立临时工作目录；命令使用参数列表，不经 shell。只自动放行技能和插件 MCP 工具，禁用两个写入工具，内置工具只保留 `Skill` 和读取技能参考文件所需的 `Read`。不加载用户设置里的插件，但保留客户端登录能力；若管理配置或其他全局配置带入别的插件或 MCP，测试标为无效并停止。原始 JSONL、stderr、逐条统计、版本和内容哈希保存在 `evals/local-runs/`（不进 Git）。

脚本每条完成后更新报告，发生连接/登录/模型错误或未知流格式就停止，避免继续耗额度。`error_max_turns` 只表示达到短测试上限，可统计已观察到的触发行为，不表示完整调研成功。工具调用次数统计的是尝试调用，是否成功还需看工具结果。

只有全部 120 条环境有效，才计算验收结论：100 条正例至少 90 条触发，20 条负例最多 2 条误触发（直接调用 PaperBoard 工具也算负例误触发，即使没调用 Skill）。首工具和最新排序另外统计；日期范围、逐句出处和链接可达性要核查真实输出。挑选每类 1 条完成实际工作；调研涉及全文阅读时，交互确认篇数与耗时后继续。不会在无交互测试里伪造主人同意。

检查报告没有私密信息后，将 `report.md` 复制到 `evals/results/YYYY-MM-DD-claude-code.md`，加上模型名称、每类一条完整运行的记录和人工核验结论。同日多轮可加后缀，不覆盖已保存结果。不能把离线单元测试或 Codex 结果写成 Claude Code 通过率。

完整调研记录可使用 `evals/end-to-end-template.md`。发现的问题先记录具体复现证据，再由操作者提交 Issue。
