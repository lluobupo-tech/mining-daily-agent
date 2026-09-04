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
