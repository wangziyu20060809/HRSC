# -*- coding: utf-8 -*-
"""用 Word COM 更新域（目录/页码）并导出 PDF，返回页数与字数。

用法：python tools/word_finalize.py docs/行业分析.docx [更多 docx ...]
"""
import sys
from pathlib import Path

import win32com.client as win32

WD_STATISTIC_PAGES = 2
WD_STATISTIC_WORDS = 0
WD_EXPORT_FORMAT_PDF = 17


def finalize(path: Path, export_pdf=True, toc_index=1):
    path = path.resolve()
    word = win32.gencache.EnsureDispatch("Word.Application")
    word.Visible = False
    word.DisplayAlerts = 0
    doc = word.Documents.Open(str(path), ReadOnly=False)
    try:
        for _ in range(2):
            try:
                doc.Fields.Update()
            except Exception:
                pass
            try:
                if doc.TablesOfContents.Count >= toc_index:
                    doc.TablesOfContents(toc_index).Update()
            except Exception:
                pass
        doc.Repaginate()
        pages = doc.ComputeStatistics(WD_STATISTIC_PAGES)
        words = doc.ComputeStatistics(WD_STATISTIC_WORDS)
        doc.Save()
        out = None
        if export_pdf:
            out = path.with_suffix(".pdf")
            doc.ExportAsFixedFormat(str(out), WD_EXPORT_FORMAT_PDF)
        return pages, words, out
    finally:
        doc.Close(SaveChanges=0)
        word.Quit()


if __name__ == "__main__":
    targets = [Path(p) for p in sys.argv[1:]]
    for t in targets:
        pages, words, out = finalize(t)
        print(f"{t.name}: {pages} 页 / {words} 字" + (f" → {out.name}" if out else ""))
