# 矿权日报 Agent(24h 面试项目)

按 MCP(Model Context Protocol)协议实现的矿业情报系统:**4 个 MCP server + 1 个 LangGraph Agent**。
输入一句话(如"给我生成一份关于 Pilbara 锂矿的今日简报"),输出 Markdown 简报:
**新闻摘要 + 储量数据 + 价格走势 + 风险提示 + 引用源清单**。

> 快速开始见 [RUN.md](RUN.md);示例简报见 [output/example/示例简报.md](output/example/示例简报.md)。

## 架构

```
用户输入 / 预设菜单(猜你想搜)
        │
        ▼
┌─────────────────────────────────────────────┐
│  Agent Client(LangGraph + DeepSeek)         │
│  agent 节点(LLM+绑定 MCP 工具)⇄ tools 节点   │
│  无工具调用 → END → 渲染 Markdown 简报       │
│  降级:AGENT_MODE=auto/llm/template 三档      │
└──────┬──────────┬──────────┬────────────────┘
  MCP  │ stdio(本地子进程)或 HTTP(容器网络)
       ▼          ▼          ▼          ▼
┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────────┐
│mining-   │ │mineral-  │ │lme-price │ │mining-rights │
│news-mcp  │ │pdf-mcp   │ │mcp       │ │mcp(第4个,加分)│
└──────────┘ └──────────┘ └──────────┘ └──────────────┘
   │             │             │             │
 数据源适配层(统一 Source 约定:source=real/demo + data_ts,TTL 缓存)
   │             │             │             │
 真实源①→②→③   三合一输入    真实源①→②→③  官方列表爬取
   │             │             │             │
 全部失败 → 内置样例(输出明确标注 ⚠️示例,演示永不空手)
```

**双传输模式**:同一份 server 代码支持 stdio(Claude Desktop / Cursor 拉子进程)与
streamable HTTP(docker 容器网络),由环境变量 `MCP_SERVER_TRANSPORT` 切换。

## 四个 MCP server 与数据源(全部实测可用)

| Server | 工具 | 数据源 |
|---|---|---|
| mining-news-mcp | `search(query, days)` `fetch_article(url)` | ① 东方财富文章搜索 API(中文,免费无 key,关键词搜索)② northernminer / im-mining RSS(英文,客户端过滤)③ 内置样例 |
| mineral-pdf-mcp | `extract_resources(pdf_url)` | 三合一:http(s) 链接下载 / 本地文件路径(可拖进对话窗口)/ `sample://pilgangoora` 内置样例。正则提取 NI 43-101 / JORC 的 Measured/Indicated/Inferred 吨位与品位,低置信度自动走 LLM 结构化抽取兜底 |
| lme-price-mcp | `get_price(commodity, date)` `get_trend(commodity, days)` | ① 新浪财经行情 API:国内期货实时+历史日K(沪铜/镍/锌/碳酸锂,碳酸锂 2023 年至今全量真实数据)② 新浪外盘:LME 伦铜/镍/锌/铝实时美元价 ③ westmetall:LME 官方结算价+官方库存 ④ 确定性模拟兜底 |
| mining-rights-mcp | `search_mining_rights(keyword, days)` | 自然资源部矿业权市场(ky.mnr.gov.cn):探矿权/采矿权出让公告、出让结果官方公示,跨频道抓取+关键词过滤(题目要求"至少 3 个",第 4 个直击"矿权日报"主题) |

### 数据源实测验证清单(2026-09-04,国内网络环境)

| 源 | 实测结果 |
|---|---|
| 东方财富搜索 | ✅ "Pilbara" 18 篇、"锂矿" 2909 篇真实命中 |
| northernminer / im-mining RSS | ✅ 直连,真实 XML 流 |
| 新浪行情(国内 nf_ / LME hf_) | ✅ 沪铜 ¥109,230、碳酸锂 ¥141,940、伦铜 $14,386(实时) |
| 新浪日 K | ✅ 碳酸锂 759 根(2023-07 至今)、沪铜自 2005 年 |
| westmetall | ✅ LME 官方结算价全表 + 官方库存(铜 234,650 吨,+800) |
| ky.mnr.gov.cn 矿权市场 | ✅ 每页 50 条当日真实公告(新疆铜矿探矿权挂牌出让等) |
| ❌ Bing News RSS | 国内重定向丢参,已弃用 |
| ❌ SEDAR+(加拿大 NI 43-101 官方系统) | 403 被墙,改走矿业公司官网 |

## 技术栈

- **语言/包管理**:Python 3.12 + uv(依赖与缓存全部落在项目内,零系统污染)
- **MCP**:fastmcp 4.x(官方 SDK 封装),4 个 server 同一代码双传输
- **Agent 编排**:LangGraph(StateGraph:agent ⇄ tools 循环,轮次上限防失控)
- **LLM**:DeepSeek `deepseek-chat`(langchain-openai 接入,OpenAI 兼容,换任何模型只改 .env)
- **MCP↔LangChain 桥接**:自写 ~100 行(`agent/bridge.py`):stdio 子进程生命周期管理、
  `list_tools()` 动态发现、JSON Schema→pydantic 动态建模、调用日志(引用源自动聚合)
- **PDF**:pypdf;**HTTP**:httpx(统一超时/UA);**缓存**:标准库 sqlite3(新闻 TTL、westmetall 快照累积)
- **无数据库、无前端**(Claude Desktop / Cursor 即 MCP 天然前端;CLI 预设菜单交互)

## 目录结构

```
├── servers/          # 4 个 MCP server(每题一个文件,stdio/HTTP 双启动)
├── agent/            # LangGraph 编排:main(菜单+CLI)/ graph / bridge / template_agent / prompts / render
├── shared/           # config(.env 零依赖加载)/ http_client / cache(sqlite)/ sources/(数据源适配器)/ sample_data(内置样例)
├── scripts/          # gen_mcp_config.py:自动探测 python 路径生成客户端配置
├── tests/            # pytest 冒烟测试
├── mcp-config.json   # 占位符版({{PYTHON_PATH}}/{{PROJECT_ROOT}},RUN.md 两步替换)
├── Dockerfile + docker-compose.yml   # 一条命令容器化(本地无需 build)
├── RUN.md            # 5 分钟验证指南(Windows/macOS 双版本)
└── output/           # 生成的简报(含 example/ 示例)
```

## 设计决策(面试速答)

| 决策 | 为什么 |
|---|---|
| 4 个 server 而非 3 个 | 题目"至少 3 个";第 4 个矿权公示直击"矿权日报"主题,数据源为自然资源部官方 |
| 双传输(stdio + HTTP) | Claude Desktop/Cursor 只支持 stdio;docker-compose 容器间必须走 HTTP;fastmcp 同一代码切换 |
| 自写 MCP↔LangChain 桥接 | 掌控 stdio 子进程生命周期;JSON Schema→pydantic 动态建模;少一个依赖;面试可逐行讲清"编排框架如何接 MCP" |
| LangGraph 而非硬编码流程 | 公司指定;图结构可扩展(可加人工审核/并行抓取节点);轮次上限控制成本 |
| 四层降级链 + 数据标注 | 每个 server 真实源失败自动降级;输出 source=real/demo/simulated 强制标注,演示永不空手且诚实 |
| LME 历史走势 | LME 官方历史数据付费,免费源只有官方结算价(westmetall 转载);每日运行自动累积快照,不足时以确定性模拟补全并标注 |
| 价格模拟 | 按(品种,日期)播种的随机游走,同一日期结果固定可复现;仅作兜底,基准价取自实测真实行情 |
| 无数据库 | 无状态聚合管线;新闻去重/快照累积用标准库 sqlite3 文件,零外部服务 |
| 环境零新增 | 依赖全部落项目内(.venv/.uv-cache),Docker 只写不 build,面试官机器零污染 |

## 验收用例

```bash
uv run python -m agent.main --query "给我生成一份关于 Pilbara 锂矿的今日简报"   # LLM 模式(需 key)
AGENT_MODE=template uv run python -m agent.main --query "给我生成一份关于 Pilbara 锂矿的今日简报"  # 模板模式(零依赖)
uv run pytest tests/ -v                                                                                 # 冒烟测试
```

输出:`output/简报-YYYYMMDD-HHMMSS.md`(新闻摘要带来源链接 + 分级储量表 + 价格走势
(期初/期末/最高/最低/涨跌幅)+ 事实型风险提示 + 引用源清单)。
