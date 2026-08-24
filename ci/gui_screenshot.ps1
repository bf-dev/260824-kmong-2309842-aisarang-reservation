# GUI 스크린샷 캡처 (GitHub Actions windows-latest).
#
# PrintWindow 를 쓴다. CopyFromScreen 은 프레임버퍼가 비어 있으면 새까만
# 이미지를 조용히 돌려주고 어떤 "비어있음" 검사도 통과해버린다. PrintWindow 는
# 창에게 스스로 그리라고 시키므로 데스크톱이 비어 있어도 올바른 픽셀이 나온다.
#
# --onefile exe 는 부트로더 부모가 창을 소유하지 않는다. 자식이 소유한다.
# 그래서 Start-Process 결과의 MainWindowHandle 은 영원히 0 이다.
# 프로세스 이름으로 0 이 아닌 핸들을 polling 해야 한다.
$ErrorActionPreference = "Stop"
Add-Type -AssemblyName System.Drawing

Add-Type @"
using System;
using System.Runtime.InteropServices;
public class Win32Cap {
  [StructLayout(LayoutKind.Sequential)] public struct RECT { public int L, T, R, B; }
  [DllImport("user32.dll")] public static extern bool PrintWindow(IntPtr h, IntPtr hdc, uint f);
  [DllImport("user32.dll")] public static extern bool GetWindowRect(IntPtr h, out RECT r);
  [DllImport("user32.dll")] public static extern bool SetForegroundWindow(IntPtr h);
  [DllImport("user32.dll")] public static extern bool ShowWindow(IntPtr h, int c);
}
"@

$dir = Join-Path $PWD "screenshots"
New-Item -ItemType Directory -Force -Path $dir | Out-Null

$exe = Get-ChildItem (Join-Path $PWD "dist\*.exe") | Select-Object -First 1
if (-not $exe) { throw "dist 에 exe 가 없습니다" }
$base = [System.IO.Path]::GetFileNameWithoutExtension($exe.Name)
Write-Host "실행: $($exe.FullName)"

Get-Process -Name $base -ErrorAction SilentlyContinue | Stop-Process -Force

# --guidemo 는 실제 서버 시각 동기화 + 실제 센터 조회를 돌리고 결과를 화면에 띄운다.
$p = Start-Process $exe.FullName -ArgumentList "--guidemo","--hold=150000" -PassThru

$hwnd = [IntPtr]::Zero
for ($i = 0; $i -lt 120; $i++) {
  Start-Sleep -Seconds 1
  $win = Get-Process -Name $base -ErrorAction SilentlyContinue |
         Where-Object { $_.MainWindowHandle -ne 0 } | Select-Object -First 1
  if ($win) { $hwnd = $win.MainWindowHandle; Write-Host "창을 찾았습니다 ($i 초)"; break }
}
if ($hwnd -eq [IntPtr]::Zero) { throw "120초 안에 창이 열리지 않았습니다" }

# 실제 조회(서버 시각 동기화 + 기관 목록)가 끝나 결과가 화면에 뜰 때까지 기다린다.
Start-Sleep -Seconds 45

[Win32Cap]::ShowWindow($hwnd, 5) | Out-Null
[Win32Cap]::SetForegroundWindow($hwnd) | Out-Null
Start-Sleep -Seconds 2

$r = New-Object Win32Cap+RECT
[Win32Cap]::GetWindowRect($hwnd, [ref] $r) | Out-Null
$w = $r.R - $r.L; $h = $r.B - $r.T
Write-Host "창 크기: ${w}x${h}"
if ($w -lt 200 -or $h -lt 200) { throw "창 크기가 이상합니다: ${w}x${h}" }

$bmp = New-Object System.Drawing.Bitmap $w, $h
$g = [System.Drawing.Graphics]::FromImage($bmp)
$hdc = $g.GetHdc()
$ok = [Win32Cap]::PrintWindow($hwnd, $hdc, 2)
$g.ReleaseHdc($hdc)
if (-not $ok) { throw "PrintWindow 실패" }

$out = Join-Path $dir "gui.png"
$bmp.Save($out)

# 비어있는 캡처(단색/거의 단색)는 실패로 처리한다.
$colors = @{}
for ($x = 0; $x -lt $w; $x += 7) {
  for ($y = 0; $y -lt $h; $y += 7) {
    $colors[$bmp.GetPixel($x, $y).ToArgb()] = 1
  }
}
Write-Host "고유 색상 수: $($colors.Count)"
if ($colors.Count -lt 12) { throw "캡처가 비어 있습니다 (색상 $($colors.Count)종)" }

try { Get-Process -Name $base -ErrorAction SilentlyContinue | Stop-Process -Force } catch {}
Write-Host "저장: $out (${w}x${h}, 색상 $($colors.Count)종)"
