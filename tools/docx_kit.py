# -*- coding: utf-8 -*-
"""docx_kit —— 轻量 Word 生成工具（项目内统一版式）

设计目标：一个 build(spec) 就能产出与既有交付文档同风格的中文 A4 文档：
  - A4 页面、统一页边距、页脚页码
  - 内置 Heading 1/2/3（保证 Word 里 TOC 域能正确更新）
  - 正文首行缩进 2 字符、1.55 倍行距、中英文字体分离
  - 表格：整表不跨页、表头重复、斑马纹、表题在上
  - 图片：居中、图题在下、按内容宽度自适应
  - 提示框（callout）：浅底色块，用于「注意 / 结论 / 边界」
  - 目录：TOC 域 + 打开时自动更新（w:updateFields）

用法：
    from docx_kit import Doc
    d = Doc("标题", "副标题")
    d.h1("一、背景")
    d.p("正文……")
    d.table(["列1","列2"], [["a","b"]], caption="表 1　示例")
    d.save("out.docx")
"""
from __future__ import annotations

import os
from pathlib import Path

from docx import Document
from docx.enum.section import WD_SECTION
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH, WD_LINE_SPACING
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Cm, Pt, RGBColor

INK = RGBColor(0x1E, 0x2A, 0x25)        # 正文墨色
BRAND = RGBColor(0x1F, 0x3D, 0x33)      # 品牌深绿（标题）
ACCENT = RGBColor(0x2D, 0x6A, 0x4F)     # 强调绿
MUTED = RGBColor(0x5E, 0x6B, 0x64)      # 注释灰
TABLE_HEAD_BG = "EDF3EF"
ZEBRA_BG = "F8FAF8"
CALLOUT_BG = "F4F7F3"

CN_FONT = "微软雅黑"
CN_BODY = "宋体"
EN_FONT = "Times New Roman"
MONO = "Consolas"


def _set_run_fonts(run, cn=CN_BODY, en=EN_FONT, size=None, bold=None, color=None, italic=None):
    if size is not None:
        run.font.size = Pt(size)
    if bold is not None:
        run.bold = bold
    if italic is not None:
        run.italic = italic
    if color is not None:
        run.font.color.rgb = color
    run.font.name = en
    rpr = run._element.get_or_add_rPr()
    rfonts = rpr.find(qn("w:rFonts"))
    if rfonts is None:
        rfonts = OxmlElement("w:rFonts")
        rpr.append(rfonts)
    rfonts.set(qn("w:ascii"), en)
    rfonts.set(qn("w:hAnsi"), en)
    rfonts.set(qn("w:eastAsia"), cn)


def _shade(element_pr, hex_color):
    shd = OxmlElement("w:shd")
    shd.set(qn("w:val"), "clear")
    shd.set(qn("w:color"), "auto")
    shd.set(qn("w:fill"), hex_color)
    element_pr.append(shd)


def _para_border(paragraph, color="D8E2DA", left_only=False):
    pPr = paragraph._p.get_or_add_pPr()
    borders = OxmlElement("w:pBdr")
    sides = ("left",) if left_only else ("top", "left", "bottom", "right")
    for side in sides:
        el = OxmlElement(f"w:{side}")
        el.set(qn("w:val"), "single")
        el.set(qn("w:sz"), "18" if side == "left" else "6")
        el.set(qn("w:space"), "6")
        el.set(qn("w:color"), ACCENT.__str__().replace("0x", "") if side == "left" else color)
        borders.append(el)
    pPr.append(borders)


def _field(paragraph, instr: str, placeholder: str = ""):
    run = paragraph.add_run()
    fld_begin = OxmlElement("w:fldChar")
    fld_begin.set(qn("w:fldCharType"), "begin")
    instr_el = OxmlElement("w:instrText")
    instr_el.set(qn("xml:space"), "preserve")
    instr_el.text = instr
    fld_sep = OxmlElement("w:fldChar")
    fld_sep.set(qn("w:fldCharType"), "separate")
    fld_text = OxmlElement("w:t")
    fld_text.text = placeholder
    fld_end = OxmlElement("w:fldChar")
    fld_end.set(qn("w:fldCharType"), "end")
    run._r.append(fld_begin)
    run._r.append(instr_el)
    run._r.append(fld_sep)
    run._r.append(fld_text)
    run._r.append(fld_end)


class Doc:
    def __init__(self, title: str, subtitle: str = "", meta_lines: list[str] | None = None,
                 toc: bool = True, footer_note: str = "", brand: str = "山海旅居 · 酒店房态与入住协同"):
        self.doc = Document()
        self._skip_next_break = False
        self.title = title
        self.footer_note = footer_note or brand
        self._setup_page()
        self._setup_styles()
        self._cover(title, subtitle, meta_lines or [])
        if toc:
            # 目录标题不参与 TOC：用普通段落模仿标题样式，避免「目录」把自己列进目录
            tp = self.doc.add_paragraph()
            tp.paragraph_format.space_before = Pt(6)
            tp.paragraph_format.space_after = Pt(10)
            tr = tp.add_run("目　录")
            _set_run_fonts(tr, cn=CN_FONT, en=EN_FONT, size=16, bold=True, color=BRAND)
            p = self.doc.add_paragraph()
            _field(p, 'TOC \\o "1-3" \\h \\z \\u', "（右键「更新域」生成目录）")
            self.doc.add_page_break()
            self._skip_next_break = True

    # ---------------- 基础设置 ----------------
    def _setup_page(self):
        sec = self.doc.sections[0]
        sec.page_width = Cm(21.0)
        sec.page_height = Cm(29.7)
        sec.top_margin = Cm(2.4)
        sec.bottom_margin = Cm(2.2)
        sec.left_margin = Cm(2.4)
        sec.right_margin = Cm(2.4)
        sec.header_distance = Cm(1.4)
        sec.footer_distance = Cm(1.2)
        self._footer(sec)

    def _footer(self, sec):
        p = sec.footer.paragraphs[0]
        p.alignment = WD_ALIGN_PARAGRAPH.CENTER
        r = p.add_run(self.footer_note + "　·　第 ")
        _set_run_fonts(r, size=8.5, color=MUTED)
        _field(p, "PAGE", "1")
        r2 = p.add_run(" 页")
        _set_run_fonts(r2, size=8.5, color=MUTED)

    def _setup_styles(self):
        st = self.doc.styles
        normal = st["Normal"]
        normal.font.size = Pt(10.5)
        normal.font.name = EN_FONT
        normal.font.color.rgb = INK
        normal.element.rPr.rFonts.set(qn("w:eastAsia"), CN_BODY)
        pf = normal.paragraph_format
        pf.line_spacing_rule = WD_LINE_SPACING.MULTIPLE
        pf.line_spacing = 1.55
        pf.space_before = Pt(0)
        pf.space_after = Pt(6)

        for name, size, color, before, after in (
            ("Heading 1", 16, BRAND, 16, 10),
            ("Heading 2", 13, ACCENT, 14, 6),
            ("Heading 3", 11.5, INK, 10, 4),
        ):
            s = st[name]
            s.font.size = Pt(size)
            s.font.bold = True
            s.font.color.rgb = color
            s.font.name = CN_FONT
            s.element.rPr.rFonts.set(qn("w:eastAsia"), CN_FONT)
            s.element.rPr.rFonts.set(qn("w:ascii"), EN_FONT)
            s.element.rPr.rFonts.set(qn("w:hAnsi"), EN_FONT)
            s.paragraph_format.space_before = Pt(before)
            s.paragraph_format.space_after = Pt(after)
            s.paragraph_format.keep_with_next = True
            s.paragraph_format.line_spacing = 1.2

        for nm in ("List Bullet", "List Number"):
            s = st[nm]
            s.font.size = Pt(10.5)
            s.font.name = CN_BODY
            s.element.rPr.rFonts.set(qn("w:eastAsia"), CN_BODY)
            s.paragraph_format.line_spacing = 1.45
            s.paragraph_format.space_after = Pt(3)

    def _cover(self, title, subtitle, meta_lines):
        for _ in range(3):
            self.doc.add_paragraph()
        p = self.doc.add_paragraph()
        p.alignment = WD_ALIGN_PARAGRAPH.CENTER
        r = p.add_run(title)
        _set_run_fonts(r, cn=CN_FONT, size=26, bold=True, color=BRAND)

        if subtitle:
            p = self.doc.add_paragraph()
            p.alignment = WD_ALIGN_PARAGRAPH.CENTER
            p.paragraph_format.space_before = Pt(6)
            r = p.add_run(subtitle)
            _set_run_fonts(r, cn=CN_FONT, size=12.5, color=ACCENT)

        self.doc.add_paragraph()
        p = self.doc.add_paragraph()
        p.alignment = WD_ALIGN_PARAGRAPH.CENTER
        r = p.add_run("—" * 18)
        _set_run_fonts(r, size=10, color=MUTED)

        for line in meta_lines:
            p = self.doc.add_paragraph()
            p.alignment = WD_ALIGN_PARAGRAPH.CENTER
            p.paragraph_format.space_after = Pt(2)
            r = p.add_run(line)
            _set_run_fonts(r, size=9.5, color=MUTED)
        self.doc.add_page_break()

    # ---------------- 内容块 ----------------
    def h1(self, text, numbered=True, page_break=True, in_toc=True):
        if page_break and len(self.doc.paragraphs) > 3 and not self._skip_next_break:
            self.doc.add_page_break()
        self._skip_next_break = False
        p = self.doc.add_paragraph(style="Heading 1")
        r = p.add_run(text)
        _set_run_fonts(r, cn=CN_FONT, en=EN_FONT, size=16, bold=True, color=BRAND)
        return p

    def h2(self, text):
        p = self.doc.add_paragraph(style="Heading 2")
        r = p.add_run(text)
        _set_run_fonts(r, cn=CN_FONT, en=EN_FONT, size=13, bold=True, color=ACCENT)
        return p

    def h3(self, text):
        p = self.doc.add_paragraph(style="Heading 3")
        r = p.add_run(text)
        _set_run_fonts(r, cn=CN_FONT, en=EN_FONT, size=11.5, bold=True, color=INK)
        return p

    def p(self, text, indent=True, size=10.5, space_after=6, bold=False, color=None, align=None):
        p = self.doc.add_paragraph()
        pf = p.paragraph_format
        if indent:
            pf.first_line_indent = Pt(size * 2)
        pf.space_after = Pt(space_after)
        if align == "center":
            p.alignment = WD_ALIGN_PARAGRAPH.CENTER
        # 支持 **加粗** 片段
        for i, seg in enumerate(text.split("**")):
            if not seg:
                continue
            r = p.add_run(seg)
            _set_run_fonts(r, size=size, bold=(bold or i % 2 == 1), color=color)
        return p

    def bullets(self, items, numbered=False):
        style = "List Number" if numbered else "List Bullet"
        for it in items:
            p = self.doc.add_paragraph(style=style)
            p.paragraph_format.space_after = Pt(3)
            for i, seg in enumerate(str(it).split("**")):
                if not seg:
                    continue
                r = p.add_run(seg)
                _set_run_fonts(r, size=10.5, bold=(i % 2 == 1))

    def note(self, text, label="说明", bg=CALLOUT_BG):
        tbl = self.doc.add_table(rows=1, cols=1)
        tbl.alignment = WD_TABLE_ALIGNMENT.CENTER
        tbl.autofit = True
        cell = tbl.cell(0, 0)
        cell.paragraphs[0].text = ""
        p = cell.paragraphs[0]
        p.paragraph_format.space_before = Pt(4)
        p.paragraph_format.space_after = Pt(4)
        r = p.add_run(f"{label}　")
        _set_run_fonts(r, cn=CN_FONT, size=9.5, bold=True, color=ACCENT)
        for i, seg in enumerate(text.split("**")):
            if not seg:
                continue
            rr = p.add_run(seg)
            _set_run_fonts(rr, size=9.5, bold=(i % 2 == 1), color=INK)
        tcPr = cell._tc.get_or_add_tcPr()
        _shade(tcPr, bg)
        _para_border(p, left_only=True)
        self._cell_margins(cell, 120)
        self.doc.add_paragraph().paragraph_format.space_after = Pt(2)

    def code(self, text):
        tbl = self.doc.add_table(rows=1, cols=1)
        cell = tbl.cell(0, 0)
        cell.paragraphs[0].text = ""
        lines = text.strip("\n").split("\n")
        first = True
        for line in lines:
            p = cell.paragraphs[0] if first else cell.add_paragraph()
            first = False
            p.paragraph_format.space_after = Pt(0)
            p.paragraph_format.line_spacing = 1.15
            r = p.add_run(line if line else " ")
            _set_run_fonts(r, cn=MONO, en=MONO, size=8.8, color=RGBColor(0x33, 0x3B, 0x36))
        _shade(cell._tc.get_or_add_tcPr(), "F5F6F4")
        self._cell_margins(cell, 120)
        self.doc.add_paragraph().paragraph_format.space_after = Pt(2)

    def table(self, header, rows, caption="", widths=None, size=9, align_center=True, zebra=True):
        if caption:
            p = self.doc.add_paragraph()
            p.paragraph_format.space_before = Pt(6)
            p.paragraph_format.space_after = Pt(3)
            p.paragraph_format.keep_with_next = True
            p.alignment = WD_ALIGN_PARAGRAPH.CENTER
            r = p.add_run(caption)
            _set_run_fonts(r, cn=CN_FONT, size=9, bold=True, color=ACCENT)

        tbl = self.doc.add_table(rows=1, cols=len(header))
        tbl.style = "Table Grid"
        tbl.alignment = WD_TABLE_ALIGNMENT.CENTER
        tbl.autofit = True if not widths else False

        hdr = tbl.rows[0]
        self._repeat_header(hdr)
        for i, h in enumerate(header):
            cell = hdr.cells[i]
            cell.text = ""
            p = cell.paragraphs[0]
            p.alignment = WD_ALIGN_PARAGRAPH.CENTER
            p.paragraph_format.space_after = Pt(0)
            p.paragraph_format.space_before = Pt(0)
            r = p.add_run(str(h))
            _set_run_fonts(r, cn=CN_FONT, size=size, bold=True, color=BRAND)
            _shade(cell._tc.get_or_add_tcPr(), TABLE_HEAD_BG)
            self._cell_margins(cell, 90)

        for ri, row in enumerate(rows):
            cells = tbl.add_row().cells
            self._no_split(tbl.rows[-1])
            for ci, val in enumerate(row):
                cell = cells[ci]
                cell.text = ""
                p = cell.paragraphs[0]
                p.paragraph_format.space_after = Pt(0)
                p.paragraph_format.space_before = Pt(0)
                p.paragraph_format.line_spacing = 1.28
                if align_center and ci > 0 and len(str(val)) <= 14:
                    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
                for k, seg in enumerate(str(val).split("**")):
                    if not seg:
                        continue
                    r = p.add_run(seg)
                    _set_run_fonts(r, size=size, bold=(k % 2 == 1))
                if zebra and ri % 2 == 1:
                    _shade(cell._tc.get_or_add_tcPr(), ZEBRA_BG)
                self._cell_margins(cell, 90)

        if widths:
            total = sum(widths)
            cap = 15.9
            scale = cap / total if total > cap else 1.0
            for i, w in enumerate(widths):
                for row in tbl.rows:
                    row.cells[i].width = Cm(w * scale)
            # 固定布局，避免 Word 按内容重新分配导致超出版心
            tblPr = tbl._tbl.tblPr
            layout = OxmlElement("w:tblLayout")
            layout.set(qn("w:type"), "fixed")
            tblPr.append(layout)
        self.doc.add_paragraph().paragraph_format.space_after = Pt(2)

    def image(self, path, caption="", width_cm=15.4):
        path = str(path)
        if not Path(path).exists():
            self.p(f"（缺图：{os.path.basename(path)}）", indent=False, color=MUTED)
            return
        p = self.doc.add_paragraph()
        p.alignment = WD_ALIGN_PARAGRAPH.CENTER
        p.paragraph_format.space_before = Pt(4)
        p.paragraph_format.space_after = Pt(2)
        p.add_run().add_picture(path, width=Cm(width_cm))
        if caption:
            c = self.doc.add_paragraph()
            c.alignment = WD_ALIGN_PARAGRAPH.CENTER
            c.paragraph_format.space_after = Pt(8)
            r = c.add_run(caption)
            _set_run_fonts(r, cn=CN_FONT, size=9, color=MUTED)

    def kv_table(self, pairs, caption="", widths=(4.0, 11.4), size=9.5):
        self.table(["项目", "内容"], pairs, caption=caption, widths=widths, size=size,
                   align_center=False)

    # ---------------- 辅助 ----------------
    def _repeat_header(self, row):
        trPr = row._tr.get_or_add_trPr()
        el = OxmlElement("w:tblHeader")
        el.set(qn("w:val"), "true")
        trPr.append(el)

    def _no_split(self, row):
        trPr = row._tr.get_or_add_trPr()
        el = OxmlElement("w:cantSplit")
        el.set(qn("w:val"), "true")
        trPr.append(el)

    def _cell_margins(self, cell, twips=90):
        tcPr = cell._tc.get_or_add_tcPr()
        mar = OxmlElement("w:tcMar")
        for side in ("top", "left", "bottom", "right"):
            el = OxmlElement(f"w:{side}")
            el.set(qn("w:w"), str(twips if side in ("left", "right") else 40))
            el.set(qn("w:type"), "dxa")
            mar.append(el)
        tcPr.append(mar)

    def save(self, path):
        path = str(path)
        # 打开时自动更新域（目录、页码）
        settings = self.doc.settings.element
        upd = settings.find(qn("w:updateFields"))
        if upd is None:
            upd = OxmlElement("w:updateFields")
            settings.append(upd)
        upd.set(qn("w:val"), "true")
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.doc.save(path)
        return path
