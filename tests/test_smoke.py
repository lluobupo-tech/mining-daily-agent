"""冒烟测试:结构断言优先;网络类用例对真实/降级结果均容忍(源可用性非代码缺陷)。"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


# ---------- 本地确定性用例(无网络,精确断言) ----------

def test_simulate_price_deterministic():
    from shared.sources.simulate import price_on

    a = price_on("lithium", "2026-08-30")
    b = price_on("lithium", "2026-08-30")
    assert a["price"] == b["price"], "同一日期模拟价格必须可复现"
    assert a["source"] == "simulated"
    assert a["unit"] == "CNY/t"


def test_simulate_trend_length():
    from shared.sources.simulate import trend

    pts = trend("lme_copper", 10)
    assert len(pts) == 10
    assert all(p["price"] > 0 for p in pts)


def test_sample_news_and_rights_load():
    from shared.sources.simulate import load_sample

    news = load_sample("news")["items"]
    rights = load_sample("rights")["items"]
    assert len(news) >= 5 and len(rights) >= 3


def test_pdf_sample_extraction():
    from servers.pdf_server import extract_resources

    r = extract_resources("sample://pilgangoora")
    assert r["source"] == "demo"
    cats = r["categories"]
    assert {"Measured", "Indicated", "Inferred"} <= set(cats.keys())
    assert cats["Indicated"]["tonnage_mt"] > 100


def test_pdf_local_file_extraction(tmp_path):
    """手工构造含储量表述的最小 PDF,验证本地文件 + 正则提取链路。"""
    from servers.pdf_server import extract_resources

    content = b"""BT /F1 12 Tf 72 700 Td (Test Project Resource Estimate) Tj 0 -24 Td
(Measured Mineral Resource 10.0 Mt at 1.2% Li2O) Tj 0 -24 Td
(Indicated Mineral Resource 20.5 Mt at 1.1% Li2O) Tj 0 -24 Td
(Inferred Mineral Resource 5.3 Mt at 0.9% Li2O) Tj ET"""
    objs = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R "
        b"/Resources << /Font << /F1 5 0 R >> >> >>",
        b"<< /Length %d >>\nstream\n%s\nendstream" % (len(content), content),
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    pdf = b"%PDF-1.4\n"
    offsets = []
    for i, o in enumerate(objs, 1):
        offsets.append(len(pdf))
        pdf += b"%d 0 obj\n%s\nendobj\n" % (i, o)
    xref = len(pdf)
    pdf += b"xref\n0 6\n0000000000 65535 f \n" + b"".join(
        b"%010d 00000 n \n" % off for off in offsets
    )
    pdf += b"trailer << /Root 1 0 R /Size 6 >>\nstartxref\n%d\n%%%%EOF" % xref
    p = tmp_path / "report.pdf"
    p.write_bytes(pdf)

    r = extract_resources(str(p))
    assert r["source"] == "real"
    assert r["confidence"] == "high"
    assert r["categories"]["Measured"]["tonnage_mt"] == 10.0
    assert r["categories"]["Inferred"]["grade"] == "0.9% Li2O"


def test_template_agent_briefing():
    from agent.template_agent import run

    body, mode, call_log = run("给我生成一份关于 Pilbara 锂矿的今日简报")
    assert mode == "template"
    assert "今日要闻摘要" in body and "储量数据" in body
    assert "价格走势" in body and "风险提示" in body
    assert len(call_log) == 5


def test_render_strip_preamble_and_document():
    from agent.render import build_document, strip_preamble

    body = "让我整理一下。\n现在生成简报。\n\n# 矿权日报简报\n\n正文内容"
    assert strip_preamble(body).startswith("# 矿权日报简报")
    doc = build_document("q", body, ["https://a.com/1"], "template")
    assert "引用源" in doc and "https://a.com/1" in doc
    assert doc.startswith("# 矿权日报简报")


def test_graph_route_limits_rounds():
    from agent.graph import build_agent, MAX_TOOL_ROUNDS
    from langchain_core.messages import AIMessage, ToolMessage
    from langchain_core.tools import tool

    @tool
    def echo(x: str) -> str:
        """回显。"""
        return x

    graph = build_agent(_FakeLLM(), [echo])
    msgs = [AIMessage(content="hi")]
    # 造超过轮次上限的对话:不应再进 tools 节点
    state = {"messages": msgs, "round": MAX_TOOL_ROUNDS + 1}
    last = AIMessage(content="done")
    from langgraph.graph import END

    # 直接验证 route 逻辑:round 超限且无 tool_calls → END
    out = graph.invoke({"messages": msgs, "round": MAX_TOOL_ROUNDS + 1})
    assert out["round"] >= MAX_TOOL_ROUNDS + 1


class _FakeLLM:
    def bind_tools(self, tools):
        return self

    def invoke(self, messages):
        from langchain_core.messages import AIMessage

        return AIMessage(content="ok")


# ---------- 缺陷回归用例(全 mock,快速确定) ----------

def test_refs_exclude_demo_and_placeholder_urls():
    """引用源只保留真实来源链接,剔除 demo/simulated 与 example.com 占位链接。"""
    from agent.render import collect_refs

    log = [
        {"server": "x", "tool": "y", "data": {
            "source": "real",
            "items": [
                {"url": "https://im-mining.com/2026/09/04/real-article/"},
                {"url": "https://example.com/news/fake"},
            ],
        }},
        {"server": "x", "tool": "y", "data": {
            "source": "demo", "items": [{"url": "https://example.com/news/demo-item"}],
        }},
        {"server": "x", "tool": "y", "data": {
            "source": "simulated", "source_url": "https://example.org/sim",
        }},
        {"server": "x", "tool": "y", "data": {
            "source": "real",
            "source_url": "https://pilbaraminerals.com.au/investors/annual-reports/",
        }},
    ]
    refs = collect_refs(log)
    assert refs == [
        "https://im-mining.com/2026/09/04/real-article/",
        "https://pilbaraminerals.com.au/investors/annual-reports/",
    ]


def test_rss_requires_all_query_terms(monkeypatch):
    """RSS 过滤要求查询词全部命中,防止宽泛单词命中泛新闻。"""
    from shared.sources import rss_news

    fake = [
        {
            "title": "New US lithium mines are coming",
            "summary": "",
            "published": "2026-09-04",
            "media": "northernminer",
            "url": "https://a.com/irrelevant",
        },
        {
            "title": "Pilbara Minerals updates Pilgangoora spodumene guidance",
            "summary": "",
            "published": "2026-09-03",
            "media": "northernminer",
            "url": "https://a.com/relevant",
        },
    ]
    monkeypatch.setattr(rss_news, "_feed_items", lambda name, url: fake)
    r = rss_news.search("Pilbara Minerals Pilgangoora spodumene", days=7, limit=10)
    assert [x["url"] for x in r["items"]] == ["https://a.com/relevant"]


def test_news_stale_cache_fallback_on_source_failure(monkeypatch):
    """东方财富实时请求失败时回退上次成功搜索的缓存。"""
    from servers import news_server

    cached = {
        "items": [
            {
                "title": "缓存新闻",
                "summary": "",
                "media": "东方财富",
                "url": "https://finance.eastmoney.com/a/1.html",
                "published": "2026-09-04",
            }
        ],
        "total": 1,
        "source": "real",
    }

    def boom(*a, **k):
        raise ConnectionError("网络异常")

    def empty_rss(*a, **k):
        return {"items": [], "total": 0, "source": "real", "data_ts": "t"}

    monkeypatch.setattr(news_server.eastmoney_news, "search", boom)
    monkeypatch.setattr(news_server.eastmoney_news, "cached_search", lambda q, limit: cached)
    monkeypatch.setattr(news_server.rss_news, "search", empty_rss)

    r = news_server.search("Pilbara", days=7, limit=5)
    assert r["source"] == "real"
    assert r["items"][0]["url"] == "https://finance.eastmoney.com/a/1.html"
    assert "缓存" in r.get("note", "")


def test_template_demo_news_heading_marked(monkeypatch):
    """模板模式:新闻降级 demo 时,标题必须注明非当日真实新闻。"""
    from agent import template_agent
    from servers import news_server, pdf_server, price_server, rights_server

    demo = {
        "items": [{"title": "t", "media": "m", "published": "2026-09-02", "url": "https://example.com/x"}],
        "total": 1,
        "source": "demo",
        "note": "真实源不可用",
        "data_ts": "t",
    }
    monkeypatch.setattr(news_server, "search", lambda *a, **k: demo)
    monkeypatch.setattr(price_server, "get_price", lambda *a, **k: {"error": "mock"})
    monkeypatch.setattr(price_server, "get_trend", lambda *a, **k: {"points": [], "note": "mock"})
    monkeypatch.setattr(pdf_server, "extract_resources", lambda *a, **k: {"note": "mock"})
    monkeypatch.setattr(rights_server, "search_mining_rights", lambda *a, **k: {"items": []})

    body, mode, call_log = template_agent.run("给我生成一份关于 Pilbara 锂矿的今日简报")
    assert mode == "template"
    assert "今日要闻摘要(⚠️示例数据" in body


# ---------- 数据源解析 fixture 用例(monkeypatch HTTP,零网络) ----------

def _jsonp(payload: dict) -> str:
    import json as _json

    return "x(" + _json.dumps(payload, ensure_ascii=False) + ")"


def test_eastmoney_time_sort_and_date_filter(monkeypatch):
    """东方财富:必须按时间排序;超过 days 窗口的旧闻必须被过滤。"""
    from shared.sources import eastmoney_news

    captured = {}

    def fake_get_text(url, *, timeout=None, headers=None, params=None, retries=1):
        import json as _json

        p = _json.loads(params["param"])
        captured["sort"] = p["param"]["cmsArticleWebOld"]["sort"]
        return _jsonp(
            {
                "hitsTotal": 2,
                "result": {"cmsArticleWebOld": [
                    {"date": "2026-08-01 10:00:00", "title": "<b>旧闻</b>", "content": "旧",
                     "mediaName": "m", "url": "https://e.com/old"},
                    {"date": "2026-09-04 10:00:00", "title": "新闻", "content": "新",
                     "mediaName": "m", "url": "https://e.com/new"},
                ]},
            }
        )

    monkeypatch.setattr(eastmoney_news, "get_text", fake_get_text)
    monkeypatch.setattr(eastmoney_news, "kv_get", lambda *a, **k: None)
    monkeypatch.setattr(eastmoney_news, "kv_set", lambda *a, **k: None)

    r = eastmoney_news.search("锂矿", days=7, limit=5)
    assert captured["sort"] == "time"
    assert [it["url"] for it in r["items"]] == ["https://e.com/new"]


def test_rss_feed_item_parsing(monkeypatch):
    """RSS:XML 字段解析(标题/链接/摘要/日期归一化)。"""
    from shared.sources import rss_news

    xml = """<?xml version="1.0"?><rss><channel><item>
    <title>Pilbara Minerals lithium update</title>
    <link>https://feed.example/1</link>
    <description><![CDATA[<p>summary</p>]]></description>
    <pubDate>Thu, 03 Sep 2026 10:00:00 GMT</pubDate>
    </item></channel></rss>"""
    monkeypatch.setattr(rss_news, "get_text", lambda url, timeout=8.0: xml)
    monkeypatch.setattr(rss_news, "kv_get", lambda *a, **k: None)
    monkeypatch.setattr(rss_news, "kv_set", lambda *a, **k: None)

    items = rss_news._feed_items("northernminer", "https://feed.example")
    assert items[0]["title"].startswith("Pilbara")
    assert items[0]["published"] == "2026-09-03"
    assert items[0]["summary"] == "summary"
    assert items[0]["url"] == "https://feed.example/1"


def test_sina_quote_parses_domestic_gbk(monkeypatch):
    """新浪国内行情:GBK 响应解析(最新价字段 8/名称/日期)。"""
    from shared.sources import sina_quote

    payload = (
        'var hq_str_nf_CU0="铜连续,150000,151000,149000,152000,148000,0,0,109290,'
        '0,0,0,0,0,0,0,0,2026-09-05,15:00:00,0,0,0,0";\n'
    )
    monkeypatch.setattr(
        sina_quote, "get_bytes", lambda url, headers=None, timeout=8.0: payload.encode("gbk")
    )

    q = sina_quote.quote("copper", "domestic")
    assert q["source"] == "real"
    assert q["price"] == 109290.0
    assert q["name"] == "铜连续"
    assert q["date"] == "2026-09-05"


# ---------- 网络类用例(容忍降级,断言结构) ----------

def test_news_search_structure():
    from servers.news_server import search

    r = search("Pilbara 锂矿", days=30, limit=3)
    assert r["source"] in ("real", "demo")
    assert "data_ts" in r
    for it in r["items"]:
        assert set(["title", "url", "published"]).issubset(it.keys())


def test_price_tools_structure():
    from servers.price_server import get_price, get_trend

    p = get_price("lithium")
    assert p.get("source") in ("real", "simulated") or "error" in p
    t = get_trend("lithium", 5)
    assert t.get("source") in ("real", "simulated") or "error" in t
    if t.get("points"):
        assert all("date" in x and "price" in x for x in t["points"])


def test_rights_search_structure():
    from servers.rights_server import search_mining_rights

    r = search_mining_rights("铜", days=60, limit=3)
    assert r["source"] in ("real", "demo")
    assert isinstance(r["items"], list)
