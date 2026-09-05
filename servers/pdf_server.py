"""mineral-pdf-mcp —— NI 43-101 / JORC 储量报告解析。

三合一输入(自动识别):
- http(s)://...   下载 PDF 后解析(落盘缓存 data/cache/pdfs/)
- 本地文件路径    直接解析(支持拖进 Claude Desktop / Cursor 后传路径)
- sample://名字   内置样例(sample://pilgangoora / wodgina / kathleen_valley / greenbushes)

两阶段提取:
1. 正则:pypdf 抽文本 → 识别 Measured/Indicated/Inferred + 吨位 + 品位模式
2. LLM 兜底:正则置信度低且配置了 DEEPSEEK_API_KEY 时,文本片段送 DeepSeek 结构化抽取
非 NI 43-101/JORC 报告会返回明确提示,不会静默失败。
"""
from __future__ import annotations

import sys
from pathlib import Path

# stdio 子进程模式下 fastmcp 以脚本方式拉起本文件,需把项目根加入 sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import hashlib
import io
import json
import re
from datetime import datetime

from fastmcp import FastMCP
from pypdf import PdfReader

from shared.config import CACHE_DIR, DEEPSEEK_API_KEY
from shared.http_client import get_bytes
from shared.server_runner import run_server
from shared.sources.simulate import load_sample

mcp = FastMCP("mineral-pdf-mcp")

PDF_CACHE_DIR = CACHE_DIR / "pdfs"
PDF_CACHE_DIR.mkdir(parents=True, exist_ok=True)

# 资源分级 → 吨位 → 品位的正则模式(NI 43-101 / JORC 通用表述)
_CAT_RE = r"\b(Measured|Indicated|Inferred)\b"
_TON_RE = r"(\d[\d,\.]*)\s*(Mt|kt|t)\b"
_GRADE_RE = r"([\d\.]+)\s*%\s*(Li2?O|[A-Za-z]{1,8})"


def _extract_text(data: bytes) -> str:
    reader = PdfReader(io.BytesIO(data))
    parts = []
    for page in reader.pages:
        try:
            parts.append(page.extract_text() or "")
        except Exception:  # noqa: BLE001
            continue
    return "\n".join(parts)


def _regex_extract(text: str) -> tuple[dict, str]:
    """正则提取,返回 (categories, confidence)。"""
    found: dict[str, dict] = {}
    for m in re.finditer(_CAT_RE, text):
        cat = m.group(1)
        window = text[m.start() : m.start() + 400]
        ton = re.search(_TON_RE, window)
        grade = re.search(_GRADE_RE, window)
        if ton and grade:
            value = float(ton.group(1).replace(",", ""))
            unit = ton.group(2)
            # Mt/kt/t 统一为 Mt
            value_mt = value if unit == "Mt" else (value / 1000 if unit == "kt" else value / 1e6)
            entry = {
                "tonnage_mt": round(value_mt, 3),
                "grade": f"{grade.group(1)}% {grade.group(2)}",
            }
            # 同类取吨位最大的记录(通常为总资源行)
            if cat not in found or value_mt > found[cat]["tonnage_mt"]:
                found[cat] = entry
    n = len(found)
    confidence = "high" if n >= 3 else ("medium" if n >= 1 else "none")
    return found, confidence


def _llm_extract(text: str) -> tuple[dict, str]:
    """LLM 兜底:DeepSeek 结构化抽取。失败抛异常。"""
    from langchain_openai import ChatOpenAI

    from shared.config import DEEPSEEK_BASE_URL, DEEPSEEK_MODEL

    llm = ChatOpenAI(
        model=DEEPSEEK_MODEL,
        base_url=DEEPSEEK_BASE_URL,
        api_key=DEEPSEEK_API_KEY,
        temperature=0,
        request_timeout=60,
        # JSON 输出模式:从协议层保证返回纯 JSON,取代脆弱的正则抠 JSON
        model_kwargs={"response_format": {"type": "json_object"}},
    )
    prompt = (
        "以下文本节选自矿业技术报告(NI 43-101 / JORC)。"
        "请提取矿产资源量分级数据,只输出 JSON,格式:\n"
        '{"Measured": {"tonnage_mt": 数字, "grade": "x% Li2O"}, '
        '"Indicated": {...}, "Inferred": {...}}\n'
        "吨位单位统一为 Mt(百万吨);没有的级别省略;找不到任何数据输出 {}。\n\n"
        f"文本:\n{text[:30000]}"
    )
    resp = llm.invoke(prompt)
    content = str(resp.content).strip()
    # 优先直接解析;供应商不支持 JSON 模式时回退到正则提取(兼容层)
    try:
        data = json.loads(content)
    except json.JSONDecodeError:
        m = re.search(r"\{.*\}", content, re.S)
        if not m:
            raise ValueError(f"LLM 未返回 JSON: {content[:100]}")
        data = json.loads(m.group(0))
    if not isinstance(data, dict):
        raise ValueError(f"LLM 返回非对象: {content[:100]}")
    confidence = "medium" if data else "none"
    return data, confidence


def _format(categories: dict, meta: dict) -> dict:
    return {
        **meta,
        "categories": categories or {},
        "standard": "NI 43-101 / JORC",
        "source": "real" if meta.get("_source") != "sample" else "demo",
        "data_ts": datetime.now().isoformat(timespec="seconds"),
    }


@mcp.tool
def extract_resources(pdf_url: str) -> dict:
    """从 PDF 提取矿产资源量(Measured / Indicated / Inferred 的吨位与品位)。

    Args:
        pdf_url: 三选一 ——
          ① 远程 PDF 链接(http/https)
          ② 本地文件绝对路径(拖文件进 Claude Desktop / Cursor 后传路径)
          ③ 内置样例: sample://pilgangoora | sample://wodgina | sample://kathleen_valley | sample://greenbushes

    Returns:
        dict: {project, company, location, commodity, standard, categories, confidence,
               extraction_method, source_url, source, data_ts, note?}
        source: real=真实解析 / demo=内置样例。confidence: high/medium/low/none。
        非储量报告会返回明确提示(不会静默成功)。
    """
    sample_m = re.fullmatch(r"sample://(\w+)", (pdf_url or "").strip())
    if sample_m:
        try:
            p = load_sample("resources")["projects"][sample_m.group(1)]
            return {
                "project": p["name"],
                "company": p["company"],
                "location": p["location"],
                "commodity": p["commodity"],
                "standard": p.get("standard", ""),
                "categories": p["categories"],
                "reserve_note": p.get("reserve_note", ""),
                "confidence": "high",
                "extraction_method": "sample",
                "source_url": p.get("source_url", ""),
                "source": "demo",
                "data_ts": datetime.now().isoformat(timespec="seconds"),
                "note": "内置样例数据(取自公司公开年报近似值,演示兜底)",
            }
        except KeyError:
            return {
                "error": f"未知样例: sample://{sample_m.group(1)}",
                "available": list(load_sample("resources")["projects"].keys()),
                "data_ts": datetime.now().isoformat(timespec="seconds"),
            }

    # ① 远程下载 / ② 本地文件
    src_url = ""
    try:
        if pdf_url.strip().startswith(("http://", "https://")):
            src_url = pdf_url.strip()
            cached = PDF_CACHE_DIR / f"{hashlib.md5(src_url.encode()).hexdigest()[:16]}.pdf"
            if cached.exists() and cached.stat().st_size > 0:
                data = cached.read_bytes()
            else:
                data = get_bytes(src_url, timeout=25.0)
                cached.write_bytes(data)
        else:
            path = Path(pdf_url.strip())
            if not path.is_file():
                return {
                    "error": f"文件不存在: {pdf_url}(请提供 http 链接、本地绝对路径或 sample://xxx)",
                    "data_ts": datetime.now().isoformat(timespec="seconds"),
                }
            data = path.read_bytes()
    except Exception as e:  # noqa: BLE001
        return {
            "error": f"PDF 获取失败: {type(e).__name__}: {e}",
            "data_ts": datetime.now().isoformat(timespec="seconds"),
        }

    # 解析
    try:
        text = _extract_text(data)
    except Exception as e:  # noqa: BLE001
        return {
            "error": f"PDF 解析失败(文件可能损坏或为扫描版): {e}",
            "data_ts": datetime.now().isoformat(timespec="seconds"),
        }

    meta = {
        "project": "",
        "company": "",
        "location": "",
        "commodity": "",
        "source_url": src_url,
    }
    categories, confidence = _regex_extract(text)
    method = "regex"

    if confidence in ("none", "low") and DEEPSEEK_API_KEY:
        try:
            llm_cats, llm_conf = _llm_extract(text)
            if llm_conf != "none" and len(llm_cats) >= len(categories):
                categories, confidence, method = llm_cats, llm_conf, "llm"
        except Exception:  # noqa: BLE001
            pass

    if not categories:
        return {
            **meta,
            "categories": {},
            "confidence": "none",
            "extraction_method": method,
            "standard": "",
            "source": "real",
            "data_ts": datetime.now().isoformat(timespec="seconds"),
            "note": "未在该 PDF 中识别到 NI 43-101/JORC 格式的储量数据(文件可能是新闻稿、财报或其他类型文档)",
        }

    return {
        **meta,
        "categories": categories,
        "confidence": confidence,
        "extraction_method": method,
        "standard": "NI 43-101 / JORC",
        "source": "real",
        "data_ts": datetime.now().isoformat(timespec="seconds"),
    }


if __name__ == "__main__":
    run_server(mcp, default_port=8102)
