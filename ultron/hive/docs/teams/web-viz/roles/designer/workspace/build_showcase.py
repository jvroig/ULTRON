import sys

html_content = '''<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>ULTRON Architecture Showcase — Universal Layered Team &amp; Role Orchestration Network</title>
<style>
  :root {
    --font-sans: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif;
    --font-mono: ui-monospace, SFMono-Regular, "SF Mono", Menlo, Monaco, Consolas, "Liberation Mono", monospace;

    /* Base Theme: Light Mode */
    --bg-page: #f8fafc;
    --bg-surface: #ffffff;
    --bg-subtle: #f1f5f9;
    --bg-alt: #f8fafc;
    --border: #e2e8f0;
    --border-hover: #cbd5e1;
    --border-strong: #94a3b8;
    
    --text-main: #0f172a;
    --text-muted: #475569;
    --text-subtle: #64748b;
    --text-inverse: #ffffff;
    
    /* Semantic Colors */
    --prime-base: #b4232c;
    --prime-light: #fef2f2;
    --prime-border: #fecaca;
    --prime-text: #991b1b;
    
    --team-base: #1d5fb8;
    --team-light: #eff6ff;
    --team-border: #bfdbfe;
    --team-text: #1e40af;
    
    --spec-base: #475569;
    --spec-light: #f8fafc;
    --spec-border: #cbd5e1;
    --spec-text: #334155;
    
    --git-base: #059669;
    --git-light: #ecfdf5;
    --git-border: #a7f3d0;
    --git-text: #065f46;
    
    --runtime-base: #7c3aed;
    --runtime-light: #f5f3ff;
    --runtime-border: #ddd6fe;
    --runtime-text: #5b21b6;
    
    --board-base: #d97706;
    --board-light: #fffbeb;
    --board-border: #fde68a;
    --board-text: #92400e;

    --code-bg: #1e293b;
    --code-text: #f8fafc;
    --badge-bg: #e2e8f0;
    --badge-text: #1e293b;

    --shadow-sm: 0 1px 2px 0 rgba(0, 0, 0, 0.05);
    --shadow-md: 0 4px 6px -1px rgba(0, 0, 0, 0.07), 0 2px 4px -2px rgba(0, 0, 0, 0.05);
    --shadow-lg: 0 10px 15px -3px rgba(0, 0, 0, 0.08), 0 4px 6px -4px rgba(0, 0, 0, 0.04);
  }

  @media (prefers-color-scheme: dark) {
    :root:not([data-theme="light"]) {
      --bg-page: #0b0f17;
      --bg-surface: #131b26;
      --bg-subtle: #1a2433;
      --bg-alt: #16202e;
      --border: #243042;
      --border-hover: #334155;
      --border-strong: #475569;
      
      --text-main: #f1f5f9;
      --text-muted: #cbd5e1;
      --text-subtle: #94a3b8;
      
      --prime-base: #f87171;
      --prime-light: #2c1214;
      --prime-border: #5c1d24;
      --prime-text: #fca5a5;
      
      --team-base: #60a5fa;
      --team-light: #112238;
      --team-border: #1e3a5f;
      --team-text: #93c5fd;
      
      --spec-base: #94a3b8;
      --spec-light: #16202e;
      --spec-border: #2b3a4f;
      --spec-text: #cbd5e1;
      
      --git-base: #34d399;
      --git-light: #0d281e;
      --git-border: #134e3a;
      --git-text: #6ee7b7;
      
      --runtime-base: #a78bfa;
      --runtime-light: #251838;
      --runtime-border: #442a68;
      --runtime-text: #c4b5fd;
      
      --board-base: #fbbf24;
      --board-light: #2b2008;
      --board-border: #523b10;
      --board-text: #fde68a;

      --code-bg: #090d14;
      --code-text: #e2e8f0;
      --badge-bg: #243042;
      --badge-text: #e2e8f0;

      --shadow-sm: 0 1px 3px 0 rgba(0, 0, 0, 0.4);
      --shadow-md: 0 4px 8px -1px rgba(0, 0, 0, 0.5);
      --shadow-lg: 0 12px 20px -3px rgba(0, 0, 0, 0.6);
      color-scheme: dark;
    }
  }

  :root[data-theme="dark"] {
    --bg-page: #0b0f17;
    --bg-surface: #131b26;
    --bg-subtle: #1a2433;
    --bg-alt: #16202e;
    --border: #243042;
    --border-hover: #334155;
    --border-strong: #475569;
    
    --text-main: #f1f5f9;
    --text-muted: #cbd5e1;
    --text-subtle: #94a3b8;
    
    --prime-base: #f87171;
    --prime-light: #2c1214;
    --prime-border: #5c1d24;
    --prime-text: #fca5a5;
    
    --team-base: #60a5fa;
    --team-light: #112238;
    --team-border: #1e3a5f;
    --team-text: #93c5fd;
    
    --spec-base: #94a3b8;
    --spec-light: #16202e;
    --spec-border: #2b3a4f;
    --spec-text: #cbd5e1;
    
    --git-base: #34d399;
    --git-light: #0d281e;
    --git-border: #134e3a;
    --git-text: #6ee7b7;
    
    --runtime-base: #a78bfa;
    --runtime-light: #251838;
    --runtime-border: #442a68;
    --runtime-text: #c4b5fd;
    
    --board-base: #fbbf24;
    --board-light: #2b2008;
    --board-border: #523b10;
    --board-text: #fde68a;

    --code-bg: #090d14;
    --code-text: #e2e8f0;
    --badge-bg: #243042;
    --badge-text: #e2e8f0;

    --shadow-sm: 0 1px 3px 0 rgba(0, 0, 0, 0.4);
    --shadow-md: 0 4px 8px -1px rgba(0, 0, 0, 0.5);
    --shadow-lg: 0 12px 20px -3px rgba(0, 0, 0, 0.6);
    color-scheme: dark;
  }

  :root[data-theme="light"] {
    --bg-page: #f8fafc;
    --bg-surface: #ffffff;
    --bg-subtle: #f1f5f9;
    --bg-alt: #f8fafc;
    --border: #e2e8f0;
    --border-hover: #cbd5e1;
    --border-strong: #94a3b8;
    
    --text-main: #0f172a;
    --text-muted: #475569;
    --text-subtle: #64748b;
    
    --prime-base: #b4232c;
    --prime-light: #fef2f2;
    --prime-border: #fecaca;
    --prime-text: #991b1b;
    
    --team-base: #1d5fb8;
    --team-light: #eff6ff;
    --team-border: #bfdbfe;
    --team-text: #1e40af;
    
    --spec-base: #475569;
    --spec-light: #f8fafc;
    --spec-border: #cbd5e1;
    --spec-text: #334155;
    
    --git-base: #059669;
    --git-light: #ecfdf5;
    --git-border: #a7f3d0;
    --git-text: #065f46;
    
    --runtime-base: #7c3aed;
    --runtime-light: #f5f3ff;
    --runtime-border: #ddd6fe;
    --runtime-text: #5b21b6;
    
    --board-base: #d97706;
    --board-light: #fffbeb;
    --board-border: #fde68a;
    --board-text: #92400e;

    --code-bg: #1e293b;
    --code-text: #f8fafc;
    --badge-bg: #e2e8f0;
    --badge-text: #1e293b;
    color-scheme: light;
  }

  * { box-sizing: border-box; margin: 0; padding: 0; }
  
  body {
    font-family: var(--font-sans);
    background-color: var(--bg-page);
    color: var(--text-main);
    line-height: 1.6;
    padding: 24px 16px;
    font-size: 15px;
    -webkit-font-smoothing: antialiased;
  }

  .container {
    max-width: 1060px;
    margin: 0 auto;
  }

  /* Header & Navigation */
  header {
    background: var(--bg-surface);
    border: 1px solid var(--border);
    border-radius: 16px;
    padding: 24px;
    margin-bottom: 24px;
    box-shadow: var(--shadow-sm);
  }

  .header-top {
    display: flex;
    justify-content: space-between;
    align-items: flex-start;
    flex-wrap: wrap;
    gap: 16px;
  }

  .brand-group h1 {
    font-size: 1.85rem;
    font-weight: 800;
    letter-spacing: -0.03em;
    display: flex;
    align-items: center;
    gap: 10px;
  }

  .brand-dot {
    width: 12px;
    height: 12px;
    border-radius: 50%;
    background: var(--prime-base);
    display: inline-block;
  }

  .header-desc {
    color: var(--text-muted);
    font-size: 0.95rem;
    margin-top: 6px;
    font-weight: 500;
  }

  .theme-switcher {
    display: flex;
    background: var(--bg-subtle);
    border: 1px solid var(--border);
    border-radius: 10px;
    padding: 3px;
    gap: 2px;
  }

  .theme-btn {
    border: none;
    background: transparent;
    color: var(--text-muted);
    font-size: 0.78rem;
    font-weight: 600;
    padding: 5px 12px;
    border-radius: 7px;
    cursor: pointer;
    transition: all 0.15s ease;
  }

  .theme-btn:hover {
    color: var(--text-main);
  }

  .theme-btn.active {
    background: var(--bg-surface);
    color: var(--text-main);
    box-shadow: var(--shadow-sm);
  }

  .meta-chips {
    display: flex;
    flex-wrap: wrap;
    gap: 8px;
    margin-top: 16px;
    padding-top: 16px;
    border-top: 1px solid var(--border);
  }

  .chip {
    display: inline-flex;
    align-items: center;
    gap: 6px;
    padding: 4px 10px;
    border-radius: 20px;
    font-size: 0.75rem;
    font-weight: 600;
    background: var(--bg-subtle);
    border: 1px solid var(--border);
    color: var(--text-muted);
  }

  .chip.prime { background: var(--prime-light); border-color: var(--prime-border); color: var(--prime-text); }
  .chip.git { background: var(--git-light); border-color: var(--git-border); color: var(--git-text); }
  .chip.runtime { background: var(--runtime-light); border-color: var(--runtime-border); color: var(--runtime-text); }
  .chip.team { background: var(--team-light); border-color: var(--team-border); color: var(--team-text); }

  /* Section Anchor Nav */
  .quicknav {
    display: flex;
    gap: 8px;
    overflow-x: auto;
    padding: 4px 0 16px;
    margin-bottom: 8px;
  }

  .quicknav a {
    color: var(--text-muted);
    text-decoration: none;
    font-size: 0.8rem;
    font-weight: 600;
    padding: 6px 14px;
    background: var(--bg-surface);
    border: 1px solid var(--border);
    border-radius: 8px;
    white-space: nowrap;
    transition: all 0.15s ease;
  }

  .quicknav a:hover {
    color: var(--team-base);
    border-color: var(--team-base);
    background: var(--bg-subtle);
  }

  /* Cards & Sections */
  .section-card {
    background: var(--bg-surface);
    border: 1px solid var(--border);
    border-radius: 16px;
    padding: 24px;
    margin-bottom: 24px;
    box-shadow: var(--shadow-sm);
  }

  .section-header {
    margin-bottom: 18px;
  }

  .section-title {
    font-size: 1.25rem;
    font-weight: 700;
    letter-spacing: -0.02em;
    display: flex;
    align-items: center;
    gap: 8px;
  }

  .section-sub {
    color: var(--text-subtle);
    font-size: 0.86rem;
    margin-top: 4px;
  }

  /* Identity Cards */
  .identity-grid {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(320px, 1fr));
    gap: 16px;
    margin-bottom: 20px;
  }

  .hero-id-card {
    border-radius: 12px;
    padding: 18px;
    border: 1px solid var(--border);
    background: var(--bg-alt);
    position: relative;
    overflow: hidden;
  }

  .hero-id-card.prime-card {
    border-color: var(--prime-border);
    background: var(--prime-light);
  }

  .hero-id-card.network-card {
    border-color: var(--team-border);
    background: var(--team-light);
  }

  .id-label {
    font-size: 0.7rem;
    font-weight: 800;
    text-transform: uppercase;
    letter-spacing: 0.08em;
    margin-bottom: 6px;
    display: inline-block;
  }

  .prime-card .id-label { color: var(--prime-base); }
  .network-card .id-label { color: var(--team-base); }

  .id-title {
    font-size: 1.15rem;
    font-weight: 800;
    line-height: 1.3;
    margin-bottom: 8px;
  }

  .id-desc {
    font-size: 0.85rem;
    color: var(--text-muted);
  }

  /* Acronym Breakdown Grid */
  .acronym-grid {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(150px, 1fr));
    gap: 12px;
    margin-top: 14px;
  }

  .letter-card {
    background: var(--bg-surface);
    border: 1px solid var(--border);
    border-radius: 10px;
    padding: 12px;
    transition: transform 0.15s ease, border-color 0.15s ease;
  }

  .letter-card:hover {
    transform: translateY(-2px);
    border-color: var(--border-hover);
    box-shadow: var(--shadow-sm);
  }

  .letter-header {
    display: flex;
    align-items: baseline;
    gap: 6px;
    margin-bottom: 4px;
  }

  .letter-char {
    font-size: 1.4rem;
    font-weight: 900;
    font-family: var(--font-mono);
    color: var(--prime-base);
  }

  .letter-word {
    font-weight: 700;
    font-size: 0.88rem;
    color: var(--text-main);
  }

  .letter-body {
    font-size: 0.78rem;
    color: var(--text-muted);
    line-height: 1.4;
  }

  /* SVG Diagrams */
  .diagram-container {
    background: var(--bg-alt);
    border: 1px solid var(--border);
    border-radius: 14px;
    padding: 20px;
    margin-top: 16px;
  }

  .svg-wrap {
    width: 100%;
    overflow-x: auto;
    padding-bottom: 8px;
  }

  .svg-wrap svg {
    display: block;
    margin: 0 auto;
    max-width: 100%;
    height: auto;
  }

  /* Storage Dual-Zone */
  .storage-grid {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(320px, 1fr));
    gap: 20px;
    margin-top: 16px;
  }

  .storage-zone {
    border-radius: 14px;
    border: 1px solid var(--border);
    padding: 20px;
    background: var(--bg-surface);
    position: relative;
  }

  .storage-zone.git-zone {
    border-top: 4px solid var(--git-base);
  }

  .storage-zone.runtime-zone {
    border-top: 4px solid var(--runtime-base);
  }

  .zone-badge {
    display: inline-flex;
    align-items: center;
    gap: 6px;
    font-size: 0.72rem;
    font-weight: 800;
    text-transform: uppercase;
    letter-spacing: 0.05em;
    padding: 3px 8px;
    border-radius: 6px;
    margin-bottom: 12px;
  }

  .git-zone .zone-badge { background: var(--git-light); color: var(--git-text); }
  .runtime-zone .zone-badge { background: var(--runtime-light); color: var(--runtime-text); }

  .zone-title {
    font-size: 1.1rem;
    font-weight: 700;
    margin-bottom: 8px;
  }

  .file-item {
    font-family: var(--font-mono);
    font-size: 0.78rem;
    padding: 8px 10px;
    background: var(--bg-subtle);
    border-radius: 6px;
    margin-bottom: 8px;
    border-left: 3px solid var(--border-strong);
  }

  .file-item.highlight-git { border-left-color: var(--git-base); }
  .file-item.highlight-runtime { border-left-color: var(--runtime-base); }

  .file-name { font-weight: 700; color: var(--text-main); }
  .file-desc { color: var(--text-muted); font-family: var(--font-sans); font-size: 0.74rem; margin-top: 2px; }

  /* Visibility Matrix */
  .matrix-table-wrap {
    overflow-x: auto;
    margin-top: 16px;
    border: 1px solid var(--border);
    border-radius: 10px;
  }

  table.matrix-table {
    width: 100%;
    border-collapse: collapse;
    font-size: 0.84rem;
    text-align: left;
  }

  table.matrix-table th {
    background: var(--bg-subtle);
    color: var(--text-muted);
    font-weight: 700;
    font-size: 0.7rem;
    text-transform: uppercase;
    letter-spacing: 0.05em;
    padding: 10px 12px;
    border-bottom: 1px solid var(--border);
  }

  table.matrix-table td {
    padding: 12px;
    border-bottom: 1px solid var(--border);
    vertical-align: top;
  }

  table.matrix-table tr:last-child td {
    border-bottom: none;
  }

  .scope-pill {
    display: inline-block;
    padding: 3px 8px;
    border-radius: 6px;
    font-family: var(--font-mono);
    font-weight: 700;
    font-size: 0.72rem;
  }

  .scope-personal { background: #ede9fe; color: #5b21b6; }
  .scope-team { background: #dbeafe; color: #1e40af; }
  .scope-cross { background: #dcfce7; color: #166534; }
  .scope-global { background: #fef3c7; color: #92400e; }

  [data-theme="dark"] .scope-personal { background: #2e1c4a; color: #c4b5fd; }
  [data-theme="dark"] .scope-team { background: #172a45; color: #93c5fd; }
  [data-theme="dark"] .scope-cross { background: #133323; color: #86efac; }
  [data-theme="dark"] .scope-global { background: #3d2a07; color: #fde68a; }

  @media (prefers-color-scheme: dark) {
    :root:not([data-theme="light"]) .scope-personal { background: #2e1c4a; color: #c4b5fd; }
    :root:not([data-theme="light"]) .scope-team { background: #172a45; color: #93c5fd; }
    :root:not([data-theme="light"]) .scope-cross { background: #133323; color: #86efac; }
    :root:not([data-theme="light"]) .scope-global { background: #3d2a07; color: #fde68a; }
  }

  /* Doorbell Steps */
  .doorbell-flow {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(240px, 1fr));
    gap: 16px;
    margin-top: 18px;
    position: relative;
  }

  .flow-step-card {
    background: var(--bg-alt);
    border: 1px solid var(--border);
    border-radius: 12px;
    padding: 16px;
    position: relative;
  }

  .step-number {
    width: 24px;
    height: 24px;
    border-radius: 50%;
    background: var(--prime-base);
    color: #fff;
    font-weight: 800;
    font-size: 0.75rem;
    display: flex;
    align-items: center;
    justify-content: center;
    margin-bottom: 8px;
  }

  .step-title {
    font-weight: 700;
    font-size: 0.95rem;
    margin-bottom: 6px;
  }

  .step-desc {
    font-size: 0.8rem;
    color: var(--text-muted);
    line-height: 1.45;
  }

  .code-pill {
    font-family: var(--font-mono);
    font-size: 0.72rem;
    background: var(--bg-subtle);
    border: 1px solid var(--border);
    padding: 2px 6px;
    border-radius: 4px;
    color: var(--text-main);
  }

  /* Lifecycle Loop */
  .pipeline-track {
    display: flex;
    flex-direction: column;
    gap: 10px;
    margin-top: 16px;
  }

  .pipeline-stage {
    display: flex;
    align-items: flex-start;
    gap: 14px;
    padding: 12px 16px;
    background: var(--bg-alt);
    border: 1px solid var(--border);
    border-radius: 10px;
  }

  .stage-badge {
    font-family: var(--font-mono);
    font-size: 0.72rem;
    font-weight: 700;
    padding: 4px 8px;
    border-radius: 6px;
    background: var(--team-light);
    color: var(--team-text);
    border: 1px solid var(--team-border);
    white-space: nowrap;
    min-width: 110px;
    text-align: center;
  }

  .stage-badge.kill {
    background: var(--prime-light);
    color: var(--prime-text);
    border-color: var(--prime-border);
  }

  .stage-info {
    flex: 1;
  }

  .stage-title {
    font-weight: 700;
    font-size: 0.88rem;
    margin-bottom: 2px;
  }

  .stage-desc {
    font-size: 0.78rem;
    color: var(--text-muted);
  }

  /* CLI Terminal Block */
  .cli-block {
    background: var(--code-bg);
    color: var(--code-text);
    border-radius: 12px;
    padding: 16px;
    font-family: var(--font-mono);
    font-size: 0.78rem;
    line-height: 1.5;
    overflow-x: auto;
    margin-top: 14px;
    position: relative;
    box-shadow: var(--shadow-md);
  }

  .cli-comment { color: #64748b; }
  .cli-cmd { color: #38bdf8; font-weight: 600; }
  .cli-arg { color: #f1f5f9; }
  .cli-flag { color: #a78bfa; }
  .cli-val { color: #34d399; }

  /* Callout box */
  .callout-box {
    margin-top: 16px;
    padding: 14px 18px;
    border-radius: 10px;
    border-left: 4px solid var(--prime-base);
    background: var(--prime-light);
    color: var(--prime-text);
    font-size: 0.84rem;
  }

  .callout-box.info {
    border-left-color: var(--team-base);
    background: var(--team-light);
    color: var(--team-text);
  }

  .callout-box.git {
    border-left-color: var(--git-base);
    background: var(--git-light);
    color: var(--git-text);
  }

  .callout-title {
    font-weight: 700;
    margin-bottom: 4px;
    display: flex;
    align-items: center;
    gap: 6px;
  }

  /* Footer */
  footer {
    text-align: center;
    padding: 24px 0 12px;
    color: var(--text-subtle);
    font-size: 0.8rem;
  }

  .footer-sub {
    font-size: 0.72rem;
    margin-top: 4px;
  }

  /* Interactive Tab Strip for CLI */
  .tab-strip {
    display: flex;
    gap: 4px;
    border-bottom: 1px solid var(--border);
    margin-bottom: 12px;
  }

  .tab-btn {
    background: transparent;
    border: none;
    padding: 8px 14px;
    font-size: 0.8rem;
    font-weight: 600;
    color: var(--text-muted);
    cursor: pointer;
    border-bottom: 2px solid transparent;
    transition: all 0.15s ease;
  }

  .tab-btn:hover {
    color: var(--text-main);
  }

  .tab-btn.active {
    color: var(--team-base);
    border-bottom-color: var(--team-base);
  }

  .tab-panel {
    display: none;
  }

  .tab-panel.active {
    display: block;
  }

</style>
</head>
<body>

<div class="container">

  <!-- Top Header Banner -->
  <header>
    <div class="header-top">
      <div class="brand-group">
        <h1><span class="brand-dot"></span> ULTRON Architecture Showcase</h1>
        <div class="header-desc">Universal Layered Team &amp; Role Orchestration Network &middot; As-Implemented Architecture</div>
      </div>
      <div class="theme-switcher">
        <button class="theme-btn" id="btn-theme-light" onclick="setTheme('light')">☀️ Light</button>
        <button class="theme-btn" id="btn-theme-dark" onclick="setTheme('dark')">🌙 Dark</button>
        <button class="theme-btn" id="btn-theme-auto" onclick="setTheme('auto')">💻 Auto</button>
      </div>
    </div>
    <div class="meta-chips">
      <span class="chip prime">👑 ULTRON PRIME (Layer 0)</span>
      <span class="chip team">🏢 N-Layer Recursive Hive</span>
      <span class="chip git">🌿 Pure Git-Native (merge=union)</span>
      <span class="chip runtime">⚡ Zero-Poll Reactive Doorbells</span>
      <span class="chip">🛡️ Dynamic Resource Conservation</span>
    </div>
  </header>

  <!-- Quick Navigation Bar -->
  <nav class="quicknav">
    <a href="#names">1. Identity &amp; Acronyms</a>
    <a href="#hierarchy">2. N-Layer Hive Topology</a>
    <a href="#storage">3. Pure Git-Native Storage</a>
    <a href="#visibility">4. Visibility &amp; Doorbells</a>
    <a href="#lifecycle">5. Lifecycle &amp; Conservation</a>
    <a href="#cli">6. CLI Reference</a>
  </nav>

  <!-- Section 1: Names & Acronyms -->
  <section id="names" class="section-card">
    <div class="section-header">
      <h2 class="section-title">1. Names &amp; Architectural Acronyms</h2>
      <div class="section-sub">The guiding vision and semantic foundation of ULTRON.</div>
    </div>

    <div class="identity-grid">
      <div class="hero-id-card network-card">
        <span class="id-label">The Autonomous Agent Network</span>
        <div class="id-title">ULTRON</div>
        <div class="id-desc"><strong>Universal Layered Team and Role Orchestration Network</strong> &mdash; A modular, recursive multi-agent orchestration architecture designed for high autonomy, structured collaboration, and resource efficiency on top of agentic harnesses.</div>
      </div>
      <div class="hero-id-card prime-card">
        <span class="id-label">Root Orchestrator &middot; Layer 0</span>
        <div class="id-title">ULTRON PRIME</div>
        <div class="id-desc"><strong>Ultimate Leader of Teams, Roles, and Operational Nodes</strong> &mdash; The single point of contact with the human User, holding sole provisioning, spawning, and teardown authority over all Hive teams and roles.</div>
      </div>
    </div>

    <!-- Letter breakdown -->
    <div class="acronym-grid">
      <div class="letter-card">
        <div class="letter-header">
          <span class="letter-char">U</span>
          <span class="letter-word">Universal</span>
        </div>
        <div class="letter-body">Not bound to a single vertical. Any domain capability (code, docs, secops, QA) plugs in as an autonomous team.</div>
      </div>
      <div class="letter-card">
        <div class="letter-header">
          <span class="letter-char">L</span>
          <span class="letter-word">Layered</span>
        </div>
        <div class="letter-body">Arbitrary <code>N</code>-layer hierarchy. Delegation cascades downward; reporting and escalations flow strictly upward.</div>
      </div>
      <div class="letter-card">
        <div class="letter-header">
          <span class="letter-char">T</span>
          <span class="letter-word">Team</span>
        </div>
        <div class="letter-body">Teams are the atomic unit of work. No unmanaged lone agents; roles collaborate in structured pods.</div>
      </div>
      <div class="letter-card">
        <div class="letter-header">
          <span class="letter-char">R</span>
          <span class="letter-word">Role</span>
        </div>
        <div class="letter-body">Flat peer specialist roles inside teams, led by a mandatory <code>&lt;team&gt;/lead</code> as internal coordinator and external bridge.</div>
      </div>
      <div class="letter-card">
        <div class="letter-header">
          <span class="letter-char">O</span>
          <span class="letter-word">Orchestration</span>
        </div>
        <div class="letter-body">Autonomous delegation, reactive doorbells, and clean teardown/reactivation for maximal resource conservation.</div>
      </div>
      <div class="letter-card">
        <div class="letter-header">
          <span class="letter-char">N</span>
          <span class="letter-word">Network</span>
        </div>
        <div class="letter-body">Pure Git-native append-only event board (<code>threads/*.jsonl</code>) and doorbells linking all operational nodes.</div>
      </div>
    </div>
  </section>

  <!-- Section 2: N-Layer Hive Hierarchy -->
  <section id="hierarchy" class="section-card">
    <div class="section-header">
      <h2 class="section-title">2. N-Layer Hive Hierarchy &amp; Chain of Command</h2>
      <div class="section-sub">Corporate org-chart topology: flat intra-team peer collaboration with strict upward escalation.</div>
    </div>

    <p style="font-size:0.88rem; color:var(--text-muted); margin-bottom:14px;">
      ULTRON organizes agents into an arbitrary-depth tree under <code>ultron/hive/</code>. Layer 1 teams report directly to <strong>ULTRON PRIME</strong>. Deeper sub-teams (<code>Layer 2..N</code>) attach under any parent team via <code>--parent &lt;parent-slug&gt;</code>. Inside any team, specialist roles are <strong>flat peers</strong>. Every team features a mandatory <strong><code>lead</code></strong> who acts as the internal coordinator and the <strong>sole external communication bridge</strong>.
    </p>

    <div class="diagram-container">
      <div class="svg-wrap">
        <svg viewBox="0 0 960 480" width="960" height="480" xmlns="http://www.w3.org/2000/svg">
          <defs>
            <marker id="arrow-down" viewBox="0 0 10 10" refX="6" refY="5" markerWidth="6" markerHeight="6" orient="auto-start-reverse">
              <path d="M 0 1 L 8 5 L 0 9 z" fill="var(--team-base)" />
            </marker>
            <marker id="arrow-up" viewBox="0 0 10 10" refX="6" refY="5" markerWidth="6" markerHeight="6" orient="auto-start-reverse">
              <path d="M 0 1 L 8 5 L 0 9 z" fill="var(--prime-base)" />
            </marker>
            <filter id="card-shadow" x="-5%" y="-5%" width="110%" height="115%">
              <feDropShadow dx="0" dy="2" stdDeviation="3" flood-opacity="0.08" />
            </filter>
          </defs>

          <!-- Layer Bands (Subtle background stripes) -->
          <rect x="10" y="10" width="940" height="60" rx="8" fill="var(--bg-subtle)" stroke="var(--border)" stroke-dasharray="4" />
          <text x="24" y="45" font-family="sans-serif" font-size="11" font-weight="700" fill="var(--text-subtle)" letter-spacing="1">LAYER 0 &middot; ROOT ORCHESTRATION</text>

          <rect x="10" y="105" width="940" height="155" rx="8" fill="var(--bg-subtle)" stroke="var(--border)" stroke-dasharray="4" />
          <text x="24" y="130" font-family="sans-serif" font-size="11" font-weight="700" fill="var(--text-subtle)" letter-spacing="1">LAYER 1 &middot; PARENT TEAMS (docs, platform)</text>

          <rect x="10" y="295" width="940" height="175" rx="8" fill="var(--bg-subtle)" stroke="var(--border)" stroke-dasharray="4" />
          <text x="24" y="320" font-family="sans-serif" font-size="11" font-weight="700" fill="var(--text-subtle)" letter-spacing="1">LAYER 2..N &middot; RECURSIVE SUB-TEAMS (web-viz, auth)</text>

          <!-- User Node -->
          <g transform="translate(180, 20)">
            <rect width="130" height="40" rx="8" fill="var(--bg-surface)" stroke="var(--border-strong)" stroke-width="1.5" filter="url(#card-shadow)" />
            <text x="65" y="25" text-anchor="middle" font-family="sans-serif" font-size="13" font-weight="700" fill="var(--text-main)">👤 User</text>
          </g>

          <!-- Direct User <-> PRIME link -->
          <line x1="315" y1="40" x2="435" y2="40" stroke="var(--border-strong)" stroke-width="2" stroke-dasharray="2 3" />
          <text x="375" y="34" text-anchor="middle" font-family="sans-serif" font-size="9" font-weight="700" fill="var(--text-subtle)">Single Point of Contact</text>

          <!-- ULTRON PRIME Node -->
          <g transform="translate(440, 16)">
            <rect width="280" height="48" rx="10" fill="var(--prime-light)" stroke="var(--prime-border)" stroke-width="2" filter="url(#card-shadow)" />
            <text x="140" y="27" text-anchor="middle" font-family="sans-serif" font-size="13" font-weight="800" fill="var(--prime-text)">👑 ULTRON PRIME</text>
            <text x="140" y="42" text-anchor="middle" font-family="sans-serif" font-size="9" font-weight="600" fill="var(--prime-base)">Root Orchestrator &middot; Sole Provisioning Authority</text>
          </g>

          <!-- Delegation down to Layer 1 -->
          <path d="M 520,64 L 520,85 L 260,85 L 260,115" fill="none" stroke="var(--team-base)" stroke-width="2" marker-end="url(#arrow-down)" />
          <path d="M 640,64 L 640,85 L 700,85 L 700,115" fill="none" stroke="var(--team-base)" stroke-width="2" marker-end="url(#arrow-down)" />

          <!-- TEAM 1: docs (Layer 1) -->
          <g transform="translate(60, 120)">
            <rect width="400" height="125" rx="12" fill="var(--bg-surface)" stroke="var(--team-border)" stroke-width="1.5" filter="url(#card-shadow)" />
            <rect x="0" y="0" width="400" height="28" rx="12" fill="var(--team-light)" />
            <text x="14" y="19" font-family="sans-serif" font-size="11" font-weight="800" fill="var(--team-text)">TEAM: docs &middot; Technical Documentation</text>
            <text x="385" y="19" text-anchor="end" font-family="sans-serif" font-size="9" font-weight="700" fill="var(--team-base)">LAYER 1</text>

            <!-- Roles inside docs -->
            <!-- docs/lead -->
            <g transform="translate(16, 38)">
              <rect width="170" height="68" rx="8" fill="var(--team-light)" stroke="var(--team-base)" stroke-width="1.5" />
              <text x="12" y="22" font-family="monospace" font-size="11" font-weight="700" fill="var(--team-text)">docs/lead</text>
              <text x="12" y="38" font-family="sans-serif" font-size="9" font-weight="700" fill="var(--team-base)">Team Leader</text>
              <text x="12" y="54" font-family="sans-serif" font-size="8" fill="var(--text-muted)">Sole External Bridge &amp; Coordinator</text>
            </g>

            <!-- Horizontal peer connector -->
            <line x1="188" y1="72" x2="216" y2="72" stroke="var(--border-strong)" stroke-width="2" stroke-dasharray="3" />

            <!-- docs/writer (Specialist) -->
            <g transform="translate(218, 38)">
              <rect width="165" height="68" rx="8" fill="var(--spec-light)" stroke="var(--spec-border)" stroke-width="1.2" />
              <text x="12" y="22" font-family="monospace" font-size="11" font-weight="700" fill="var(--spec-text)">docs/writer</text>
              <text x="12" y="38" font-family="sans-serif" font-size="9" font-weight="700" fill="var(--text-subtle)">Technical Writer</text>
              <text x="12" y="54" font-family="sans-serif" font-size="8" fill="var(--text-muted)">Flat Peer Role &middot; Docs Authoring</text>
            </g>
          </g>

          <!-- TEAM 2: platform (Layer 1) -->
          <g transform="translate(490, 120)">
            <rect width="420" height="125" rx="12" fill="var(--bg-surface)" stroke="var(--team-border)" stroke-width="1.5" filter="url(#card-shadow)" />
            <rect x="0" y="0" width="420" height="28" rx="12" fill="var(--team-light)" />
            <text x="14" y="19" font-family="sans-serif" font-size="11" font-weight="800" fill="var(--team-text)">TEAM: platform &middot; Core Platform &amp; APIs</text>
            <text x="405" y="19" text-anchor="end" font-family="sans-serif" font-size="9" font-weight="700" fill="var(--team-base)">LAYER 1</text>

            <!-- platform/lead -->
            <g transform="translate(14, 38)">
              <rect width="140" height="68" rx="8" fill="var(--team-light)" stroke="var(--team-base)" stroke-width="1.5" />
              <text x="10" y="22" font-family="monospace" font-size="10.5" font-weight="700" fill="var(--team-text)">platform/lead</text>
              <text x="10" y="38" font-family="sans-serif" font-size="9" font-weight="700" fill="var(--team-base)">Team Leader</text>
              <text x="10" y="54" font-family="sans-serif" font-size="8" fill="var(--text-muted)">Internal Lead &amp; Bridge</text>
            </g>

            <line x1="156" y1="72" x2="168" y2="72" stroke="var(--border-strong)" stroke-width="1.5" stroke-dasharray="3" />

            <!-- platform/coder -->
            <g transform="translate(170, 38)">
              <rect width="115" height="68" rx="8" fill="var(--spec-light)" stroke="var(--spec-border)" stroke-width="1.2" />
              <text x="8" y="22" font-family="monospace" font-size="10" font-weight="700" fill="var(--spec-text)">platform/coder</text>
              <text x="8" y="38" font-family="sans-serif" font-size="8.5" font-weight="700" fill="var(--text-subtle)">Backend Dev</text>
              <text x="8" y="54" font-family="sans-serif" font-size="7.5" fill="var(--text-muted)">Flat Peer Specialist</text>
            </g>

            <line x1="287" y1="72" x2="297" y2="72" stroke="var(--border-strong)" stroke-width="1.5" stroke-dasharray="3" />

            <!-- platform/reviewer -->
            <g transform="translate(299, 38)">
              <rect width="110" height="68" rx="8" fill="var(--spec-light)" stroke="var(--spec-border)" stroke-width="1.2" />
              <text x="8" y="22" font-family="monospace" font-size="9.5" font-weight="700" fill="var(--spec-text)">platform/reviewer</text>
              <text x="8" y="38" font-family="sans-serif" font-size="8.5" font-weight="700" fill="var(--text-subtle)">Code Auditor</text>
              <text x="8" y="54" font-family="sans-serif" font-size="7.5" fill="var(--text-muted)">Read-Only Tier-2</text>
            </g>
          </g>

          <!-- Sub-Team Link: docs -> web-viz -->
          <path d="M 160,245 L 160,310" fill="none" stroke="var(--team-base)" stroke-width="2" marker-end="url(#arrow-down)" />
          <path d="M 180,310 L 180,250" fill="none" stroke="var(--prime-base)" stroke-width="1.5" stroke-dasharray="4" marker-end="url(#arrow-up)" />
          <text x="195" y="280" font-family="sans-serif" font-size="8.5" font-weight="700" fill="var(--prime-base)">Escalation Up</text>

          <!-- Sub-Team Link: platform -> auth -->
          <path d="M 680,245 L 680,310" fill="none" stroke="var(--team-base)" stroke-width="2" marker-end="url(#arrow-down)" />
          <path d="M 700,310 L 700,250" fill="none" stroke="var(--prime-base)" stroke-width="1.5" stroke-dasharray="4" marker-end="url(#arrow-up)" />
          <text x="715" y="280" font-family="sans-serif" font-size="8.5" font-weight="700" fill="var(--prime-base)">Escalation Up</text>

          <!-- TEAM 3: web-viz (Layer 2 under docs) -->
          <g transform="translate(60, 315)">
            <rect width="400" height="135" rx="12" fill="var(--bg-surface)" stroke="var(--team-border)" stroke-width="1.5" filter="url(#card-shadow)" />
            <rect x="0" y="0" width="400" height="28" rx="12" fill="var(--team-light)" />
            <text x="14" y="19" font-family="sans-serif" font-size="11" font-weight="800" fill="var(--team-text)">SUB-TEAM: web-viz &middot; Visual Architecture Showcase</text>
            <text x="385" y="19" text-anchor="end" font-family="sans-serif" font-size="9" font-weight="700" fill="var(--team-base)">LAYER 2</text>

            <!-- web-viz/lead -->
            <g transform="translate(16, 42)">
              <rect width="170" height="75" rx="8" fill="var(--team-light)" stroke="var(--team-base)" stroke-width="1.5" />
              <text x="12" y="22" font-family="monospace" font-size="11" font-weight="700" fill="var(--team-text)">web-viz/lead</text>
              <text x="12" y="38" font-family="sans-serif" font-size="9" font-weight="700" fill="var(--team-base)">Team Leader</text>
              <text x="12" y="52" font-family="sans-serif" font-size="8" fill="var(--text-muted)">Coordinates Showcase</text>
              <text x="12" y="65" font-family="sans-serif" font-size="8" font-weight="700" fill="var(--team-text)">Sole Bridge to docs/lead</text>
            </g>

            <line x1="188" y1="80" x2="216" y2="80" stroke="var(--border-strong)" stroke-width="2" stroke-dasharray="3" />

            <!-- web-viz/designer -->
            <g transform="translate(218, 42)">
              <rect width="165" height="75" rx="8" fill="var(--spec-light)" stroke="var(--spec-border)" stroke-width="1.2" />
              <text x="12" y="22" font-family="monospace" font-size="11" font-weight="700" fill="var(--spec-text)">web-viz/designer</text>
              <text x="12" y="38" font-family="sans-serif" font-size="9" font-weight="700" fill="var(--text-subtle)">HTML &amp; Diagram Specialist</text>
              <text x="12" y="52" font-family="sans-serif" font-size="8" fill="var(--text-muted)">Builds Architecture Showcase</text>
              <text x="12" y="65" font-family="sans-serif" font-size="8" font-weight="600" fill="var(--prime-text)">Reports strictly to web-viz/lead</text>
            </g>
          </g>

          <!-- TEAM 4: auth (Layer 2 under platform) -->
          <g transform="translate(490, 315)">
            <rect width="420" height="135" rx="12" fill="var(--bg-surface)" stroke="var(--team-border)" stroke-width="1.5" filter="url(#card-shadow)" />
            <rect x="0" y="0" width="420" height="28" rx="12" fill="var(--team-light)" />
            <text x="14" y="19" font-family="sans-serif" font-size="11" font-weight="800" fill="var(--team-text)">SUB-TEAM: auth &middot; Authentication &amp; Security</text>
            <text x="405" y="19" text-anchor="end" font-family="sans-serif" font-size="9" font-weight="700" fill="var(--team-base)">LAYER 2</text>

            <!-- auth/lead -->
            <g transform="translate(18, 42)">
              <rect width="180" height="75" rx="8" fill="var(--team-light)" stroke="var(--team-base)" stroke-width="1.5" />
              <text x="12" y="22" font-family="monospace" font-size="11" font-weight="700" fill="var(--team-text)">auth/lead</text>
              <text x="12" y="38" font-family="sans-serif" font-size="9" font-weight="700" fill="var(--team-base)">Team Leader</text>
              <text x="12" y="52" font-family="sans-serif" font-size="8" fill="var(--text-muted)">Coordinates SecOps</text>
              <text x="12" y="65" font-family="sans-serif" font-size="8" font-weight="700" fill="var(--team-text)">Sole Bridge to platform/lead</text>
            </g>

            <line x1="200" y1="80" x2="230" y2="80" stroke="var(--border-strong)" stroke-width="2" stroke-dasharray="3" />

            <!-- auth/secops -->
            <g transform="translate(232, 42)">
              <rect width="170" height="75" rx="8" fill="var(--spec-light)" stroke="var(--spec-border)" stroke-width="1.2" />
              <text x="12" y="22" font-family="monospace" font-size="11" font-weight="700" fill="var(--spec-text)">auth/secops</text>
              <text x="12" y="38" font-family="sans-serif" font-size="9" font-weight="700" fill="var(--text-subtle)">Security Specialist</text>
              <text x="12" y="52" font-family="sans-serif" font-size="8" fill="var(--text-muted)">JWT Verification &amp; Auditing</text>
              <text x="12" y="65" font-family="sans-serif" font-size="8" font-weight="600" fill="var(--prime-text)">Reports strictly to auth/lead</text>
            </g>
          </g>

        </svg>
      </div>
    </div>

    <!-- Upward Escalation Rule Callout -->
    <div class="callout-box">
      <div class="callout-title">⚠️ The Strict Escalation &amp; Provisioning Invariants</div>
      <p>
        <strong>1. Specialists never doorbell external teams or ULTRON PRIME:</strong> All external communication must funnel through the team's <code>lead</code>.<br>
        <strong>2. No rogue provisioning:</strong> Only <code>ultron-prime</code> can run <code>create-team</code>, <code>add-role</code>, or spawn subagents. Specialists escalate resource/headcount requests upward: <em>Specialist &rarr; Team Lead &rarr; Parent Lead &rarr; ULTRON PRIME &rarr; User</em>.
      </p>
    </div>
  </section>

  <!-- Section 3: Pure Git-Native Storage Split -->
  <section id="storage" class="section-card">
    <div class="section-header">
      <h2 class="section-title">3. Pure Git-Native Storage Split (Dual-Zone Architecture)</h2>
      <div class="section-sub">Zero SQLite or database engines. On-disk files are the single source of truth.</div>
    </div>

    <p style="font-size:0.88rem; color:var(--text-muted);">
      ULTRON enforces a strict physical split between <strong>Git-Tracked persistent assets</strong> (org charters, roles, code, and append-only event logs) and <strong>Gitignored ephemeral runtime state</strong> (Antigravity session UUIDs and lockfiles).
    </p>

    <!-- Visual Dual-Zone Diagram -->
    <div class="diagram-container">
      <div class="svg-wrap">
        <svg viewBox="0 0 920 220" width="920" height="220" xmlns="http://www.w3.org/2000/svg">
          <defs>
            <filter id="box-shadow" x="-3%" y="-5%" width="106%" height="115%">
              <feDropShadow dx="0" dy="2" stdDeviation="2.5" flood-opacity="0.06" />
            </filter>
          </defs>

          <!-- Zone 1: Git Tracked -->
          <g transform="translate(10, 10)">
            <rect width="520" height="195" rx="12" fill="var(--bg-surface)" stroke="var(--git-base)" stroke-width="2" filter="url(#box-shadow)" />
            <rect x="0" y="0" width="520" height="32" rx="12" fill="var(--git-light)" />
            <text x="16" y="21" font-family="sans-serif" font-size="12" font-weight="800" fill="var(--git-text)">🌿 ZONE 1: GIT-TRACKED &amp; PERSISTENT</text>
            <text x="504" y="21" text-anchor="end" font-family="monospace" font-size="10" font-weight="700" fill="var(--git-base)">repo root / ultron/</text>

            <!-- Hive Folder -->
            <rect x="16" y="44" width="235" height="135" rx="8" fill="var(--bg-subtle)" stroke="var(--border)" />
            <text x="26" y="62" font-family="monospace" font-size="10.5" font-weight="700" fill="var(--text-main)">ultron/hive/ (Org Tree)</text>
            <text x="26" y="80" font-family="sans-serif" font-size="9" fill="var(--text-muted)">&bull; <code>team.json</code> (metadata &amp; parent)</text>
            <text x="26" y="98" font-family="sans-serif" font-size="9" fill="var(--text-muted)">&bull; <code>AGENTS.md</code> (team charter)</text>
            <text x="26" y="116" font-family="sans-serif" font-size="9" fill="var(--text-muted)">&bull; <code>roles/&lt;role&gt;/role.json</code></text>
            <text x="26" y="134" font-family="sans-serif" font-size="9" fill="var(--text-muted)">&bull; <code>roles/&lt;role&gt;/workspace/</code></text>
            <text x="26" y="156" font-family="sans-serif" font-size="8.5" font-weight="700" fill="var(--git-text)">✔ Fully versioned across branches</text>

            <!-- Threads Folder -->
            <rect x="265" y="44" width="240" height="135" rx="8" fill="var(--bg-subtle)" stroke="var(--border)" />
            <text x="275" y="62" font-family="monospace" font-size="10.5" font-weight="700" fill="var(--text-main)">ultron/core/threads/</text>
            <text x="275" y="80" font-family="sans-serif" font-size="9" fill="var(--text-muted)">&bull; <code>t-YYYYMMDD-xxxxxxxx.jsonl</code></text>
            <text x="275" y="98" font-family="sans-serif" font-size="9" fill="var(--text-muted)">&bull; Append-only event streams</text>
            <text x="275" y="116" font-family="sans-serif" font-size="9" fill="var(--text-muted)">&bull; <code>threads/.gitattributes</code></text>
            <rect x="275" y="126" width="220" height="24" rx="4" fill="var(--git-light)" stroke="var(--git-border)" />
            <text x="285" y="142" font-family="monospace" font-size="9.5" font-weight="800" fill="var(--git-text)">*.jsonl merge=union</text>
            <text x="275" y="166" font-family="sans-serif" font-size="8.5" font-weight="700" fill="var(--git-base)">✔ Zero merge conflicts on branch join</text>
          </g>

          <!-- Zone 2: Gitignored Runtime -->
          <g transform="translate(555, 10)">
            <rect width="355" height="195" rx="12" fill="var(--bg-surface)" stroke="var(--runtime-base)" stroke-width="2" filter="url(#box-shadow)" />
            <rect x="0" y="0" width="355" height="32" rx="12" fill="var(--runtime-light)" />
            <text x="16" y="21" font-family="sans-serif" font-size="12" font-weight="800" fill="var(--runtime-text)">⚡ ZONE 2: GITIGNORED EPHEMERAL</text>
            <text x="340" y="21" text-anchor="end" font-family="monospace" font-size="10" font-weight="700" fill="var(--runtime-base)">.gitignore</text>

            <rect x="16" y="44" width="323" height="135" rx="8" fill="var(--bg-subtle)" stroke="var(--border)" />
            <text x="26" y="64" font-family="monospace" font-size="10.5" font-weight="700" fill="var(--text-main)">ultron/core/.runtime/</text>
            <text x="26" y="84" font-family="sans-serif" font-size="9" fill="var(--text-muted)">&bull; <code>sessions.json</code> (live conversation UUIDs)</text>
            <text x="26" y="104" font-family="sans-serif" font-size="9" fill="var(--text-muted)">&bull; <code>.lock</code> (atomic kernel-level file flock)</text>
            <text x="26" y="124" font-family="sans-serif" font-size="9" fill="var(--text-muted)">&bull; Dynamic team activation / disable state</text>
            
            <rect x="26" y="136" width="303" height="30" rx="6" fill="var(--runtime-light)" stroke="var(--runtime-border)" />
            <text x="36" y="154" font-family="sans-serif" font-size="8.5" font-weight="700" fill="var(--runtime-text)">✔ git status is 100% clean on team wake/sleep</text>
          </g>
        </svg>
      </div>
    </div>

    <div class="storage-grid">
      <!-- Zone 1 Details -->
      <div class="storage-zone git-zone">
        <span class="zone-badge">Zone 1 &middot; Git-Tracked &amp; Persistent</span>
        <div class="zone-title">Repository File Database</div>
        <p style="font-size:0.8rem; color:var(--text-muted); margin-bottom:12px;">Committed to Git. Survives branch switches, reboots, and repo relocations.</p>

        <div class="file-item highlight-git">
          <div class="file-name">ultron/hive/&lt;team&gt;/team.json</div>
          <div class="file-desc">Canonical team specification (slug, name, parent pointer, mission).</div>
        </div>
        <div class="file-item highlight-git">
          <div class="file-name">ultron/hive/&lt;team&gt;/AGENTS.md</div>
          <div class="file-desc">Shared team operating charter, responsibilities, and guidelines.</div>
        </div>
        <div class="file-item highlight-git">
          <div class="file-name">ultron/hive/&lt;team&gt;/roles/&lt;role&gt;/</div>
          <div class="file-desc"><code>role.json</code>, <code>AGENTS.md</code>, and role scratch <code>workspace/</code>.</div>
        </div>
        <div class="file-item highlight-git">
          <div class="file-name">ultron/core/threads/*.jsonl</div>
          <div class="file-desc">Append-only event log (<code>thread</code>, <code>post</code>, <code>status</code>, <code>reclassify</code>).</div>
        </div>
        <div class="file-item highlight-git">
          <div class="file-name">ultron/core/threads/.gitattributes</div>
          <div class="file-desc">Enforces <code>*.jsonl merge=union</code> for conflict-free Git branch merges!</div>
        </div>
      </div>

      <!-- Zone 2 Details -->
      <div class="storage-zone runtime-zone">
        <span class="zone-badge">Zone 2 &middot; Gitignored &amp; Ephemeral</span>
        <div class="zone-title">Runtime Session Registry</div>
        <p style="font-size:0.8rem; color:var(--text-muted); margin-bottom:12px;">Ignored by Git via <code>ultron/core/.gitignore</code>. Zero working-tree noise.</p>

        <div class="file-item highlight-runtime">
          <div class="file-name">ultron/core/.runtime/sessions.json</div>
          <div class="file-desc">Live Antigravity <code>conversation_id</code> UUIDs, registration timestamps, and model bindings.</div>
        </div>
        <div class="file-item highlight-runtime">
          <div class="file-name">ultron/core/.runtime/.lock</div>
          <div class="file-desc">Kernel-level <code>fcntl.flock</code> mutex ensuring atomic cross-process writes.</div>
        </div>

        <div class="callout-box git" style="margin-top:20px;">
          <div class="callout-title">🌿 Pristine Working Trees Guaranteed</div>
          <p style="font-size:0.8rem;">
            When teams are enabled (<code>activate-team</code>) or stood down (<code>disable-team</code>), changes are written <strong>strictly to <code>.runtime/sessions.json</code></strong>. Running <code>git status</code> remains completely clean, preventing ghost commits and dirty merges.
          </p>
        </div>
      </div>
    </div>

    <!-- Code pill block showing gitattributes -->
    <div class="cli-block">
      <span class="cli-comment"># ultron/core/threads/.gitattributes — Conflict-Free Git Branch Merging:</span><br>
      <span class="cli-cmd">*.jsonl</span> <span class="cli-flag">merge=union</span><br><br>
      <span class="cli-comment"># Why this matters: When two developers or agents work on separate Git branches,</span><br>
      <span class="cli-comment"># both can append replies or update statuses on the board simultaneously.</span><br>
      <span class="cli-comment"># Upon git merge, Git union-merges the JSONL lines with ZERO conflicts.</span>
    </div>
  </section>

  <!-- Section 4: Visibility & Reactive Doorbells -->
  <section id="visibility" class="section-card">
    <div class="section-header">
      <h2 class="section-title">4. Visibility Scoping &amp; Reactive Doorbell Workflow</h2>
      <div class="section-sub">Information boundary enforcement and zero-polling event-driven communication.</div>
    </div>

    <p style="font-size:0.88rem; color:var(--text-muted);">
      To prevent context window bloat and noise across multi-agent swarms, ULTRON enforces a 4-tier visibility model on all thread operations, paired with a 3-step reactive doorbell flow that requires <strong>zero polling loops</strong>.
    </p>

    <!-- Visibility Matrix Table -->
    <div class="matrix-table-wrap">
      <table class="matrix-table">
        <thead>
          <tr>
            <th>Visibility Tier</th>
            <th>CLI Flag</th>
            <th>Read &amp; Reply Authorization</th>
            <th>Architectural Purpose</th>
          </tr>
        </thead>
        <tbody>
          <tr>
            <td><span class="scope-pill scope-personal">personal</span></td>
            <td><code>--visibility personal</code></td>
            <td>Target <code>&lt;team&gt;/&lt;role&gt;</code> only + <code>ultron-prime</code></td>
            <td>Role-persistent memory: private notes and domain lessons that survive agent session respawns.</td>
          </tr>
          <tr>
            <td><span class="scope-pill scope-team">team</span></td>
            <td><code>--visibility team</code></td>
            <td>All roles in <code>team_slug</code> + <code>ultron-prime</code></td>
            <td>Intra-team sprint execution, peer code reviews, and local team lessons.</td>
          </tr>
          <tr>
            <td><span class="scope-pill scope-cross">team &harr; child</span></td>
            <td><code>--visibility team --with-team &lt;subteam&gt;</code></td>
            <td>Parent team + designated sub-team + <code>ultron-prime</code></td>
            <td>Cross-layer delegation, contract handoffs, and escalations without global noise.</td>
          </tr>
          <tr>
            <td><span class="scope-pill scope-global">global</span></td>
            <td><code>--visibility global</code></td>
            <td>Every agent in the entire Hive</td>
            <td>Network-wide architectural standards, breaking changes, and framework-wide announcements.</td>
          </tr>
        </tbody>
      </table>
    </div>

    <!-- 3-Step Doorbell Sequence -->
    <h3 style="font-size:1.05rem; font-weight:700; margin-top:24px; margin-bottom:8px;">The 3-Step Reactive Doorbell Flow</h3>
    <p style="font-size:0.84rem; color:var(--text-muted); margin-bottom:12px;">JSONL files are passive logs on disk. Agents never sleep in polling loops. When an agent posts work, they wake the recipient immediately:</p>

    <!-- Reactive Doorbell SVG Flow -->
    <div class="diagram-container">
      <div class="svg-wrap">
        <svg viewBox="0 0 920 180" width="920" height="180" xmlns="http://www.w3.org/2000/svg">
          <defs>
            <marker id="flow-arrow" viewBox="0 0 10 10" refX="6" refY="5" markerWidth="6" markerHeight="6" orient="auto-start-reverse">
              <path d="M 0 1 L 8 5 L 0 9 z" fill="var(--team-base)" />
            </marker>
          </defs>

          <!-- Step 1 Node -->
          <g transform="translate(15, 20)">
            <rect width="250" height="135" rx="10" fill="var(--bg-surface)" stroke="var(--border)" stroke-width="1.5" />
            <circle cx="26" cy="26" r="14" fill="var(--team-base)" />
            <text x="26" y="31" text-anchor="middle" font-family="sans-serif" font-size="12" font-weight="800" fill="#ffffff">1</text>
            <text x="50" y="30" font-family="sans-serif" font-size="12" font-weight="700" fill="var(--text-main)">Write JSONL Event</text>
            <text x="16" y="58" font-family="sans-serif" font-size="9" fill="var(--text-muted)">Agent appends post atomically:</text>
            <rect x="16" y="68" width="218" height="48" rx="6" fill="var(--code-bg)" />
            <text x="24" y="86" font-family="monospace" font-size="8.5" fill="#38bdf8">python3 ultron/core/core.py</text>
            <text x="24" y="102" font-family="monospace" font-size="8.5" fill="#34d399">new-thread / reply ...</text>
            <text x="16" y="138" font-family="sans-serif" font-size="8" font-weight="600" fill="var(--git-text)">Atomic append with fcntl.flock</text>
          </g>

          <!-- Connector 1 -> 2 -->
          <path d="M 270,85 L 320,85" fill="none" stroke="var(--team-base)" stroke-width="2.5" marker-end="url(#flow-arrow)" />

          <!-- Step 2 Node -->
          <g transform="translate(330, 20)">
            <rect width="250" height="135" rx="10" fill="var(--bg-surface)" stroke="var(--border)" stroke-width="1.5" />
            <circle cx="26" cy="26" r="14" fill="var(--team-base)" />
            <text x="26" y="31" text-anchor="middle" font-family="sans-serif" font-size="12" font-weight="800" fill="#ffffff">2</text>
            <text x="50" y="30" font-family="sans-serif" font-size="12" font-weight="700" fill="var(--text-main)">Resolve Live UUID</text>
            <text x="16" y="58" font-family="sans-serif" font-size="9" fill="var(--text-muted)">Query session registry:</text>
            <rect x="16" y="68" width="218" height="48" rx="6" fill="var(--code-bg)" />
            <text x="24" y="86" font-family="monospace" font-size="8.5" fill="#38bdf8">python3 ultron/core/core.py</text>
            <text x="24" y="102" font-family="monospace" font-size="8.5" fill="#a78bfa">whois &lt;agent_id&gt; --id-only</text>
            <text x="16" y="138" font-family="sans-serif" font-size="8" font-weight="600" fill="var(--runtime-text)">Reads .runtime/sessions.json</text>
          </g>

          <!-- Connector 2 -> 3 -->
          <path d="M 585,85 L 635,85" fill="none" stroke="var(--team-base)" stroke-width="2.5" marker-end="url(#flow-arrow)" />

          <!-- Step 3 Node -->
          <g transform="translate(645, 20)">
            <rect width="260" height="135" rx="10" fill="var(--bg-surface)" stroke="var(--prime-border)" stroke-width="1.5" />
            <circle cx="26" cy="26" r="14" fill="var(--prime-base)" />
            <text x="26" y="31" text-anchor="middle" font-family="sans-serif" font-size="12" font-weight="800" fill="#ffffff">3</text>
            <text x="50" y="30" font-family="sans-serif" font-size="12" font-weight="700" fill="var(--prime-text)">Doorbell Wakeup</text>
            <text x="16" y="58" font-family="sans-serif" font-size="9" fill="var(--text-muted)">Wake recipient via Antigravity:</text>
            <rect x="16" y="68" width="228" height="48" rx="6" fill="var(--code-bg)" />
            <text x="24" y="86" font-family="monospace" font-size="8" fill="#f1f5f9">send_message(</text>
            <text x="24" y="102" font-family="monospace" font-size="8" fill="#f87171">Recipient="&lt;uuid&gt;", ...)</text>
            <text x="16" y="138" font-family="sans-serif" font-size="8" font-weight="700" fill="var(--prime-text)">⚡ Wakes target immediately &middot; 0 polling!</text>
          </g>
        </svg>
      </div>
    </div>

    <div class="doorbell-flow">
      <div class="flow-step-card">
        <div class="step-number">1</div>
        <div class="step-title">Write JSONL Event</div>
        <div class="step-desc">
          Agent appends a post, reply, or status change using atomic file locking:
          <div style="margin-top:6px;"><code class="code-pill">core.py reply &lt;thread_id&gt; ...</code></div>
        </div>
      </div>

      <div class="flow-step-card">
        <div class="step-number">2</div>
        <div class="step-title">Resolve Live UUID</div>
        <div class="step-desc">
          Agent queries the runtime registry for the target recipient's active Antigravity session:
          <div style="margin-top:6px;"><code class="code-pill">core.py whois &lt;agent_id&gt; --id-only</code></div>
        </div>
      </div>

      <div class="flow-step-card">
        <div class="step-number">3</div>
        <div class="step-title">Doorbell Wakeup</div>
        <div class="step-desc">
          Agent immediately wakes the target via Antigravity's messaging primitive:
          <div style="margin-top:6px;"><code class="code-pill">send_message(Recipient="&lt;uuid&gt;", ...)</code></div>
          Target awakens automatically. <strong>Zero polling cycles wasted!</strong>
        </div>
      </div>
    </div>
  </section>

  <!-- Section 5: Team Lifecycle & Dynamic Resource Conservation -->
  <section id="lifecycle" class="section-card">
    <div class="section-header">
      <h2 class="section-title">5. Team Lifecycle &amp; Dynamic Resource Conservation</h2>
      <div class="section-sub">Conserving token bandwidth and subagent processes without losing organizational memory.</div>
    </div>

    <p style="font-size:0.88rem; color:var(--text-muted);">
      Persistent background agents consume memory, model context, and harness slots. ULTRON treats teams as <strong>dynamic state machines</strong>: teams can be spawned on-demand for tasks and cleanly stood down when idle, with 100% of their charters, role lessons, and board logs preserved on disk.
    </p>

    <!-- Lifecycle State Loop SVG -->
    <div class="diagram-container">
      <div class="svg-wrap">
        <svg viewBox="0 0 920 160" width="920" height="160" xmlns="http://www.w3.org/2000/svg">
          <defs>
            <marker id="loop-arrow" viewBox="0 0 10 10" refX="6" refY="5" markerWidth="6" markerHeight="6" orient="auto-start-reverse">
              <path d="M 0 1 L 8 5 L 0 9 z" fill="var(--team-base)" />
            </marker>
            <marker id="revive-arrow" viewBox="0 0 10 10" refX="6" refY="5" markerWidth="6" markerHeight="6" orient="auto-start-reverse">
              <path d="M 0 1 L 8 5 L 0 9 z" fill="var(--git-base)" />
            </marker>
          </defs>

          <!-- State 1: Scaffolded / Dormant -->
          <g transform="translate(20, 30)">
            <rect width="230" height="90" rx="10" fill="var(--bg-surface)" stroke="var(--border)" stroke-width="1.5" />
            <text x="16" y="28" font-family="sans-serif" font-size="11" font-weight="800" fill="var(--text-subtle)">1. DORMANT / SCAFFOLDED</text>
            <text x="16" y="48" font-family="sans-serif" font-size="9" fill="var(--text-muted)">&bull; <code>create-team</code> + <code>add-role</code></text>
            <text x="16" y="66" font-family="sans-serif" font-size="9" fill="var(--text-muted)">&bull; On-disk charters &amp; workspace ready</text>
            <text x="16" y="82" font-family="sans-serif" font-size="8.5" font-weight="700" fill="var(--git-text)">0 tokens consumed</text>
          </g>

          <!-- Arrow 1 -> 2 -->
          <path d="M 255,75 L 335,75" fill="none" stroke="var(--team-base)" stroke-width="2.5" marker-end="url(#loop-arrow)" />
          <text x="295" y="66" text-anchor="middle" font-family="sans-serif" font-size="8" font-weight="700" fill="var(--team-base)">activate-team</text>

          <!-- State 2: Active Execution -->
          <g transform="translate(345, 20)">
            <rect width="250" height="110" rx="10" fill="var(--team-light)" stroke="var(--team-border)" stroke-width="2" />
            <text x="16" y="28" font-family="sans-serif" font-size="11.5" font-weight="800" fill="var(--team-text)">2. ACTIVE EXECUTION</text>
            <text x="16" y="50" font-family="sans-serif" font-size="9" fill="var(--text-main)">&bull; Subagents running (default <code>flash</code>)</text>
            <text x="16" y="68" font-family="sans-serif" font-size="9" fill="var(--text-main)">&bull; Tasks assigned &amp; doorbelled</text>
            <text x="16" y="86" font-family="sans-serif" font-size="9" fill="var(--text-main)">&bull; Specialists code, design, audit</text>
            <text x="16" y="102" font-family="sans-serif" font-size="8.5" font-weight="700" fill="var(--team-base)">Active Antigravity sessions</text>
          </g>

          <!-- Arrow 2 -> 3 -->
          <path d="M 600,75 L 675,75" fill="none" stroke="var(--prime-base)" stroke-width="2.5" marker-end="url(#arrow-up)" />
          <text x="638" y="66" text-anchor="middle" font-family="sans-serif" font-size="8" font-weight="700" fill="var(--prime-base)">disable-team</text>

          <!-- State 3: Clean Stand-Down -->
          <g transform="translate(685, 30)">
            <rect width="220" height="90" rx="10" fill="var(--bg-surface)" stroke="var(--git-base)" stroke-width="1.5" />
            <text x="16" y="28" font-family="sans-serif" font-size="11" font-weight="800" fill="var(--git-text)">3. CLEAN STAND-DOWN</text>
            <text x="16" y="48" font-family="sans-serif" font-size="9" fill="var(--text-muted)">&bull; <code>manage_subagents(kill)</code></text>
            <text x="16" y="66" font-family="sans-serif" font-size="9" fill="var(--text-muted)">&bull; Memory &amp; logs preserved</text>
            <text x="16" y="82" font-family="sans-serif" font-size="8.5" font-weight="700" fill="var(--git-base)">Idle resources released</text>
          </g>

          <!-- Curve revival from 3 back to 2 -->
          <path d="M 795,125 C 795,150 470,150 470,135" fill="none" stroke="var(--git-base)" stroke-width="2" stroke-dasharray="4" marker-end="url(#revive-arrow)" />
          <text x="630" y="152" text-anchor="middle" font-family="sans-serif" font-size="8.5" font-weight="700" fill="var(--git-base)">Instant zero-loss re-activation with preserved memory</text>
        </svg>
      </div>
    </div>

    <div class="pipeline-track">
      <div class="pipeline-stage">
        <span class="stage-badge">1. Scaffold</span>
        <div class="stage-info">
          <div class="stage-title"><code>python3 ultron/core/core.py create-team --slug &lt;slug&gt; [--parent &lt;parent&gt;]</code></div>
          <div class="stage-desc">Scaffolds <code>ultron/hive/&lt;slug&gt;/</code>, writes <code>team.json</code> and team charter <code>AGENTS.md</code>, and creates the mandatory <code>lead</code> role.</div>
        </div>
      </div>

      <div class="pipeline-stage">
        <span class="stage-badge">2. Render Spawn</span>
        <div class="stage-info">
          <div class="stage-title"><code>python3 ultron/core/core.py render-spawn &lt;slug&gt; --json</code></div>
          <div class="stage-desc">Generates exact JSON payloads for Antigravity's <code>define_subagent</code> and <code>invoke_subagent</code>. Defaults subagent model to <code>flash</code> for token efficiency.</div>
        </div>
      </div>

      <div class="pipeline-stage">
        <span class="stage-badge">3. Spawn Harness</span>
        <div class="stage-info">
          <div class="stage-title">ULTRON PRIME Calls <code>define_subagent</code> &amp; <code>invoke_subagent</code></div>
          <div class="stage-desc">Spawns background subagent processes. Antigravity returns live <code>conversationId</code> UUIDs for each role.</div>
        </div>
      </div>

      <div class="pipeline-stage">
        <span class="stage-badge">4. Activate</span>
        <div class="stage-info">
          <div class="stage-title"><code>python3 ultron/core/core.py activate-team &lt;slug&gt; --uuids '{...}'</code></div>
          <div class="stage-desc">Binds live session UUIDs into gitignored <code>.runtime/sessions.json</code> and sets team status to <code>active</code>. Working tree stays clean.</div>
        </div>
      </div>

      <div class="pipeline-stage">
        <span class="stage-badge">5. Execute &amp; Verify</span>
        <div class="stage-info">
          <div class="stage-title">Task Dispatch &amp; Doorbell Execution</div>
          <div class="stage-desc">ULTRON PRIME posts task thread and doorbells <code>&lt;team&gt;/lead</code>. The Lead delegates to flat specialist peers, reviews PRs/deliverables, and reports completion.</div>
        </div>
      </div>

      <div class="pipeline-stage">
        <span class="stage-badge kill">6. Prepare Disable</span>
        <div class="stage-info">
          <div class="stage-title"><code>python3 ultron/core/core.py prepare-disable &lt;slug&gt; [--cascade] --json</code></div>
          <div class="stage-desc">Extracts active session UUIDs for termination. ULTRON PRIME calls Antigravity's <code>manage_subagents(Action="kill")</code> to release process resources.</div>
        </div>
      </div>

      <div class="pipeline-stage">
        <span class="stage-badge kill">7. Stand Down</span>
        <div class="stage-info">
          <div class="stage-title"><code>python3 ultron/core/core.py disable-team &lt;slug&gt; [--cascade]</code></div>
          <div class="stage-desc">Marks team <code>disabled</code> in the registry. <strong>Zero loss:</strong> Charters, private workspaces, and JSONL thread logs remain intact on disk for immediate future re-activation!</div>
        </div>
      </div>
    </div>
  </section>

  <!-- Section 6: CLI Quick Reference -->
  <section id="cli" class="section-card">
    <div class="section-header">
      <h2 class="section-title">6. CLI Quick Reference (<code>ultron/core/core.py</code>)</h2>
      <div class="section-sub">Standard commands for ULTRON PRIME, Team Leads, and Specialist Peers.</div>
    </div>

    <!-- Tab navigation -->
    <div class="tab-strip">
      <button class="tab-btn active" onclick="switchTab(event, 'tab-prime')">👑 ULTRON PRIME</button>
      <button class="tab-btn" onclick="switchTab(event, 'tab-leads')">🔷 Team Leads</button>
      <button class="tab-btn" onclick="switchTab(event, 'tab-specialists')">⚪ Specialist Peers</button>
      <button class="tab-btn" onclick="switchTab(event, 'tab-board')">📋 Board &amp; Search</button>
    </div>

    <!-- Tab: ULTRON PRIME -->
    <div id="tab-prime" class="tab-panel active">
      <div class="cli-block">
        <span class="cli-comment"># 1. Register PRIME session on boot</span><br>
        <span class="cli-cmd">python3 ultron/core/core.py</span> <span class="cli-arg">register-prime</span> <span class="cli-flag">--id</span> <span class="cli-val">"&lt;conversation-uuid&gt;"</span><br><br>
        <span class="cli-comment"># 2. Inspect full N-layer org tree, integrity &amp; stats</span><br>
        <span class="cli-cmd">python3 ultron/core/core.py</span> <span class="cli-arg">org-tree</span><br>
        <span class="cli-cmd">python3 ultron/core/core.py</span> <span class="cli-arg">verify</span><br>
        <span class="cli-cmd">python3 ultron/core/core.py</span> <span class="cli-arg">stats</span><br><br>
        <span class="cli-comment"># 3. Create Layer 1 and nested Layer 2..N teams</span><br>
        <span class="cli-cmd">python3 ultron/core/core.py</span> <span class="cli-arg">create-team</span> <span class="cli-flag">--slug</span> <span class="cli-val">"docs"</span> <span class="cli-flag">--name</span> <span class="cli-val">"Technical Documentation"</span> <span class="cli-flag">--mission</span> <span class="cli-val">"Public architecture docs"</span><br>
        <span class="cli-cmd">python3 ultron/core/core.py</span> <span class="cli-arg">create-team</span> <span class="cli-flag">--slug</span> <span class="cli-val">"web-viz"</span> <span class="cli-flag">--parent</span> <span class="cli-val">"docs"</span> <span class="cli-flag">--name</span> <span class="cli-val">"Visual Architecture Showcase"</span><br><br>
        <span class="cli-comment"># 4. Add flat specialist roles</span><br>
        <span class="cli-cmd">python3 ultron/core/core.py</span> <span class="cli-arg">add-role</span> <span class="cli-flag">--team</span> <span class="cli-val">"web-viz"</span> <span class="cli-flag">--role</span> <span class="cli-val">"designer"</span> <span class="cli-flag">--title</span> <span class="cli-val">"HTML Specialist"</span> <span class="cli-flag">--responsibilities</span> <span class="cli-val">"Build responsive architecture showcase"</span><br><br>
        <span class="cli-comment"># 5. Render spawn specs &amp; activate spawned sessions</span><br>
        <span class="cli-cmd">python3 ultron/core/core.py</span> <span class="cli-arg">render-spawn</span> <span class="cli-val">"web-viz"</span> <span class="cli-flag">--json</span><br>
        <span class="cli-cmd">python3 ultron/core/core.py</span> <span class="cli-arg">activate-team</span> <span class="cli-val">"web-viz"</span> <span class="cli-flag">--uuids</span> <span class="cli-val">'{"lead":"&lt;lead-uuid&gt;","designer":"&lt;designer-uuid&gt;"}'</span><br><br>
        <span class="cli-comment"># 6. Stand down idle teams cleanly (resource conservation)</span><br>
        <span class="cli-cmd">python3 ultron/core/core.py</span> <span class="cli-arg">prepare-disable</span> <span class="cli-val">"web-viz"</span> <span class="cli-flag">--json</span><br>
        <span class="cli-cmd">python3 ultron/core/core.py</span> <span class="cli-arg">disable-team</span> <span class="cli-val">"web-viz"</span>
      </div>
    </div>

    <!-- Tab: Team Leads -->
    <div id="tab-leads" class="tab-panel">
      <div class="cli-block">
        <span class="cli-comment"># 1. Startup hydration: verify contacts &amp; team threads</span><br>
        <span class="cli-cmd">python3 ultron/core/core.py</span> <span class="cli-arg">contacts</span> <span class="cli-val">web-viz/lead</span><br>
        <span class="cli-cmd">python3 ultron/core/core.py</span> <span class="cli-arg">list</span> <span class="cli-flag">--as</span> <span class="cli-val">web-viz/lead</span> <span class="cli-flag">--visibility</span> <span class="cli-val">team</span><br><br>
        <span class="cli-comment"># 2. Assign tasks to specialists via new thread</span><br>
        <span class="cli-cmd">python3 ultron/core/core.py</span> <span class="cli-arg">new-thread</span> <span class="cli-flag">--author</span> <span class="cli-val">web-viz/lead</span> <span class="cli-flag">--visibility</span> <span class="cli-val">team</span> <span class="cli-flag">--category</span> <span class="cli-val">task</span> <span class="cli-flag">--title</span> <span class="cli-val">"Design Architecture HTML"</span> <span class="cli-flag">--content</span> <span class="cli-val">"Build ultron-architecture.html..."</span><br><br>
        <span class="cli-comment"># 3. Resolve specialist UUID &amp; wake via doorbell</span><br>
        <span class="cli-cmd">python3 ultron/core/core.py</span> <span class="cli-arg">whois</span> <span class="cli-val">web-viz/designer</span> <span class="cli-flag">--id-only</span><br>
        <span class="cli-comment"># Wake designer via Antigravity: send_message(Recipient="&lt;designer-uuid&gt;", Message="Doorbell: Assigned Thread...")</span><br><br>
        <span class="cli-comment"># 4. Cross-layer handoff / escalation to parent lead (docs/lead)</span><br>
        <span class="cli-cmd">python3 ultron/core/core.py</span> <span class="cli-arg">new-thread</span> <span class="cli-flag">--author</span> <span class="cli-val">web-viz/lead</span> <span class="cli-flag">--visibility</span> <span class="cli-val">team</span> <span class="cli-flag">--with-team</span> <span class="cli-val">docs</span> <span class="cli-flag">--category</span> <span class="cli-val">task</span> <span class="cli-flag">--title</span> <span class="cli-val">"Visual Showcase Ready for Review"</span>
      </div>
    </div>

    <!-- Tab: Specialist Peers -->
    <div id="tab-specialists" class="tab-panel">
      <div class="cli-block">
        <span class="cli-comment"># 1. Startup hydration: check personal memory &amp; team tasks</span><br>
        <span class="cli-cmd">python3 ultron/core/core.py</span> <span class="cli-arg">list</span> <span class="cli-flag">--as</span> <span class="cli-val">web-viz/designer</span> <span class="cli-flag">--visibility</span> <span class="cli-val">personal</span><br>
        <span class="cli-cmd">python3 ultron/core/core.py</span> <span class="cli-arg">list</span> <span class="cli-flag">--as</span> <span class="cli-val">web-viz/designer</span> <span class="cli-flag">--visibility</span> <span class="cli-val">team</span><br>
        <span class="cli-cmd">python3 ultron/core/core.py</span> <span class="cli-arg">contacts</span> <span class="cli-val">web-viz/designer</span><br><br>
        <span class="cli-comment"># 2. View assigned task thread (accepts full ID or short hex suffix)</span><br>
        <span class="cli-cmd">python3 ultron/core/core.py</span> <span class="cli-arg">view</span> <span class="cli-val">81f92de1</span> <span class="cli-flag">--as</span> <span class="cli-val">web-viz/designer</span><br><br>
        <span class="cli-comment"># 3. Post completion reply to team lead</span><br>
        <span class="cli-cmd">python3 ultron/core/core.py</span> <span class="cli-arg">reply</span> <span class="cli-val">81f92de1</span> <span class="cli-flag">--author</span> <span class="cli-val">web-viz/designer</span> <span class="cli-flag">--content</span> <span class="cli-val">"Showcase implementation complete. Verified self-contained HTML."</span><br><br>
        <span class="cli-comment"># 4. Record personal reusable lesson (survives session restarts)</span><br>
        <span class="cli-cmd">python3 ultron/core/core.py</span> <span class="cli-arg">new-thread</span> <span class="cli-flag">--author</span> <span class="cli-val">web-viz/designer</span> <span class="cli-flag">--visibility</span> <span class="cli-val">personal</span> <span class="cli-flag">--category</span> <span class="cli-val">lesson</span> <span class="cli-flag">--title</span> <span class="cli-val">"SVG Dark Mode Theme Tips"</span> <span class="cli-flag">--content</span> <span class="cli-val">"Use var(--border) and var(--bg-surface) in SVG stroke/fill."</span>
      </div>
    </div>

    <!-- Tab: Board & Search -->
    <div id="tab-board" class="tab-panel">
      <div class="cli-block">
        <span class="cli-comment"># 1. Search visible threads across all authorized scopes</span><br>
        <span class="cli-cmd">python3 ultron/core/core.py</span> <span class="cli-arg">search</span> <span class="cli-val">"architecture"</span> <span class="cli-flag">--as</span> <span class="cli-val">web-viz/designer</span><br><br>
        <span class="cli-comment"># 2. Filter thread lists by status or category</span><br>
        <span class="cli-cmd">python3 ultron/core/core.py</span> <span class="cli-arg">list</span> <span class="cli-flag">--as</span> <span class="cli-val">web-viz/lead</span> <span class="cli-flag">--status</span> <span class="cli-val">open</span><br>
        <span class="cli-cmd">python3 ultron/core/core.py</span> <span class="cli-arg">list</span> <span class="cli-flag">--as</span> <span class="cli-val">web-viz/lead</span> <span class="cli-flag">--category</span> <span class="cli-val">task</span><br><br>
        <span class="cli-comment"># 3. Update thread status (open -> resolved / blocked / closed)</span><br>
        <span class="cli-cmd">python3 ultron/core/core.py</span> <span class="cli-arg">set-status</span> <span class="cli-val">81f92de1</span> <span class="cli-val">resolved</span> <span class="cli-flag">--as</span> <span class="cli-val">web-viz/lead</span><br><br>
        <span class="cli-comment"># 4. Reclassify thread scope (ULTRON PRIME only)</span><br>
        <span class="cli-cmd">python3 ultron/core/core.py</span> <span class="cli-arg">reclassify</span> <span class="cli-val">81f92de1</span> <span class="cli-flag">--as</span> <span class="cli-val">ultron-prime</span> <span class="cli-flag">--visibility</span> <span class="cli-val">global</span>
      </div>
    </div>

  </section>

  <!-- Footer -->
  <footer>
    <div><strong>ULTRON</strong> &middot; Universal Layered Team and Role Orchestration Network</div>
    <div class="footer-sub">Pure Git-Native Multi-Agent Coordination Engine &middot; Self-Contained Visual Architecture Showcase</div>
  </footer>

</div>

<script>
  // Theme Toggle Logic
  function setTheme(theme) {
    const root = document.documentElement;
    const btnLight = document.getElementById('btn-theme-light');
    const btnDark = document.getElementById('btn-theme-dark');
    const btnAuto = document.getElementById('btn-theme-auto');

    btnLight.classList.remove('active');
    btnDark.classList.remove('active');
    btnAuto.classList.remove('active');

    if (theme === 'light') {
      root.setAttribute('data-theme', 'light');
      localStorage.setItem('ultron-theme', 'light');
      btnLight.classList.add('active');
    } else if (theme === 'dark') {
      root.setAttribute('data-theme', 'dark');
      localStorage.setItem('ultron-theme', 'dark');
      btnDark.classList.add('active');
    } else {
      root.removeAttribute('data-theme');
      localStorage.removeItem('ultron-theme');
      btnAuto.classList.add('active');
    }
  }

  // Restore saved theme
  (function initTheme() {
    const saved = localStorage.getItem('ultron-theme');
    if (saved === 'light' || saved === 'dark') {
      setTheme(saved);
    } else {
      setTheme('auto');
    }
  })();

  // CLI Tab Switching Logic
  function switchTab(evt, tabId) {
    const tabBtns = document.querySelectorAll('.tab-btn');
    const tabPanels = document.querySelectorAll('.tab-panel');

    tabBtns.forEach(btn => btn.classList.remove('active'));
    tabPanels.forEach(panel => panel.classList.remove('active'));

    evt.currentTarget.classList.add('active');
    const activePanel = document.getElementById(tabId);
    if (activePanel) {
      activePanel.classList.add('active');
    }
  }
</script>

</body>
</html>
'''

with open("/Users/jvroig/Dev/ULTRON/ultron-architecture.html", "w", encoding="utf-8") as f:
    f.write(html_content)

print(f"Successfully generated publication-grade showcase: {len(html_content)} bytes to /Users/jvroig/Dev/ULTRON/ultron-architecture.html")
