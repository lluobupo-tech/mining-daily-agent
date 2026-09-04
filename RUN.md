# RUN.md —— 5 分钟跑起来(面试官专用)

> 目标:拿到本项目后 5 分钟内,① 看到 Agent 生成 Markdown 简报;② 把 4 个 MCP server 接入 Claude Desktop / Cursor 并成功调用。

## 🛠️ 前置条件

- Python 3.10+(建议装有 [uv](https://docs.astral.sh/uv/),非必需)
- Claude Desktop 或 Cursor(二选一,仅"方式二"需要)
- **无需申请任何 API Key**:三个新闻/价格/矿权数据源全部免费
- DeepSeek key 可选:LLM 模式需要;无 key 自动走模板模式,功能完整

---

## 方式一:本机运行 Agent(1 分钟)

```bash
# 1. 进入项目根目录
cd 本项目目录

# 2. 安装依赖(有 uv:全部落在项目内 .venv 与 .uv-cache,零系统污染)
uv sync
#    没有 uv 则用 pip:
#    pip install -r requirements.txt

# 3. 运行 Agent(交互菜单:回车即生成 Pilbara 锂矿简报)
uv run python -m agent.main
#    或直接一条命令(pip 用户把 uv run 去掉即可):
uv run python -m agent.main --query "给我生成一份关于 Pilbara 锂矿的今日简报"
```

**成功标志**:终端出现 4 个 MCP server 的启动日志与 🔨 工具调用记录,最后打印
`✅ 简报已生成: ...\output\简报-YYYYMMDD-HHMMSS.md`,打开即见四块内容
(新闻摘要 / 储量数据 / 价格走势 / 风险提示)+ 引用源清单。

> 模式说明:`AGENT_MODE=auto`(默认,LLM 失败自动降级模板)/ `llm` / `template`;
> 也可 `--mode` 参数指定。DeepSeek key 在 `.env`(参考 `.env.example`)。

---

## 方式二:接入 Claude Desktop / Cursor(2 分钟)

### 第一步:拿到两个真实路径(约 30 秒)

**Windows(PowerShell)**,分别执行并复制输出:

```powershell
where python          # Python 绝对路径
(Get-Location).Path  # 项目根绝对路径(先 cd 到项目目录)
```

**macOS / Linux**,分别执行并复制输出:

```bash
which python3
pwd
```

### 第二步:替换 mcp-config.json 中的两个占位符(约 1 分钟)

用编辑器打开项目根目录的 `mcp-config.json`:

- 将 **所有** `{{PYTHON_PATH}}` 替换为第一步的 Python 路径
- 将 **所有** `{{PROJECT_ROOT}}` 替换为第一步的项目根路径

也可以跳过手工替换,直接运行自动生成脚本(推荐):

```bash
python scripts/gen_mcp_config.py    # 生成 mcp-config.local.json,路径已填好
```

### 第三步:把配置复制进客户端(约 30 秒,二选一)

**选项 A —— Claude Desktop**:

1. 打开配置文件:
   - Windows:`%APPDATA%\Claude\claude_desktop_config.json`
   - macOS:`~/Library/Application Support/Claude/claude_desktop_config.json`
2. 把改好的 `mcp-config.json`(或 `mcp-config.local.json`)中 **整个 `mcpServers` 内容**复制进去(如已有其他配置,逗号分隔合并)
3. **完全退出并重新打开** Claude Desktop

**选项 B —— Cursor**:

1. 项目根目录新建 `.cursor` 文件夹,里面新建 `mcp.json`
2. 把改好的配置中 **整个 `mcpServers` 内容**复制进 `mcp.json`
3. 重启 Cursor

### 第四步:终极验证(30 秒)

在对话框输入(直接复制):

> 帮我查一下沪铜价格,再搜最近 3 天的锂矿新闻,最后解析 sample://pilgangoora 的储量。

**成功标志**:AI 回复中出现 ① 沪铜价格(¥/吨,国内期货真实行情)② 锂矿新闻标题列表
③ Pilgangoora 的 Measured/Indicated/Inferred 储量表;调用过程中能看到
🔨 工具调用提示(Claude Desktop 显示工具调用,名称如 `lme-price-mcp`)。

---

## 方式三:Docker 一条命令(可选,2 分钟)

```bash
# 模板模式(不需要任何 key,面试官零配置验证):
docker compose up --build agent

# LLM 模式:先 cp .env.example .env 并填入 DeepSeek key,再:
docker compose up --build agent
```

4 个 MCP server 以 HTTP 模式跑在容器网络内(端口 8101~8104),agent 容器连接后
生成简报,输出挂载到宿主机 `./output/`。

---

## 常见问题(FAQ)

| 问题 | 解决 |
|---|---|
| pip 安装慢 | `pip install -i https://mirrors.aliyun.com/pypi/simple/ -r requirements.txt` |
| uv 下载慢 | `UV_DEFAULT_INDEX=https://mirrors.aliyun.com/pypi/simple/ uv sync` |
| Docker 拉基础镜像慢 | 配置 registry 镜像加速(如阿里云容器镜像加速器) |
| 项目目录含中文 | 本项目 compose 已显式声明 `name`,无需处理 |
| 断网/数据源不可用 | 所有数据自动降级为内置样例,输出标注 ⚠️示例,演示不中断 |
| 新闻为什么中英混合 | 中文走东方财富搜索,英文走国际矿业媒体 RSS,双语互补 |
| LME 为什么没有历史走势 | LME 官方历史数据付费,免费源仅有官方结算价快照(每日运行自动累积);国内品种历史为真实日 K |
| 提示 LLM 模式失败 | 无 key 或网络异常,已自动降级模板模式(正常行为) |
