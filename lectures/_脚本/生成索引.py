# -*- coding: utf-8 -*-
"""生成讲座总索引 index.html

扫描 BASE 下每个讲座文件夹，按「角色」归类文件，生成可打印的索引页。

设计要点
--------
1. 日期 / 标题：优先读 HTML <head> 里的元数据注释
       <!-- lecture-date: YYYY-MM-DD | lecture-title: … | lecture-title-en: … -->
   缺省回退到文件夹名（支持 YYYY-MM-DD_主题 形式）。
2. 友好名称：优先读每个 HTML 的 <title>，其次 <meta name="description"> 作为说明。
3. 图片版折叠：同一文件夹下的多张图片只出一条记录，显示张数（避免 25 张图刷屏）。
4. index.html 是本脚本的**产物**，请勿手改；改样式/排版请改本文件。

用法
----
    python "大学\\lectures\\_脚本\\生成索引.py"
    powershell -File "…\\生成索引.ps1"        # 同目录的 .ps1 只是包装器
"""
import html
import os
import re
from datetime import datetime

# 本脚本位于 <资料库根>/_脚本/，所以往上一级就是资料库根目录。
# 这样整套资料库可以整体移动、复制或克隆到任何路径而不必改代码。
BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

DOC_EXT = {".html", ".htm", ".pdf", ".docx", ".pptx", ".md", ".tex"}
IMG_EXT = {".png", ".jpg", ".jpeg", ".webp", ".gif"}
CODE_EXT = {".py", ".ps1", ".js", ".json", ".csv", ".xlsx"}

# 角色 → 排序权重（同时决定表格里的显示顺序）
KIND_ORDER = {
    "正式版": 0,
    "讲义": 1,
    "预习": 2,
    "提问卡": 3,
    "总结": 4,
    "图片版": 5,
    "附件": 6,
    "资料": 7,
}

DESC_LIMIT = 108


# --------------------------------------------------------------------------
# 读取元数据
# --------------------------------------------------------------------------
def read_head(path):
    """返回 {date, title, title_en, tag, desc}；读不到的部分为空。"""
    try:
        with open(path, "r", encoding="utf-8", errors="ignore") as fh:
            head = fh.read(9000)
    except OSError:
        return {}

    out = {}
    m = re.search(r"lecture-date:\s*([0-9]{4}-[0-9]{2}-[0-9]{2})", head)
    if m:
        out["date"] = m.group(1)
    m = re.search(r"lecture-title:\s*([^|]+?)\s*(?:\||-->)", head)
    if m:
        out["title"] = m.group(1).strip()
    m = re.search(r"lecture-title-en:\s*([^|]+?)\s*(?:\||-->)", head)
    if m:
        out["title_en"] = m.group(1).strip()
    m = re.search(r"<title>(.*?)</title>", head, re.S | re.I)
    if m:
        out["tag"] = re.sub(r"\s+", " ", m.group(1)).strip()
    m = re.search(r'<meta\s+name=["\']description["\']\s+content=["\'](.*?)["\']', head, re.S | re.I)
    if m:
        out["desc"] = re.sub(r"\s+", " ", m.group(1)).strip()
    return out


def clip(text, limit=DESC_LIMIT):
    text = (text or "").strip()
    return text if len(text) <= limit else text[: limit - 1] + "…"


def classify(name):
    """按文件名判断角色。"""
    stem, ext = os.path.splitext(name)
    ext = ext.lower()
    if ext in IMG_EXT:
        return "图片版"
    if ext in CODE_EXT:
        return "附件"
    if re.search(r"提问|问题卡|追问", stem):
        return "提问卡"
    if re.search(r"预习|primer", stem, re.I):
        return "预习"
    if re.search(r"总结|复盘|回顾", stem):
        return "总结"
    if re.match(r"^A\d", stem, re.I):
        return "讲义"
    if re.search(r"正式版|讲座笔记|笔记", stem):
        return "正式版"
    return "资料"


def human_size(n):
    if n < 1024:
        return "{} B".format(n)
    if n < 1024 * 1024:
        return "{:.0f} KB".format(n / 1024)
    return "{:.1f} MB".format(n / 1024 / 1024)


# --------------------------------------------------------------------------
# 扫描
# --------------------------------------------------------------------------
def scan_lecture(folder):
    """返回 (meta, rows, counters)。rows 已按角色排序。"""
    meta = {}
    docs, imgs, codes = [], [], []

    for root, dirs, names in os.walk(folder):
        dirs.sort()
        for n in sorted(names):
            ext = os.path.splitext(n)[1].lower()
            full = os.path.join(root, n)
            rel = os.path.relpath(full, BASE).replace("\\", "/")
            size = os.path.getsize(full)
            if ext in DOC_EXT:
                docs.append({"name": n, "stem": os.path.splitext(n)[0], "rel": rel,
                             "ext": ext.lstrip("."), "size": size})
            elif ext in IMG_EXT:
                imgs.append({"name": n, "rel": rel, "size": size,
                             "dir": os.path.dirname(rel)})
            elif ext in CODE_EXT:
                codes.append({"name": n, "rel": rel, "size": size,
                              "ext": ext.lstrip(".")})

    # 元数据：按文件名顺序读 HTML，取第一个带 lecture-title 的
    for d in sorted(docs, key=lambda x: x["name"]):
        if d["ext"] in ("html", "htm"):
            head = read_head(os.path.join(BASE, d["rel"].replace("/", os.sep)))
            d["tag"] = head.get("tag", "")
            if head.get("date") and not meta.get("date"):
                meta["date"] = head["date"]
            if head.get("title") and not meta.get("title"):
                meta["title"] = head["title"]
                meta["title_en"] = head.get("title_en", "")
            if not meta.get("desc") and head.get("desc"):
                meta["desc"] = head["desc"]

    # 角色修正：docs 里没有「正式版」，就把最大的那个 HTML 当正式版
    if docs and not any(classify(d["name"]) == "正式版" for d in docs):
        big = max((d for d in docs if d["ext"] in ("html", "htm")),
                  key=lambda d: d["size"], default=None)
        if big:
            big["force_kind"] = "正式版"

    rows = []

    # 图片版：按所在目录分组，一条记录
    groups = {}
    for im in imgs:
        groups.setdefault(im["dir"], []).append(im)
    for gdir, items in sorted(groups.items()):
        items.sort(key=lambda x: x["name"])
        folder_name = os.path.basename(gdir) or "图片"
        total = sum(x["size"] for x in items)
        rows.append({
            "kind": "图片版",
            "title": "{}（{} 张）".format(folder_name, len(items)),
            "path": items[0]["rel"],
            "sub": "{}/{} … {}".format(folder_name, items[0]["name"], items[-1]["name"]),
            "desc": "A4 打印导出，按 01–{:02d} 顺序阅读；点开从第 1 张看起".format(len(items)),
            "meta": "{} 张 · {}".format(len(items), human_size(total)),
            "ext": "png",
        })

    for d in docs:
        kind = d.get("force_kind") or classify(d["name"])
        rows.append({
            "kind": kind,
            "title": d.get("tag") or d["stem"],
            "path": d["rel"],
            "sub": d["rel"],
            "desc": "",
            "meta": human_size(d["size"]),
            "ext": d["ext"],
        })

    for c in codes:
        rows.append({
            "kind": classify(c["name"]),
            "title": c["name"],
            "path": c["rel"],
            "sub": c["rel"],
            "desc": "可直接运行的脚本" if c["ext"] in ("py", "ps1", "js") else "",
            "meta": human_size(c["size"]),
            "ext": c["ext"],
        })

    rows.sort(key=lambda r: (KIND_ORDER.get(r["kind"], 99), r["path"]))

    counters = {
        "rows": len(rows),
        "正式版": sum(1 for r in rows if r["kind"] == "正式版"),
        "图片": sum(len(v) for v in groups.values()),
        "附件": sum(1 for r in rows if r["kind"] == "附件"),
    }
    return meta, rows, counters


# --------------------------------------------------------------------------
# 渲染
# --------------------------------------------------------------------------
def esc(s):
    return html.escape(s, quote=True)


def render_row(r):
    desc = ""
    if r["desc"]:
        desc = ' <span class="desc">— {}</span>'.format(esc(r["desc"]))
    return (
        '          <tr>'
        '<td><span class="kind k-{kind}">{kind}</span></td>'
        '<td class="f"><a href="{href}">{title}</a>{desc}'
        '<span class="path">{sub}</span></td>'
        '<td class="m">{meta}<span class="ext">{ext}</span></td>'
        '</tr>'
    ).format(kind=esc(r["kind"]), href=esc(r["path"]), title=esc(r["title"]),
             desc=desc, sub=esc(r["sub"]), meta=esc(r["meta"]), ext=esc(r["ext"].upper()))


def render_lecture(folder_name, meta, rows, counters):
    date = meta.get("date", "")
    title = meta.get("title", "") or folder_name.replace("-", " ")
    if meta.get("title_en"):
        title = "{}　·　{}".format(meta["title_en"], title)

    chips = []
    if counters["正式版"]:
        chips.append("正文 1")
    if counters["图片"]:
        chips.append("图片版 {} 张".format(counters["图片"]))
    if counters["附件"]:
        chips.append("附件 {}".format(counters["附件"]))
    chips_html = "".join('<span class="chip">{}</span>'.format(esc(c)) for c in chips) \
        or '<span class="chip muted">空</span>'

    desc_html = ""
    if meta.get("desc"):
        desc_html = '\n      <p class="lede">{}</p>'.format(esc(clip(meta["desc"], 150)))

    rows_html = "\n".join(render_row(r) for r in rows)

    return """    <article class="lec">
      <div class="head">
        <div class="date">{date}</div>
        <div class="chips">{chips}</div>
        <h2>{title}</h2>
      </div>{desc}
      <table class="files">
        <thead><tr><th>角色</th><th>文件</th><th>大小</th></tr></thead>
        <tbody>
{rows}
        </tbody>
      </table>
    </article>""".format(date=esc(date) or "未标日期", chips=chips_html,
                        title=esc(title), desc=desc_html, rows=rows_html)


CSS = """
  :root{
    --ink:#141a22;--ink-2:#3d4753;--muted:#69737f;--faint:#8d96a1;
    --line:#dfe4ea;--line-2:#c8d0d9;--bg:#eef0f3;--paper:#fff;
    --navy:#1f4e79;--navy-pale:#eef3f9;
  }
  *{box-sizing:border-box}
  body{margin:0;background:var(--bg);color:var(--ink);
       font-family:"Segoe UI","PingFang SC","Hiragino Sans GB","Microsoft YaHei",system-ui,sans-serif;
       font-size:15px;line-height:1.7;}
  .page{max-width:980px;margin:0 auto;padding:0 20px 72px;}
  header.top{background:var(--paper);border:1px solid var(--line);border-radius:12px;
             padding:26px 30px;margin:26px 0 18px;box-shadow:0 1px 2px rgba(20,25,40,.05);}
  h1{font-size:26px;margin:0 0 8px;letter-spacing:-.01em;}
  .sub{color:var(--faint);font-size:13.5px;margin:0;}
  .sub b{color:var(--ink-2);}
  .lec{background:var(--paper);border:1px solid var(--line);border-radius:12px;
       padding:22px 26px 12px;margin-bottom:16px;box-shadow:0 1px 2px rgba(20,25,40,.05);}
  .head{display:flex;flex-wrap:wrap;align-items:center;gap:8px 10px;}
  .date{font-family:"Cascadia Mono",Consolas,monospace;font-size:12.5px;color:var(--navy);
        background:var(--navy-pale);border-radius:5px;padding:2px 8px;letter-spacing:.03em;}
  h2{font-size:18.5px;margin:2px 0 0;flex:1 1 100%;line-height:1.4;}
  .chips{display:flex;gap:6px;flex-wrap:wrap;}
  .chip{font-size:11.5px;color:var(--muted);border:1px solid var(--line-2);
        border-radius:999px;padding:1px 9px;background:#fbfcfd;}
  .chip.muted{color:var(--faint);}
  .lede{color:var(--ink-2);font-size:13.8px;margin:12px 0 0;}
  table.files{width:100%;border-collapse:collapse;margin:14px 0 8px;font-size:14px;}
  th,td{text-align:left;vertical-align:top;padding:9px 10px;border-bottom:1px solid var(--line);}
  thead th{background:#f7f8fa;font-size:11.8px;letter-spacing:.06em;color:var(--muted);
           text-transform:uppercase;border-bottom:1px solid var(--line-2);}
  tbody tr:last-child td{border-bottom:none;}
  .kind{display:inline-block;font-size:11.5px;border-radius:4px;padding:1px 7px;white-space:nowrap;
        border:1px solid var(--line-2);color:var(--ink-2);background:#fafbfc;}
  .k-正式版{color:#1f4e79;background:#eef3f9;border-color:#c9dcee;font-weight:600;}
  .k-图片版{color:#1f7a5a;background:#eaf6f1;border-color:#cbe7db;}
  .k-附件{color:#7a5a1f;background:#fdf6e7;border-color:#eadfc4;}
  .f a{color:var(--navy);text-decoration:none;font-weight:600;}
  .f a:hover{text-decoration:underline;}
  .desc{color:var(--ink-2);font-weight:400;}
  .path{display:block;font-family:"Cascadia Mono",Consolas,monospace;font-size:11.6px;
        color:var(--faint);margin-top:2px;word-break:break-all;}
  .m{white-space:nowrap;font-size:12.5px;color:var(--muted);text-align:right;}
  .ext{display:inline-block;margin-left:8px;font-family:"Cascadia Mono",Consolas,monospace;
       font-size:10.5px;color:var(--faint);border:1px solid var(--line);border-radius:3px;padding:0 4px;}
  .empty{background:var(--paper);border:1px dashed var(--line-2);border-radius:12px;
         padding:34px;text-align:center;color:var(--faint);}
  footer{text-align:center;color:var(--faint);font-size:12.5px;padding:24px 0 0;line-height:1.9;}
  @media print{
    @page{size:A4;margin:14mm 13mm;}
    body{background:#fff;font-size:10.2pt;line-height:1.5;}
    .page{max-width:none;padding:0;}
    header.top,.lec{border:none;border-radius:0;box-shadow:none;padding:0;margin:0 0 8mm;}
    header.top{border-bottom:2px solid #000;padding-bottom:3mm;margin-bottom:6mm;}
    h1{font-size:17pt;} h2{font-size:12.5pt;}
    .lede{font-size:8.8pt;}
    table.files{font-size:8.8pt;}
    .path{font-size:7.8pt;}
    .lec{break-inside:avoid;}
    th{background:#f2f2f2;}
    a{color:#000;text-decoration:none;}
  }
  @media (max-width:720px){
    .lec{padding:18px 16px 10px;}
    header.top{padding:20px 18px;}
    h1{font-size:21px;}
    .m{display:none;} .files thead th:last-child{display:none;}
  }
"""

HTML_TMPL = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>讲座总索引</title>
<style>__CSS__</style>
</head>
<body>
<div class="page">
<header class="top">
  <h1>讲座总索引</h1>
  <p class="sub">共 <b>__N_LEC__</b> 场讲座__IMG_PART__ · 更新于 __NOW__</p>
</header>
__BODY__
<footer>
  本页由 <code>_脚本\\生成索引.py</code> 生成，不要手改 · 新增或改动资料后重新运行即可<br>
  点击任意文件即在浏览器打开；「打印 → 另存为 PDF」可得到 A4 索引
</footer>
</div>
</body>
</html>
"""


def main():
    lectures = sorted(
        (d for d in os.listdir(BASE)
         if os.path.isdir(os.path.join(BASE, d)) and not d.startswith("_")),
        reverse=True,
    )

    blocks, dates, total_imgs = [], [], 0
    for name in lectures:
        folder = os.path.join(BASE, name)
        meta, rows, counters = scan_lecture(folder)
        if not rows:
            continue
        blocks.append(render_lecture(name, meta, rows, counters))
        dates.append(meta.get("date") or name)
        total_imgs += counters["图片"]

    order = sorted(range(len(blocks)), key=lambda i: dates[i], reverse=True)
    body = "\n\n".join(blocks[i] for i in order) if blocks else \
        '    <div class="empty">还没有讲座资料。新建一个讲座文件夹（建议用英文标题命名）后重新运行本脚本。</div>'

    # 没有图片版时不显示「0 张图片版页面」，避免首页出现无意义的信息
    img_part = f" · <b>{total_imgs}</b> 张图片版页面" if total_imgs else ""

    page = (HTML_TMPL
            .replace("__CSS__", CSS)
            .replace("__N_LEC__", str(len(blocks)))
            .replace("__IMG_PART__", img_part)
            .replace("__NOW__", datetime.now().strftime("%Y-%m-%d %H:%M"))
            .replace("__BODY__", body))

    out = os.path.join(BASE, "index.html")
    with open(out, "w", encoding="utf-8", newline="\n") as f:
        f.write(page)

    print("index.html 已更新")
    print("  讲座：{} 场".format(len(blocks)))
    print("  图片版：{} 张".format(total_imgs))
    print("  输出：{}".format(out))


if __name__ == "__main__":
    main()
