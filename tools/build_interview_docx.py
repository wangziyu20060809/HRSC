# -*- coding: utf-8 -*-
"""build_interview_docx.py —— 由原始誊录整理两份 docx 访谈文档

1) 典型事件采访记录.docx：来自 docs/访谈记录/典型事件-采访记录.txt（原始誊录）
2) 六人访谈记录.docx：来自 docs/访谈记录/六人访谈记录.json（结构化）

两份文档都保留原话，不做结论改写；「整理说明」一节写明哪些内容是 AI 结构化时的
格式化处理（分段、编号、表格化），以便与原始录音誊录逐条核对。

用法：python tools/build_interview_docx.py
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from docx_kit import Doc

ROOT = Path(__file__).resolve().parents[1]
IV = ROOT / "docs" / "访谈记录"
TXT = IV / "典型事件-采访记录.txt"
JSON = IV / "六人访谈记录.json"


# ---------------------------------------------------------------------
# 解析誊录 txt
# ---------------------------------------------------------------------
def parse_txt(path: Path) -> tuple[dict, list[tuple[str, list[tuple[str, str]]]], list[list[str]]]:
    lines = path.read_text(encoding="utf-8").splitlines()
    meta: dict[str, str] = {}
    sections: list[tuple[str, list[tuple[str, str]]]] = []
    cur_title, cur_turns, cur_spk = "", None, None

    for raw in lines:
        line = raw.rstrip()
        if not line.strip() or set(line.strip()) <= {"=", "-"}:
            continue
        if line.startswith("【"):
            cur_title = line.strip("【】 ")
            cur_turns = []
            sections.append((cur_title, cur_turns))
            cur_spk = None
            continue
        if line.startswith("附："):
            cur_title, cur_turns = "", None
            continue
        m = re.match(r"^(访谈方|顾明岚|指标)\s*[:：]\s*(.*)$", line.strip())
        if m and cur_turns is not None:
            cur_spk = m.group(1)
            cur_turns.append((cur_spk, m.group(2).strip()))
            continue
        if cur_turns is None and "：" in line:
            k, v = line.split("：", 1)
            meta[k.strip()] = v.strip()
            continue
        if cur_spk and cur_turns:
            spk, txt = cur_turns[-1]
            joiner = "" if txt.endswith(("，", "。", "；", "、", "？", "：")) else ""
            cur_turns[-1] = (spk, txt + joiner + line.strip())

    # 量化清单表
    table: list[list[str]] = []
    grab = False
    for raw in lines:
        s = raw.strip()
        if s.startswith("指标") and "现状" in s:
            grab = True
            continue
        if grab:
            if s.startswith("说明"):
                break
            if not s or set(s) <= {"-"}.union(" "):
                continue
            cells = [c.strip() for c in re.split(r"\s{2,}", s) if c.strip()]
            table.append(cells)
    return meta, sections, table


def build_event() -> None:
    meta, sections, table = parse_txt(TXT)
    doc = Doc(
        "典型事件采访记录",
        "山海旅居 · 房态与入住协同（资料编号 travel-hotel）",
        [
            "文档性质：访谈誊录的整理版（原始誊录见 典型事件-采访记录.txt）",
            f"受访人：{meta.get('访谈对象', '顾明岚')}",
            f"访谈时间：{meta.get('访谈时间', '')}",
            f"轮次：{meta.get('轮次', '')}",
            "整理日期：2026 年 11 月 6 日",
        ],
    )

    doc.h1("一、访谈基本信息")
    doc.kv_table([
        ("项目", meta.get("项目", "酒店房态与入住协同（资料编号 travel-hotel）")),
        ("受访人", meta.get("访谈对象", "顾明岚 · 酒店运营经理（共同提出人）")),
        ("访谈方", meta.get("访谈方", "FDE 业务发现小组")),
        ("访谈时间", meta.get("访谈时间", "")),
        ("方式", meta.get("方式", "现场面谈，全程录音后誊录")),
        ("轮次与问题数", meta.get("轮次", "3 轮，共 11 问")),
        ("证据编号", meta.get("证据编号", "沿用发现报告 f00–f55 体系")),
        ("资料性质", meta.get("资料性质", "合成训练资料的访谈誊录")),
    ], caption="表 1-1　访谈基本信息")

    doc.note("这份文档回答一个问题：把「客房部标了已清扫、前台当成可入住、客人干等 37 分钟」"
             "这件事，用当事人自己的话、带时间和金额，完整讲一遍。后面所有的需求、设计与验收指标，"
             "都从这一件事长出来。")

    for i, (title, turns) in enumerate(sections, 2):
        doc.h1(f"{['二','三','四','五','六'][i-2]}、{title}")
        for spk, txt in turns:
            if spk == "访谈方":
                doc.p(f"问（访谈方）：{txt}", indent=False)
            else:
                doc.p(f"答（顾明岚）：{txt}", indent=False)

    doc.h1("五、本次采访形成的量化清单")
    doc.p("下表是这次采访能落成数字的全部内容。需要特别说明的是：现状列都是当事人口述的观察值或估计值，"
          "未经系统化测量——这也是后来要求「按节点补测基线」的原因。", indent=False)
    rows = []
    for cells in table:
        cells = list(cells)
        # 原文个别行的「目标」与「证据」之间只有一个空格，这里补拆一次
        if len(cells) >= 3 and re.search(r"(f\d{2})$", cells[-1]) and len(cells) == 3:
            tail = re.match(r"^(.*?)\s*(f\d{2})$", cells[-1])
            if tail and tail.group(1):
                cells = [cells[0], cells[1], tail.group(1).strip(), tail.group(2)]
        if len(cells) == 3 and re.fullmatch(r"f\d{2}(/f\d{2})?", cells[2]):
            cells = [cells[0], cells[1], "", cells[2]]  # 原文无「目标」列的行
        cells = (cells + ["", "", "", ""])[:4]
        rows.append(cells)
    if rows:
        doc.table(["指标", "现状", "目标", "证据"], rows,
                  caption="表 5-1　量化清单（供后续文档引用）", widths=(4.6, 4.0, 3.6, 3.6),
                  align_center=False)
    doc.note("房态错误有两个口径——只数「状态标错」约 4 次/周，把「前台据此对客人做了承诺、"
             "后续要改房或补偿」也算进去是 24 次/周，两者差 6 倍。顾明岚倾向用 24，但明确表示「这个要质检签字」。"
             "任何引用这两个数字的文档都必须写清用的是哪个口径。", label="口径提醒")

    doc.h1("六、整理说明")
    doc.p("原始材料是一份口语化的录音誊录（典型事件-采访记录.txt）。整理成本文档时做了以下处理，"
          "均在保留原话的前提下进行，不改变任何结论：", indent=False)
    doc.bullets([
        "按轮次分段，并为每轮加标题（标题取自原问题，不是新观点）；",
        "把「访谈方 / 顾明岚」的问答对拆成独立段落，便于逐条核对；",
        "文末量化清单由正文中的数字抽取成表，第四列标注证据编号（f00–f55）；",
        "对原文中的口语句式（「就是我们刚才讲的 37 分钟」等）未做润色，保留了指代关系；",
        "没有新增任何数字。表里出现过的每个数，都能在正文里找到对应的那句话。",
    ])
    doc.p("换句话说，AI 在这里做的是「排版与索引」，不是「总结与推断」。判断一个整理版是否可信，"
          "标准很简单：把表格里任一数字拿回正文，能不能逐字找到。", indent=False)

    doc.save(IV / "典型事件采访记录.docx")
    print("saved 典型事件采访记录.docx")


def build_six() -> None:
    d = json.loads(JSON.read_text(encoding="utf-8"))
    m, ivs = d["meta"], d["interviews"]
    doc = Doc(
        "六人访谈记录",
        f"{m['project']} · {m.get('coverage', '')}",
        [
            f"资料编号：{m.get('case_code', 'travel-hotel')}　版本：{m.get('version', 'v1.0')}",
            f"访谈方法：{m.get('method', '')[:28]}…",
            f"覆盖：{m.get('coverage', '')}",
            f"整理日期：{m.get('date', '2026-11-06')}",
        ],
    )

    doc.h1("一、访谈概览")
    doc.p("六场访谈分别对应六个角色。每个人的第一轮都要求「用最近一次具体事件说明问题」，"
          "之后才追问流程、约束、量化、权限与验收。这样问的原因很直接：先拿到事实，再谈方案。", indent=False)
    doc.table(
        ["序", "受访人", "岗位", "角色定位", "时长", "本轮重点"],
        [[str(i["seq"]), i["name"], i["post"], i["role"], f"{i['duration_min']} 分钟", i["focus"]]
         for i in ivs],
        caption="表 1-1　六场访谈概览",
        widths=(0.9, 2.0, 3.2, 3.0, 1.8, 5.0),
        size=8,
        align_center=False,
    )
    doc.note(f"{m.get('nature', '')}。所有「现状数字」均为当事人口述的观察值或估计值，未经系统化测量。")

    if m.get("notes"):
        doc.h2("阅读须知")
        for n in m["notes"]:
            doc.p("· " + n, indent=False, size=10)

    for i, it in enumerate(ivs, 2):
        doc.h1(f"{['二','三','四','五','六','七'][i-2]}、{it['name']}（{it['post']}）")
        doc.kv_table([
            ("角色定位", it["role"]),
            ("访谈时间", it["time"]),
            ("时长 / 方式", f"{it['duration_min']} 分钟　·　{it['channel']}"),
            ("本轮重点", it["focus"]),
        ], caption="")
        for j, r in enumerate(it["rounds"], 1):
            doc.h3(f"第 {j} 轮")
            doc.p("问：" + r["q"], indent=False)
            doc.p("答：" + r["a"], indent=False)
            if r.get("numbers"):
                doc.note("量化线索：" + r["numbers"], label="量化线索", bg="F3F7F4")
            if r.get("facts"):
                doc.p("证据编号：" + "、".join(r["facts"]), indent=False, size=9)
        doc.h2("该角色关键结论")
        doc.bullets(it["key_points"])
        if it.get("open_items"):
            doc.h2("待核实项")
            doc.bullets(it["open_items"])

    doc.h1("八、整理说明")
    doc.p("本文件由 docs/访谈记录/六人访谈记录.json 生成，同一份数据另有 .md 与 .csv 两种形态，"
          "三者的问答内容完全一致，只是载体不同（阅读 / 程序处理 / 表格筛选）。", indent=False)
    doc.bullets([
        "问答文本为原始誊录，未做改写；仅补充了轮次编号与角色小标题；",
        "「量化线索」由该轮回答中被明确说出的数字抽取，用于后续指标定义；",
        "「证据编号」沿用发现报告 f00–f55 体系，便于需求文档与设计文档回溯；",
        "「待核实项」是受访人自己提出的不确定点，不是访谈方的推断。",
    ])

    doc.save(IV / "六人访谈记录.docx")
    print("saved 六人访谈记录.docx")


def main() -> None:
    build_event()
    build_six()


if __name__ == "__main__":
    main()
