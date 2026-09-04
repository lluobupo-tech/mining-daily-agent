# 矿权日报 Agent —— 单镜像,4 个服务(server×4 / agent)通过 compose 的 command 区分
FROM python:3.12-slim

# 国内构建建议配置镜像加速,如:
#   RUN sed -i 's/deb.debian.org/mirrors.aliyun.com/g' /etc/apt/sources.list.d/debian.sources
WORKDIR /app

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY servers ./servers
COPY shared ./shared
COPY agent ./agent
COPY .env.example ./

# MCP server 以 HTTP 模式对外服务(compose 网络内互相调用)
ENV MCP_SERVER_TRANSPORT=http
ENV PYTHONUNBUFFERED=1

CMD ["python", "-m", "servers.news_server"]
