# README Product Poster Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Thay ba screenshot full-page trong Product Showcase bằng một poster bento `1600×900` kết hợp background AI nhẹ, crop UI thật và text/metric deterministic, có user preview gate trước khi cập nhật README hoặc push.

**Architecture:** Built-in image generation chỉ tạo background không chữ. Một HTML/CSS artifact ignored ghép background đó với ba screenshot thật và typography/metric xác định; Playwright chụp poster thành PNG. Sau khi người dùng duyệt preview, final PNG được đưa vào `docs/assets/readme/`, README chuyển sang một ảnh duy nhất và ba asset cũ bị xóa.

**Tech Stack:** Built-in `image_gen`, HTML/CSS, Python Playwright `1.62.0`, installed Microsoft Edge, GitHub-flavored Markdown, PowerShell, pytest, Git.

---

## File map

- Create ignored `output/readme-poster/radar-background.png`: background supporting input, không commit.
- Create ignored `output/readme-poster/poster.html`: deterministic composite template, không commit.
- Create ignored `output/readme-poster/devradar-product-poster-preview.png`: preview chờ user duyệt, không commit.
- Create after approval `docs/assets/readme/devradar-product-poster.png`: final README asset.
- Modify after approval `README.md`: thay Product Showcase ba ảnh bằng một poster.
- Delete after approval `docs/assets/readme/dashboard-overview.png`.
- Delete after approval `docs/assets/readme/analytics.png`.
- Delete after approval `docs/assets/readme/sources.png`.
- Preserve all application code, API, config, roadmap, ADR and evidence files.

### Task 1: Prepare isolated workspace and generate the atmospheric background

**Files:**

- Create ignored: `output/readme-poster/radar-background.png`
- Reference: `docs/superpowers/specs/2026-08-24-readme-product-poster-design.md`

- [ ] **Step 1: Create an isolated worktree and verify baseline**

Use `superpowers:using-git-worktrees` to create branch `codex/readme-product-poster` under `.worktrees/readme-product-poster`. Verify `.worktrees/` is ignored before creation.

Run from the worktree using the main repository virtual environment:

```powershell
& 'C:\Users\PC\Documents\Duy\DevRadar\.venv\Scripts\python.exe' -m pytest tests/test_custom_source_docs.py -q
```

Expected: `4 passed` and clean worktree.

- [ ] **Step 2: Create the ignored workspace**

Run:

```powershell
New-Item -ItemType Directory -Force output/readme-poster | Out-Null
git check-ignore -v output/readme-poster
```

Expected: path exists and is ignored by `/output/`.

- [ ] **Step 3: Generate one background with the built-in image tool**

Invoke built-in `image_gen` once with this exact prompt:

```text
Use case: productivity-visual
Asset type: subtle background layer for a GitHub README product poster
Primary request: create an abstract radar field and data-intelligence mesh for DevRadar, suggesting job-market signals moving through a trustworthy data pipeline
Scene/backdrop: wide clean editorial canvas with concentric radar rings, sparse data nodes, fine connecting paths, and generous negative space
Style/medium: premium editorial technology illustration, restrained, precise, soft depth, no photorealism
Composition/framing: 16:9 landscape; visual energy concentrated toward the right and outer edges; calm open area on the left for deterministic copy overlay
Lighting/mood: bright, calm, trustworthy, analytical
Color palette: warm off-white background, deep navy, indigo, restrained cyan, tiny amber accents
Constraints: background only; no text, letters, numbers, logos, UI screens, charts, people, devices, badges, watermark, or fake interface elements
Avoid: neon cyberpunk, dark mode, glassmorphism, stock-photo look, dense clutter, illegible pseudo-text
```

Use built-in mode only. Do not use CLI/API fallback and do not request an API key.

- [ ] **Step 4: Save and inspect the generated background**

Read the generated output hint, copy the selected generated image to:

```text
output/readme-poster/radar-background.png
```

Inspect at original detail. Accept only when all constraints hold. If generated text/UI/logo appears, make one targeted edit/regeneration that says:

```text
Remove every text-like mark, number, logo, chart, screen, and interface element. Keep only the abstract radar rings, sparse nodes, connecting paths, off-white/navy/indigo/cyan palette, and the same wide composition.
```

If built-in image generation is unavailable, continue with the exact CSS gradients/radar overlays in Task 2; do not switch tool modes.

### Task 2: Build the deterministic bento poster preview

**Files:**

- Create ignored: `output/readme-poster/poster.html`
- Create ignored: `output/readme-poster/devradar-product-poster-preview.png`
- Read: `docs/assets/readme/dashboard-overview.png`
- Read: `docs/assets/readme/analytics.png`
- Read: `docs/assets/readme/sources.png`

- [ ] **Step 1: Create the complete poster template**

Create `output/readme-poster/poster.html` with exactly this implementation:

```html
<!doctype html>
<html lang="vi">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>DevRadar Product Poster</title>
  <style>
    * { box-sizing: border-box; }
    html, body { margin: 0; width: 1600px; height: 900px; overflow: hidden; }
    body { font-family: "Segoe UI", Arial, sans-serif; background: #eef2f8; }
    .poster {
      position: relative;
      width: 1600px;
      height: 900px;
      overflow: hidden;
      padding: 58px 64px 48px;
      color: #10213b;
      background:
        linear-gradient(112deg, rgba(249, 247, 241, .98) 0%, rgba(245, 248, 252, .96) 45%, rgba(233, 241, 250, .92) 100%),
        url("./radar-background.png") center / cover no-repeat;
    }
    .poster::before {
      content: "";
      position: absolute;
      inset: 0;
      opacity: .24;
      pointer-events: none;
      background:
        radial-gradient(circle at 87% 20%, transparent 0 105px, rgba(79, 70, 229, .20) 106px 108px, transparent 109px 160px, rgba(8, 145, 178, .13) 161px 163px, transparent 164px),
        linear-gradient(rgba(30, 64, 175, .035) 1px, transparent 1px),
        linear-gradient(90deg, rgba(30, 64, 175, .035) 1px, transparent 1px);
      background-size: auto, 40px 40px, 40px 40px;
    }
    .layout {
      position: relative;
      z-index: 1;
      display: grid;
      grid-template-columns: 560px 1fr;
      gap: 54px;
      height: 696px;
    }
    .narrative { padding: 10px 0 0; }
    .brand-row { display: flex; align-items: center; gap: 16px; margin-bottom: 48px; }
    .brand-mark {
      display: grid;
      place-items: center;
      width: 54px;
      height: 54px;
      border-radius: 17px;
      color: white;
      font-size: 26px;
      font-weight: 800;
      background: linear-gradient(135deg, #4f46e5, #0891b2);
      box-shadow: 0 16px 32px rgba(79, 70, 229, .18);
    }
    .brand-name { font-size: 32px; line-height: 1; font-weight: 800; letter-spacing: -.03em; }
    .brand-sub { margin-top: 7px; color: #52627a; font-size: 18px; }
    .eyebrow {
      margin: 0 0 18px;
      color: #4f46e5;
      font-size: 18px;
      font-weight: 800;
      letter-spacing: .13em;
    }
    h1 {
      max-width: 540px;
      margin: 0;
      font-family: Georgia, "Times New Roman", serif;
      font-size: 61px;
      line-height: 1.04;
      letter-spacing: -.045em;
      text-wrap: balance;
    }
    .summary {
      max-width: 510px;
      margin: 24px 0 30px;
      color: #52627a;
      font-size: 24px;
      line-height: 1.45;
    }
    .metrics { display: grid; grid-template-columns: 1fr 1fr; gap: 14px; }
    .metric {
      min-height: 105px;
      padding: 17px 20px;
      border: 1px solid rgba(109, 128, 157, .22);
      border-radius: 20px;
      background: rgba(255, 255, 255, .76);
      box-shadow: 0 14px 38px rgba(27, 48, 78, .07);
    }
    .metric strong { display: block; font-size: 34px; line-height: 1; letter-spacing: -.04em; }
    .metric span { display: block; margin-top: 10px; color: #5b6c82; font-size: 17px; font-weight: 650; }
    .bento { display: grid; grid-template-columns: 1fr 1fr; grid-template-rows: 414px 258px; gap: 22px; }
    .panel {
      position: relative;
      overflow: hidden;
      border: 1px solid rgba(109, 128, 157, .24);
      border-radius: 25px;
      background: #f8fafc;
      box-shadow: 0 24px 55px rgba(20, 42, 74, .13);
    }
    .panel-main { grid-column: 1 / -1; }
    .panel img { width: 100%; height: 100%; object-fit: cover; display: block; }
    .panel-main img { object-position: 50% 27%; }
    .panel-analytics img { object-position: 50% 30%; }
    .panel-sources img { object-position: 50% 21%; }
    .panel::after {
      content: "";
      position: absolute;
      inset: 0;
      pointer-events: none;
      box-shadow: inset 0 0 0 1px rgba(255, 255, 255, .45);
    }
    .panel-label {
      position: absolute;
      z-index: 2;
      top: 16px;
      left: 16px;
      padding: 9px 13px;
      border-radius: 999px;
      color: #17233a;
      font-size: 16px;
      font-weight: 750;
      background: rgba(255, 255, 255, .92);
      border: 1px solid rgba(109, 128, 157, .22);
      box-shadow: 0 8px 20px rgba(20, 42, 74, .10);
    }
    .flow {
      position: relative;
      z-index: 1;
      display: grid;
      grid-template-columns: auto 1fr auto 1fr auto 1fr auto 1fr auto;
      align-items: center;
      gap: 14px;
      height: 72px;
      margin-top: 26px;
      padding: 0 24px;
      color: #eaf4ff;
      border-radius: 23px;
      background: linear-gradient(102deg, #12233c, #173c58);
      box-shadow: 0 20px 42px rgba(18, 35, 60, .20);
    }
    .flow span { font-size: 18px; font-weight: 700; white-space: nowrap; }
    .flow i { height: 1px; background: linear-gradient(90deg, rgba(255,255,255,.28), #22d3ee); }
    .snapshot { color: #a9bfd1; font-size: 15px !important; font-weight: 500 !important; }
  </style>
</head>
<body>
  <main class="poster" id="poster" aria-label="DevRadar product overview poster">
    <section class="layout">
      <div class="narrative">
        <div class="brand-row">
          <div class="brand-mark" aria-hidden="true">D</div>
          <div><div class="brand-name">DevRadar</div><div class="brand-sub">Job Market Intelligence</div></div>
        </div>
        <p class="eyebrow">EVIDENCE-LED JOB MARKET INTELLIGENCE</p>
        <h1>Từ job posting đến tín hiệu thị trường có thể kiểm chứng.</h1>
        <p class="summary">Một data pipeline có provenance cho ingestion, analytics và vận hành nguồn tuyển dụng.</p>
        <div class="metrics">
          <div class="metric"><strong>4</strong><span>Data sources</span></div>
          <div class="metric"><strong>23</strong><span>Tracked skills</span></div>
          <div class="metric"><strong>1,003</strong><span>Analyzed jobs</span></div>
          <div class="metric"><strong>0.9583</strong><span>Semantic Top-1</span></div>
        </div>
      </div>
      <div class="bento" aria-label="DevRadar interface views">
        <article class="panel panel-main">
          <span class="panel-label">Market overview</span>
          <img src="../../docs/assets/readme/dashboard-overview.png" alt="" />
        </article>
        <article class="panel panel-analytics">
          <span class="panel-label">Skill analytics</span>
          <img src="../../docs/assets/readme/analytics.png" alt="" />
        </article>
        <article class="panel panel-sources">
          <span class="panel-label">Bounded sources</span>
          <img src="../../docs/assets/readme/sources.png" alt="" />
        </article>
      </div>
    </section>
    <section class="flow" aria-label="DevRadar data flow">
      <span>Sources</span><i></i><span>Safe ingestion</span><i></i><span>PostgreSQL</span><i></i><span>Intelligence</span><i></i><span>Dashboard</span>
    </section>
  </main>
</body>
</html>
```

- [ ] **Step 2: Capture the exact poster preview with installed Edge**

Run from the worktree:

```powershell
$code = 'from pathlib import Path; from playwright.sync_api import sync_playwright; p=sync_playwright().start(); b=p.chromium.launch(channel="msedge"); page=b.new_page(viewport={"width":1600,"height":900}, device_scale_factor=1); page.goto(Path("output/readme-poster/poster.html").resolve().as_uri(), wait_until="load"); page.locator("#poster").screenshot(path="output/readme-poster/devradar-product-poster-preview.png", animations="disabled"); b.close(); p.stop()'
& 'C:\Users\PC\Documents\Duy\DevRadar\.venv\Scripts\python.exe' -c $code
```

Expected: one PNG at `1600×900` without browser chrome.

- [ ] **Step 3: Verify dimensions and file size**

Run:

```powershell
Add-Type -AssemblyName System.Drawing
$path = (Resolve-Path 'output/readme-poster/devradar-product-poster-preview.png').Path
$image = [System.Drawing.Image]::FromFile($path)
try {
    if ($image.Width -ne 1600 -or $image.Height -ne 900) { throw "Unexpected size $($image.Width)x$($image.Height)" }
} finally {
    $image.Dispose()
}
$bytes = (Get-Item $path).Length
if ($bytes -ge 1.5MB) { throw "Poster is too large: $bytes bytes" }
"poster=1600x900 bytes=$bytes"
```

Expected: `poster=1600x900`, size below `1.5MB`.

- [ ] **Step 4: Inspect at original and GitHub-like width**

Use `view_image` at original detail. Confirm:

- main headline and four metrics are readable;
- all three product areas are recognizable;
- no `V6`, PII, secret, browser chrome, fake UI, generated text, watermark or loading/error state;
- background is subordinate to UI and copy;
- no crop cuts a heading or key value awkwardly.

Render the preview at `838px` width in the conversation/app and confirm headline, metric values and panel labels remain readable.

### Task 3: Obtain explicit preview approval

**Files:**

- Review only: `output/readme-poster/devradar-product-poster-preview.png`

- [ ] **Step 1: Present the preview to the user**

Display the absolute preview path as an inline image and state that README has not been changed yet.

- [ ] **Step 2: Stop for user feedback**

Do not copy the preview into `docs/assets/readme/`, delete old assets, edit README, commit integration or push until the user explicitly approves this preview.

If the user requests changes, modify only the named visual property, recapture, re-run Task 2 Steps 3–4, and present a new preview.

### Task 4: Integrate the approved poster

**Files:**

- Create: `docs/assets/readme/devradar-product-poster.png`
- Modify: `README.md`
- Delete: `docs/assets/readme/dashboard-overview.png`
- Delete: `docs/assets/readme/analytics.png`
- Delete: `docs/assets/readme/sources.png`
- Test: `tests/test_custom_source_docs.py`

- [ ] **Step 1: Copy the approved binary into the repository**

Run:

```powershell
Copy-Item -LiteralPath output/readme-poster/devradar-product-poster-preview.png -Destination docs/assets/readme/devradar-product-poster.png
```

- [ ] **Step 2: Replace only the Product Showcase media block**

Keep the existing `<a id="product-showcase"></a>` and `## ◈ Product showcase` heading. Replace the overview image, caption and two-column `<table>` with:

```html
<p align="center">
  <img src="docs/assets/readme/devradar-product-poster.png" alt="DevRadar product poster kết hợp market overview, skill analytics và bounded custom-source workflow" width="100%" />
</p>

<p align="center"><sub>UI thật, metric có evidence và data flow có provenance — trong một product overview duy nhất.</sub></p>
```

- [ ] **Step 3: Delete obsolete full-page assets**

Run:

```powershell
git rm docs/assets/readme/dashboard-overview.png docs/assets/readme/analytics.png docs/assets/readme/sources.png
```

Expected: only `devradar-product-poster.png` remains under `docs/assets/readme/`.

- [ ] **Step 4: Run the narrow contract and no-version gates**

Run:

```powershell
& 'C:\Users\PC\Documents\Duy\DevRadar\.venv\Scripts\python.exe' -m pytest tests/test_custom_source_docs.py -q
$matches = @(Select-String -Path README.md -Pattern '\bV6(?:-|\b)')
if ($matches.Count -ne 0) { $matches; throw 'README still contains V6 labels' }
```

Expected: `4 passed`, no `V6` output.

- [ ] **Step 5: Commit the approved integration**

Run:

```powershell
git add README.md docs/assets/readme/devradar-product-poster.png
git diff --cached --check
git diff --cached --name-status
git commit -m "docs: replace README gallery with product poster"
```

Expected: commit contains one README modification, one new PNG and three deleted PNGs.

### Task 5: Verify, merge, push and inspect GitHub rendering

**Files:**

- Verify: `README.md`
- Verify: `docs/assets/readme/devradar-product-poster.png`
- Verify: `docs/superpowers/specs/2026-08-24-readme-product-poster-design.md`
- Verify: `docs/superpowers/plans/2026-08-24-readme-product-poster-implementation-plan.md`

- [ ] **Step 1: Check every README local target**

Run:

```powershell
$content = Get-Content -Raw README.md
$targets = @()
foreach ($match in [regex]::Matches($content, '!?\[[^\]]*\]\(([^)]+)\)')) { $targets += $match.Groups[1].Value.Trim() }
foreach ($match in [regex]::Matches($content, '(?:src|href)="([^"]+)"')) { $targets += $match.Groups[1].Value.Trim() }
$missing = @()
foreach ($target in $targets) {
    if ($target -match '^(https?://|mailto:|#)') { continue }
    $pathPart = [uri]::UnescapeDataString(($target -split '#', 2)[0])
    if ($pathPart -and -not (Test-Path -LiteralPath $pathPart)) { $missing += $target }
}
if ($missing.Count) { $missing | Sort-Object -Unique; throw 'Missing README targets' }
"local_targets=$($targets.Count)"
```

Expected: all targets exist; README points only to the new poster under `docs/assets/readme/`.

- [ ] **Step 2: Run final local gates**

Run:

```powershell
& 'C:\Users\PC\Documents\Duy\DevRadar\.venv\Scripts\python.exe' -m pytest tests/test_custom_source_docs.py -q
.\scripts\scan-secrets.ps1
git diff --check origin/main..HEAD
git status --short --branch
git diff --name-status origin/main..HEAD
git check-ignore -v TASK_BOARD.md .npm-cache 2>$null
```

Expected: `4 passed`, secret scan pass, diff check clean, scope limited to spec/plan/README/assets, task board ignored and `.npm-cache/` absent from commits.

- [ ] **Step 3: Merge and re-run verification on `main`**

Use `superpowers:finishing-a-development-branch` option 1 because the user already requested push to GitHub. Fast-forward merge `codex/readme-product-poster` into `main`, then re-run Task 5 Steps 1–2 from the main repository root before deleting the worktree/branch.

- [ ] **Step 4: Push and verify remote identity**

Run:

```powershell
git -c http.sslBackend=schannel push origin main
$local = git rev-parse HEAD
$remote = (git -c http.sslBackend=schannel ls-remote origin refs/heads/main).Split("`t")[0]
if ($local -ne $remote) { throw "Remote SHA mismatch: local=$local remote=$remote" }
git status --short --branch
```

Expected: push succeeds, local/remote SHA match, `.npm-cache/` remains untracked and `TASK_BOARD.md` remains ignored.

- [ ] **Step 5: Verify GitHub-rendered poster**

Open `https://github.com/HPhucTV/DevRadar`, wait for `.markdown-body`, and inspect:

- `.markdown-body img[alt^="DevRadar product poster"]` exists once;
- `naturalWidth=1600`, `naturalHeight=900`;
- obsolete image paths are absent from README DOM;
- poster is visually readable at GitHub content width;
- workflow run for the pushed SHA is reported as current state, without claiming success before completion.
