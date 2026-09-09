# measure_text.ps1 — 文字のはみ出しを PowerPoint 本体に測らせる（読み取り専用・保存しない）
#
#     pwsh -File measure_text.ps1 -PptxPath <レポート.pptx> [-Slack 2] [-Quiet]
#
# なぜ要るのか
#     check_layout.py は文字の高さを**見積もる**。描画しないので、それしかできない。
#     見積もりは実測と 0.05cm 以内で合うことを確かめてあるが、合わない枠が1%ある。
#     PowerPoint のある PC なら、見積もらずに**本人に測らせる**ことができる。
#     TextRange.BoundHeight は、折り返したあとの実際の文字の高さである。
#
# 何を見るか
#     枠あふれ   文字の下端が、入れた枠の下端を越えている
#     用紙の外   文字の下端が、スライドの下端を越えている
#
# 終了コード
#     0  はみ出しなし
#     1  はみ出しあり
#     2  測れなかった（PowerPoint が無い・開けない）。**検査したことにしない。**
param(
    [Parameter(Mandatory = $true)][string]$PptxPath,
    [double]$Slack = 2.0,      # 許容量(pt)。丸めのぶんは見逃す
    [switch]$Quiet             # 一覧を出さず、要約だけ
)
$ErrorActionPreference = 'Stop'
$PT_CM = 28.35

if (-not (Test-Path -LiteralPath $PptxPath)) {
    Write-Output "ファイルがありません: $PptxPath"
    exit 2
}
$path = (Resolve-Path -LiteralPath $PptxPath).Path

try {
    $pp = New-Object -ComObject PowerPoint.Application
}
catch {
    Write-Output "PowerPoint が使えないため、文字の実測はできません（$($_.Exception.Message)）"
    exit 2
}

# 利用者がすでに PowerPoint を開いていたら、終わっても閉じない
$already = [int]($pp.Presentations.Count)
$pres = $null
try {
    # ReadOnly=true / Untitled=true / WithWindow=false（元のファイルには一切触れない）
    $pres = $pp.Presentations.Open($path, $true, $true, $false)
}
catch {
    Write-Output "開けないため、文字の実測はできません（$($_.Exception.Message)）"
    if ($already -eq 0) { $pp.Quit() }
    exit 2
}

# ここから先で何が起きても、**「はみ出しあり」と取り違えない。**
# 納品ゲートの4つめとして走るため、COM の不調で既存3検査の判定を巻き添えにすると
# 「体裁は通っているのに納品できない」になる。測れなければ 2 を返して先へ通す。
try {
    $slideH = [double]($pres.PageSetup.SlideHeight)
    $rows = New-Object System.Collections.Generic.List[object]
    $checked = 0

    # グループの中も見る（枠だけを数えても意味がない）
    function Get-Frames($shapes) {
        $out = New-Object System.Collections.Generic.List[object]
        foreach ($sh in $shapes) {
            if ($sh.Type -eq 6) { $out.AddRange((Get-Frames $sh.GroupItems)); continue }
            if ([bool]$sh.HasTextFrame) { $out.Add($sh) }
        }
        return $out
    }

    foreach ($slide in $pres.Slides) {
        foreach ($sh in (Get-Frames $slide.Shapes)) {
            $tf = $sh.TextFrame
            if (-not [bool]$tf.HasText) { continue }
            $checked++
            $tr = $tf.TextRange
            $textBottom = [double]($tr.BoundTop) + [double]($tr.BoundHeight)
            $overBox = $textBottom - ([double]($sh.Top) + [double]($sh.Height))
            $overSlide = $textBottom - $slideH
            if (($overBox -le $Slack) -and ($overSlide -le $Slack)) { continue }
            $rows.Add([pscustomobject]@{
                    ページ  = [int]$slide.SlideIndex
                    図形    = [string]$sh.Name
                    枠cm    = [math]::Round([double]($sh.Height) / $PT_CM, 2)
                    文字cm  = [math]::Round([double]($tr.BoundHeight) / $PT_CM, 2)
                    枠超過cm = [math]::Round([math]::Max($overBox, 0) / $PT_CM, 2)
                    用紙外cm = [math]::Round([math]::Max($overSlide, 0) / $PT_CM, 2)
                    書出し  = ([string]$tr.Text -replace '\s+', ' ').Trim()
                })
        }
    }

    $name = Split-Path -Leaf $path
    Write-Output "■ $name（PowerPoint で実測）"
    Write-Output "  検査した文字枠 $checked / はみ出し $($rows.Count) 件 / スライド高 $([math]::Round($slideH / $PT_CM, 2)) cm"
    if ($rows.Count -gt 0) {
        if (-not $Quiet) {
            Write-Output ""
            $rows | Sort-Object ページ | ForEach-Object {
                $_.書出し = $_.書出し.Substring(0, [math]::Min(30, $_.書出し.Length))
                $_
            } | Format-Table -AutoSize | Out-String -Width 200 | Write-Output
        }
        Write-Output "要対応 $($rows.Count) 件。文章を短くするか、枠を広げてから作り直す。"
        exit 1
    }
    Write-Output "  はみ出しはありません。"
    exit 0
}
catch {
    Write-Output "測り切れなかったため、文字の実測はできません（$($_.Exception.Message)）"
    exit 2
}
finally {
    # 後始末の失敗で判定を変えない
    try { if ($null -ne $pres) { $pres.Close() } } catch {}
    try { if ($already -eq 0) { $pp.Quit() } } catch {}
    try {
        [System.Runtime.InteropServices.Marshal]::ReleaseComObject($pp) | Out-Null
    } catch {}
    [GC]::Collect()
}
