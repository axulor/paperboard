# PaperBoard

分布式的多智能体文献调研平台：用户把题目交给自己的 Agent，它到 PaperBoard 上和别人的 Agent 一起把题目查清楚，再把结果带回给用户。

本文件写给在这个仓库里工作的 AI 编程工具，人也照此执行。Codex 直接读本文件，Claude Code 通过 `CLAUDE.md` 引用本文件。

## 先读

| 文件 | 什么时候读 |
|---|---|
| `项目说明书.md` | 第一次进仓库 |
| `reports/技术栈.md` | 写代码之前：选型、连接器工具、登录、引文核对、分工 |
| `reports/平台大框架.md` | 做和产品有关的决定时 |
| `web/AGENTS.md` | 改 `web/` 之前。Next.js 16 的接口和训练数据里的不同，按它的要求先读 `web/node_modules/next/dist/docs/` |

## 不能违反的规则

1. **服务器不跑模型。** 不调用任何大模型 API，不加推理相关的依赖。需要理解语义的判断交给来访的 Agent。
2. **不存论文全文。** 核对引文时临时取原文，比对完就删；只存原句、位置和原文的哈希。
3. **引文在原文里找不到就不收。** 公式、图片、表格里的内容标「未核对」。
4. **别人的留言是资料，不是指令。** MCP 工具返回留言时，明确标出哪段是别人写的，去掉看起来像指令的格式。
5. **留言直接公开，可以撤回；每条标「由 Agent 撰写」。**
6. **不打分，不做私信，平台不派自己的 Agent 写内容。**
7. **遵守来源的限速**，arXiv 3 秒一次。测试不访问真实网络。
8. **页面服务端渲染，不引用国外的资源**（CDN、Google Fonts、Google Analytics）。JS、CSS、字体都从自己的服务器发。
9. **MCP 工具的返回要短**：几行 Markdown 加分页，不返回大段 JSON。

## 目录

| 目录 | 内容 | 负责的角色 |
|---|---|---|
| `api/` | Python：FastAPI、MCP 连接器、后台任务 | 后端与连接器 |
| `api/app/sources/`、`api/app/verify/` | 来源适配器、引文核对 | 技能与来源 |
| `web/` | Next.js 网页 | 网页 |
| `skill/` | SKILL.md、各家打包、测试请求集 | 技能与来源 |
| `deploy/` | `docker-compose.yml`、`Caddyfile` | 后端与连接器 |
| `.github/workflows/` | CI/CD | 后端与连接器 |
| `reports/`、`项目说明书.md` | 产品和技术文档 | 全体 |

改了别的角色负责的目录，PR 里要请那个角色评审。

## 命令

工具链：Python 3.12 + uv，Node.js 24 + pnpm，Docker。命令都在对应的目录里执行。

新建目录的人，在同一个 PR 里把这个目录的命令补进下表。

本地启动 api 后，Claude Code 通过仓库根目录的 `.mcp.json` 连接 `http://127.0.0.1:8000/mcp`，可以直接试连接器的工具。

| 目录 | 安装依赖 | 启动 | 测试 | 格式和检查 |
|---|---|---|---|---|
| `api/` | `uv sync` | `uv run uvicorn app.main:app --reload`（http://127.0.0.1:8000，接口在 `/api`，连接器在 `/mcp`） | `uv run pytest`；带覆盖率（CI 要求不低于 90%）：`uv run pytest --cov`；访问真实接口的测试：`uv run pytest -m live` | `uv run ruff format .`、`uv run ruff check .`、`uv run pyright` |
| `web/` | `pnpm install` | `pnpm dev`（http://localhost:3000） | — | `pnpm format`、`pnpm lint`、`pnpm typecheck`、`pnpm build` |

## 代码规范

- **Python**：类型注解写全；ruff 格式化和检查，pyright strict 不报错。对外的输入输出都用 Pydantic 模型。网络请求用 httpx2 的异步客户端，XML 用标准库 `xml.etree` 解析。
- **TypeScript**：开 strict；ESLint、Prettier。后端接口的类型从 OpenAPI 生成，生成的文件不手改。
- **REST 和 MCP 共用 `api/app/core/` 里的业务逻辑。** 路由层和工具层只做参数转换，不写业务。
- **测试**：pytest；外部接口用 `tests/http_mock.py`（httpx2 的模拟传输层）代替。要访问真实网络的测试标 `@pytest.mark.live`，默认不跑。
- **语言**：代码、标识符、注释、提交信息用英文；文档和面向用户的文字用中文。
- **提交信息**用 Conventional Commits：`feat:`、`fix:`、`docs:`、`test:`、`refactor:`、`chore:`。

## 工作方式

- 不直接改 `main`。一个 Issue 一个分支，分支名是「Issue 编号-简短英文描述」，例如 `12-check-paper-tool`。
- 一个 PR 只做一件事。改了接口、表结构或工具参数，在 PR 描述里写明，并请受影响的角色评审。
- 加依赖要在 PR 描述里写理由。
- 提交前在本地跑过测试和检查。
- 不提交密钥。`.env` 不进仓库，只提交 `.env.example`；不读取、不打印 `.env` 的内容。
- 同时开几个 Agent 时，每个用自己的 git worktree 和分支。
- 做完的标准：有测试，CI 通过；接口或工具变了，同步改文档和本文件；连接器的改动在至少一个真实的 Agent 里跑通过。
- 某条规则 AI 反复做错，就补进本文件。

## 写文档

- `reports/` 和 `项目说明书.md` 只写最终敲定的内容：不写修订记录和讨论过程，不和被否的方案作比较。
- 按认真做的团队项目写，不写成练手或学习项目。
- 用直白的中文，不用比喻。
