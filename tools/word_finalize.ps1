# Word 定稿：更新目录/页码域，另存 PDF，输出页数与字数
# 用法： powershell -File tools/word_finalize.ps1 -Files "docs\行业分析.docx"
param(
  [Parameter(Mandatory = $true)][string[]]$Files,
  [switch]$NoPdf
)

$word = New-Object -ComObject Word.Application
$word.Visible = $false
$word.DisplayAlerts = 0

foreach ($f in $Files) {
  $path = (Resolve-Path $f).Path
  $doc = $word.Documents.Open($path, $false, $false)
  try {
    for ($i = 0; $i -lt 2; $i++) {
      try { $doc.Fields.Update() | Out-Null } catch {}
      try { if ($doc.TablesOfContents.Count -ge 1) { $doc.TablesOfContents(1).Update() | Out-Null } } catch {}
    }
    $doc.Repaginate()
    $pages = $doc.ComputeStatistics(2)   # wdStatisticPages
    $words = $doc.ComputeStatistics(0)   # wdStatisticWords
    $doc.Save()
    if (-not $NoPdf) {
      $pdf = [System.IO.Path]::ChangeExtension($path, ".pdf")
      $doc.ExportAsFixedFormat($pdf, 17) # wdExportFormatPDF
    }
    Write-Output ("{0}: {1} 页 / {2} 字" -f (Split-Path $path -Leaf), $pages, $words)
  }
  finally {
    $doc.Close(0)
  }
}
$word.Quit()
[System.Runtime.Interopservices.Marshal]::ReleaseComObject($word) | Out-Null
