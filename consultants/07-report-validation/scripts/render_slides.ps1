# render_slides.ps1 — PPTXの全スライドをPNG画像に書き出す（PowerPoint COM使用）
# 使い方: pwsh -File render_slides.ps1 -PptxPath <入力.pptx> -OutDir <出力フォルダ> [-Width 1600]
param(
    [Parameter(Mandatory = $true)][string]$PptxPath,
    [Parameter(Mandatory = $true)][string]$OutDir,
    [int]$Width = 1600
)
$ErrorActionPreference = 'Stop'

$PptxPath = (Resolve-Path $PptxPath).Path
New-Item -ItemType Directory -Force $OutDir | Out-Null
$OutDir = (Resolve-Path $OutDir).Path

$pp = New-Object -ComObject PowerPoint.Application
try {
    # ReadOnly=true / Untitled=true / WithWindow=false（元ファイルには一切触れない）
    $pres = $pp.Presentations.Open($PptxPath, $true, $true, $false)
    try {
        $h = [int]($Width * $pres.PageSetup.SlideHeight / $pres.PageSetup.SlideWidth)
        $total = $pres.Slides.Count
        foreach ($slide in $pres.Slides) {
            $n = $slide.SlideIndex
            $out = Join-Path $OutDir ("slide{0:d3}.png" -f $n)
            $slide.Export($out, "PNG", $Width, $h)
        }
        Write-Output "OK: $total 枚を $OutDir に書き出しました（${Width}x${h}px）"
    }
    finally {
        $pres.Close()
    }
}
finally {
    $pp.Quit()
    [System.Runtime.InteropServices.Marshal]::ReleaseComObject($pp) | Out-Null
    [GC]::Collect()
}
