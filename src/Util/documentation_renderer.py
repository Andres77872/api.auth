"""
Documentation Renderer Utility

Provides markdown-to-HTML rendering with modern docs UI/UX.
Features: sidebar navigation, table of contents, search, responsive design.
"""

import re
from pathlib import Path
from typing import Optional, List, Dict, Tuple
from dataclasses import dataclass, field


@dataclass
class DocumentationFile:
    """Represents a documentation file"""
    name: str
    path: str
    title: str
    is_readme: bool = False


@dataclass
class DocCategory:
    """Represents a documentation category/folder"""
    name: str
    title: str
    path: str
    files: List[DocumentationFile] = field(default_factory=list)


@dataclass
class TocItem:
    """Table of contents item"""
    level: int
    text: str
    slug: str


class DocumentationRenderer:
    """
    Renders markdown documentation as styled HTML with modern docs UI.
    Features: sidebar navigation, TOC, search, responsive design.
    """
    
    # Modern docs theme CSS - VitePress/Docusaurus inspired
    CSS_STYLES = """
    :root {
        --bg-primary: #ffffff;
        --bg-secondary: #f8fafc;
        --bg-tertiary: #f1f5f9;
        --bg-code: #1e293b;
        --text-primary: #1e293b;
        --text-secondary: #475569;
        --text-muted: #94a3b8;
        --border-color: #e2e8f0;
        --accent-color: #3b82f6;
        --accent-hover: #2563eb;
        --accent-light: #eff6ff;
        --success-color: #22c55e;
        --warning-color: #f59e0b;
        --error-color: #ef4444;
        --sidebar-width: 260px;
        --toc-width: 220px;
        --nav-height: 56px;
    }
    
    /* Dark mode support via media query */
    @media (prefers-color-scheme: dark) {
        :root {
            --bg-primary: #0f172a;
            --bg-secondary: #1e293b;
            --bg-tertiary: #334155;
            --text-primary: #f1f5f9;
            --text-secondary: #cbd5e1;
            --text-muted: #64748b;
            --border-color: #334155;
            --accent-light: rgba(59, 130, 246, 0.1);
        }
    }
    
    * { box-sizing: border-box; margin: 0; padding: 0; }
    
    html { scroll-behavior: smooth; scroll-padding-top: calc(var(--nav-height) + 24px); }
    
    body {
        font-family: 'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Oxygen, Ubuntu, sans-serif;
        font-size: 15px;
        line-height: 1.7;
        color: var(--text-primary);
        background: var(--bg-primary);
        min-height: 100vh;
    }
    
    /* Top Navigation */
    .top-nav {
        position: fixed;
        top: 0;
        left: 0;
        right: 0;
        height: var(--nav-height);
        z-index: 100;
        background: var(--bg-primary);
        border-bottom: 1px solid var(--border-color);
        display: flex;
        align-items: center;
        padding: 0 24px;
        backdrop-filter: blur(12px);
    }
    
    .nav-left {
        display: flex;
        align-items: center;
        gap: 16px;
    }
    
    .menu-toggle {
        display: none;
        background: none;
        border: none;
        padding: 8px;
        cursor: pointer;
        color: var(--text-primary);
        border-radius: 6px;
    }
    
    .menu-toggle:hover { background: var(--bg-tertiary); }
    
    .nav-brand {
        font-weight: 700;
        font-size: 18px;
        color: var(--text-primary);
        text-decoration: none;
        display: flex;
        align-items: center;
        gap: 10px;
    }
    
    .nav-brand-icon {
        width: 32px;
        height: 32px;
        background: linear-gradient(135deg, var(--accent-color), #8b5cf6);
        border-radius: 8px;
        display: flex;
        align-items: center;
        justify-content: center;
        color: white;
        font-size: 16px;
        font-weight: 700;
    }
    
    .search-container {
        flex: 1;
        display: flex;
        justify-content: center;
        padding: 0 32px;
    }
    
    .search-box {
        position: relative;
        width: 100%;
        max-width: 480px;
    }
    
    .search-input {
        width: 100%;
        padding: 10px 16px 10px 44px;
        border: 1px solid var(--border-color);
        border-radius: 10px;
        font-size: 14px;
        background: var(--bg-secondary);
        color: var(--text-primary);
        transition: all 0.2s;
    }
    
    .search-input:focus {
        outline: none;
        border-color: var(--accent-color);
        box-shadow: 0 0 0 3px var(--accent-light);
    }
    
    .search-input::placeholder { color: var(--text-muted); }
    
    .search-icon {
        position: absolute;
        left: 14px;
        top: 50%;
        transform: translateY(-50%);
        color: var(--text-muted);
        pointer-events: none;
    }
    
    .search-shortcut {
        position: absolute;
        right: 12px;
        top: 50%;
        transform: translateY(-50%);
        padding: 4px 8px;
        background: var(--bg-tertiary);
        border-radius: 4px;
        font-size: 11px;
        color: var(--text-muted);
        font-weight: 500;
    }
    
    .nav-right {
        display: flex;
        align-items: center;
        gap: 8px;
    }
    
    .nav-link {
        color: var(--text-secondary);
        text-decoration: none;
        padding: 8px 12px;
        border-radius: 6px;
        font-size: 14px;
        font-weight: 500;
        transition: all 0.2s;
    }
    
    .nav-link:hover {
        color: var(--text-primary);
        background: var(--bg-tertiary);
    }
    
    /* Layout */
    .layout {
        display: flex;
        padding-top: var(--nav-height);
        min-height: 100vh;
    }

    /* Sidebar */
    .sidebar {
        position: fixed;
        top: var(--nav-height);
        left: 0;
        bottom: 0;
        width: var(--sidebar-width);
        background: var(--bg-secondary);
        border-right: 1px solid var(--border-color);
        overflow-y: auto;
        overflow-x: hidden;
        padding: 20px 0;
        z-index: 50;
        transition: transform 0.3s ease;
        /* Subtle shadow for depth */
        box-shadow: 1px 0 3px rgba(0,0,0,0.05);
    }

    @media (prefers-color-scheme: dark) {
        .sidebar {
            box-shadow: 1px 0 3px rgba(0,0,0,0.2);
        }
    }

    .sidebar-section {
        margin-bottom: 4px;
    }

    .sidebar-section-title {
        padding: 12px 16px 8px;
        font-size: 10px;
        font-weight: 700;
        text-transform: uppercase;
        letter-spacing: 0.08em;
        color: var(--text-muted);
    }

    .sidebar-nav-group {
        margin-bottom: 2px;
    }

    .sidebar-group-header {
        display: flex;
        align-items: center;
        padding: 10px 14px;
        margin: 0 8px;
        border-radius: 8px;
        color: var(--text-primary);
        font-weight: 600;
        font-size: 13px;
        cursor: pointer;
        transition: all 0.15s;
        text-decoration: none;
        gap: 10px;
        justify-content: flex-start;
    }

    .sidebar-group-header:hover {
        background: var(--bg-tertiary);
    }

    .sidebar-group-header:focus-visible {
        outline: 2px solid var(--accent-color);
        outline-offset: 2px;
    }

    .sidebar-group-header.active {
        color: var(--accent-color);
        background: var(--accent-light);
    }

    .sidebar-group-header .sidebar-icon {
        flex-shrink: 0;
        font-size: 14px;
        opacity: 0.85;
    }

    .sidebar-group-header .sidebar-text {
        flex: 1;
        white-space: nowrap;
        overflow: hidden;
        text-overflow: ellipsis;
    }

    .sidebar-chevron {
        flex-shrink: 0;
        transition: transform 0.2s ease;
        font-size: 8px;
        opacity: 0.5;
    }

    .sidebar-group-header:hover .sidebar-chevron {
        opacity: 0.8;
    }

    .sidebar-group-header.expanded .sidebar-chevron {
        transform: rotate(90deg);
    }

    .sidebar-group-items {
        overflow: hidden;
        max-height: 0;
        transition: max-height 0.25s ease-out;
    }

    .sidebar-group-items.expanded {
        max-height: 2000px;
        transition: max-height 0.35s ease-in;
    }

    .sidebar-link {
        display: flex;
        align-items: center;
        position: relative;
        padding: 7px 14px 7px 38px;
        margin: 1px 8px;
        border-radius: 6px;
        color: var(--text-secondary);
        text-decoration: none;
        font-size: 13px;
        font-weight: 450;
        transition: all 0.15s;
        gap: 8px;
    }

    .sidebar-link:hover {
        color: var(--text-primary);
        background: var(--bg-tertiary);
    }

    .sidebar-link.active {
        color: var(--accent-color);
        background: var(--accent-light);
        font-weight: 500;
    }

    .sidebar-link.active::before {
        content: '';
        position: absolute;
        left: 8px;
        width: 3px;
        height: 18px;
        background: var(--accent-color);
        border-radius: 0 2px 2px 0;
    }

    .sidebar-link-icon {
        font-size: 13px;
        opacity: 0.5;
        flex-shrink: 0;
    }

    .sidebar-link:hover .sidebar-link-icon {
        opacity: 0.7;
    }
    
    /* Main content */
    .content-wrapper {
        flex: 1;
        min-width: 0;
        display: flex;
        margin-left: var(--sidebar-width);
    }

    .content {
        flex: 1;
        max-width: 820px;
        margin: 0 auto;
        padding: 32px 48px;
    }
    
    /* Right sidebar - TOC */
    .toc-sidebar {
        position: fixed;
        top: calc(var(--nav-height) + 24px);
        right: 0;
        width: var(--toc-width);
        padding: 0 24px;
        display: none;
    }

    @media (min-width: 1440px) {
        .toc-sidebar { display: block; }
        .content-wrapper { margin-right: var(--toc-width); }
    }
    
    .toc-title {
        font-size: 12px;
        font-weight: 600;
        text-transform: uppercase;
        letter-spacing: 0.05em;
        color: var(--text-muted);
        margin-bottom: 12px;
    }
    
    .toc-list {
        list-style: none;
        font-size: 13px;
        border-left: 1px solid var(--border-color);
    }
    
    .toc-item {
        margin: 0;
    }
    
    .toc-link {
        display: block;
        padding: 4px 0 4px 16px;
        color: var(--text-secondary);
        text-decoration: none;
        transition: all 0.15s;
        border-left: 2px solid transparent;
        margin-left: -1px;
    }
    
    .toc-link:hover {
        color: var(--text-primary);
    }
    
    .toc-link.active {
        color: var(--accent-color);
        border-left-color: var(--accent-color);
    }
    
    .toc-link.level-3 { padding-left: 32px; font-size: 12px; }
    
    /* Typography */
    h1, h2, h3, h4, h5, h6 {
        color: var(--text-primary);
        font-weight: 700;
        line-height: 1.3;
    }
    
    h1 {
        font-size: 2.25rem;
        margin: 0 0 24px 0;
        padding-bottom: 16px;
        border-bottom: 1px solid var(--border-color);
    }
    
    h2 {
        font-size: 1.5rem;
        margin: 40px 0 16px 0;
        padding-bottom: 8px;
        border-bottom: 1px solid var(--border-color);
    }
    
    h3 {
        font-size: 1.25rem;
        margin: 32px 0 12px 0;
    }
    
    h4 {
        font-size: 1rem;
        margin: 24px 0 8px 0;
    }
    
    p { margin-bottom: 16px; color: var(--text-secondary); }
    
    a {
        color: var(--accent-color);
        text-decoration: none;
        font-weight: 500;
    }
    
    a:hover { text-decoration: underline; }
    
    /* Code blocks */
    code {
        font-family: 'Fira Code', 'JetBrains Mono', 'SF Mono', Consolas, monospace;
        font-size: 0.875em;
        background: var(--bg-code);
        color: #e2e8f0;
        padding: 0.2em 0.4em;
        border-radius: 4px;
    }
    
    .code-block-wrapper {
        position: relative;
        margin: 20px 0;
        border-radius: 12px;
        overflow: hidden;
        background: var(--bg-code);
        border: 1px solid #334155;
    }
    
    .code-header {
        display: flex;
        align-items: center;
        justify-content: space-between;
        padding: 10px 16px;
        background: #1a202c;
        border-bottom: 1px solid #334155;
    }
    
    .code-lang {
        font-size: 12px;
        font-weight: 600;
        text-transform: uppercase;
        color: #94a3b8;
        display: flex;
        align-items: center;
        gap: 6px;
    }
    
    .code-lang-dot {
        width: 8px;
        height: 8px;
        border-radius: 50%;
    }
    
    .code-actions {
        display: flex;
        gap: 8px;
    }
    
    .code-copy-btn {
        background: #334155;
        border: none;
        color: #94a3b8;
        padding: 4px 10px;
        border-radius: 6px;
        font-size: 12px;
        cursor: pointer;
        display: flex;
        align-items: center;
        gap: 4px;
        transition: all 0.2s;
    }
    
    .code-copy-btn:hover {
        background: #475569;
        color: #e2e8f0;
    }
    
    pre {
        margin: 0;
        padding: 16px;
        overflow-x: auto;
    }
    
    pre code {
        background: transparent;
        padding: 0;
        font-size: 13px;
        line-height: 1.6;
        color: #e2e8f0;
        display: block;
    }
    
    /* Inline code fix */
    p code, li code, td code {
        background: var(--bg-tertiary);
        color: var(--accent-color);
        padding: 0.15em 0.4em;
    }
    
    /* Tables */
    .table-wrapper {
        overflow-x: auto;
        margin: 20px 0;
        border-radius: 8px;
        border: 1px solid var(--border-color);
    }
    
    table {
        width: 100%;
        border-collapse: collapse;
        font-size: 14px;
    }
    
    th, td {
        padding: 12px 16px;
        text-align: left;
        border-bottom: 1px solid var(--border-color);
    }
    
    th {
        background: var(--bg-secondary);
        font-weight: 600;
        color: var(--text-primary);
    }
    
    tr:last-child td { border-bottom: none; }
    
    tr:hover td { background: var(--bg-secondary); }
    
    /* Method badges */
    .method-badge {
        display: inline-flex;
        align-items: center;
        padding: 3px 10px;
        border-radius: 4px;
        font-size: 11px;
        font-weight: 700;
        font-family: monospace;
        text-transform: uppercase;
    }
    
    .method-get { background: rgba(34, 197, 94, 0.15); color: #22c55e; }
    .method-post { background: rgba(59, 130, 246, 0.15); color: #3b82f6; }
    .method-put { background: rgba(245, 158, 11, 0.15); color: #f59e0b; }
    .method-delete { background: rgba(239, 68, 68, 0.15); color: #ef4444; }
    .method-patch { background: rgba(168, 85, 247, 0.15); color: #a855f7; }
    
    /* Lists */
    ul, ol {
        padding-left: 24px;
        margin-bottom: 16px;
    }
    
    li { margin: 8px 0; color: var(--text-secondary); }
    li > ul, li > ol { margin-bottom: 0; }
    
    /* Blockquotes */
    blockquote {
        border-left: 4px solid var(--accent-color);
        padding: 16px 20px;
        margin: 20px 0;
        background: var(--accent-light);
        border-radius: 0 8px 8px 0;
    }
    
    blockquote p { margin: 0; color: var(--text-primary); }
    
    /* Callouts */
    .callout {
        padding: 16px 20px;
        margin: 20px 0;
        border-radius: 8px;
        display: flex;
        gap: 12px;
    }
    
    .callout-icon { font-size: 20px; line-height: 1; }
    .callout-content { flex: 1; }
    .callout-title { font-weight: 600; margin-bottom: 4px; }
    
    .callout-info { background: rgba(59, 130, 246, 0.1); border: 1px solid rgba(59, 130, 246, 0.3); }
    .callout-info .callout-title { color: #3b82f6; }
    
    .callout-warning { background: rgba(245, 158, 11, 0.1); border: 1px solid rgba(245, 158, 11, 0.3); }
    .callout-warning .callout-title { color: #f59e0b; }
    
    .callout-success { background: rgba(34, 197, 94, 0.1); border: 1px solid rgba(34, 197, 94, 0.3); }
    .callout-success .callout-title { color: #22c55e; }
    
    .callout-error { background: rgba(239, 68, 68, 0.1); border: 1px solid rgba(239, 68, 68, 0.3); }
    .callout-error .callout-title { color: #ef4444; }
    
    /* Horizontal rule */
    hr {
        border: none;
        border-top: 1px solid var(--border-color);
        margin: 32px 0;
    }
    
    /* Breadcrumb */
    .breadcrumb {
        display: flex;
        align-items: center;
        gap: 6px;
        margin-bottom: 24px;
        font-size: 13px;
        color: var(--text-muted);
    }
    
    .breadcrumb a {
        color: var(--text-secondary);
        text-decoration: none;
    }
    
    .breadcrumb a:hover {
        color: var(--accent-color);
        text-decoration: none;
    }
    
    .breadcrumb-sep { color: var(--text-muted); }
    .breadcrumb-current { color: var(--text-primary); font-weight: 500; }
    
    /* Card grid for home */
    .section-title {
        font-size: 1.25rem;
        font-weight: 700;
        margin: 32px 0 16px 0;
        color: var(--text-primary);
        display: flex;
        align-items: center;
        gap: 8px;
    }
    
    .card-grid {
        display: grid;
        grid-template-columns: repeat(auto-fill, minmax(280px, 1fr));
        gap: 16px;
        margin: 16px 0;
    }
    
    .card {
        background: var(--bg-secondary);
        border: 1px solid var(--border-color);
        border-radius: 12px;
        padding: 20px;
        transition: all 0.2s;
        text-decoration: none;
        display: block;
    }
    
    .card:hover {
        border-color: var(--accent-color);
        transform: translateY(-2px);
        box-shadow: 0 8px 24px rgba(0,0,0,0.08);
    }
    
    .card-header {
        display: flex;
        align-items: center;
        gap: 10px;
        margin-bottom: 8px;
    }
    
    .card-icon {
        width: 36px;
        height: 36px;
        background: var(--accent-light);
        border-radius: 8px;
        display: flex;
        align-items: center;
        justify-content: center;
        font-size: 18px;
    }
    
    .card-title {
        font-size: 16px;
        font-weight: 600;
        color: var(--text-primary);
    }
    
    .card-description {
        color: var(--text-secondary);
        font-size: 13px;
        line-height: 1.5;
    }
    
    .card-meta {
        display: flex;
        gap: 12px;
        margin-top: 12px;
        font-size: 12px;
        color: var(--text-muted);
    }
    
    /* File list for indexes */
    .file-list {
        list-style: none;
        padding: 0;
        margin: 16px 0;
    }
    
    .file-item {
        display: flex;
        align-items: center;
        padding: 14px 16px;
        border: 1px solid var(--border-color);
        border-radius: 8px;
        margin: 8px 0;
        background: var(--bg-secondary);
        transition: all 0.2s;
        text-decoration: none;
    }
    
    .file-item:hover {
        border-color: var(--accent-color);
        background: var(--accent-light);
    }
    
    .file-item-icon {
        font-size: 20px;
        margin-right: 12px;
    }
    
    .file-item-title {
        flex: 1;
        font-weight: 500;
        color: var(--text-primary);
    }
    
    .file-item-arrow {
        color: var(--text-muted);
    }
    
    /* Raw mode link */
    .raw-link {
        position: fixed;
        bottom: 24px;
        right: 24px;
        background: var(--bg-secondary);
        border: 1px solid var(--border-color);
        padding: 10px 16px;
        border-radius: 10px;
        color: var(--text-secondary);
        font-size: 13px;
        text-decoration: none;
        display: flex;
        align-items: center;
        gap: 8px;
        transition: all 0.2s;
        z-index: 50;
    }
    
    .raw-link:hover {
        background: var(--bg-tertiary);
        color: var(--text-primary);
        text-decoration: none;
        border-color: var(--accent-color);
    }
    
    /* Footer */
    .footer {
        margin-top: 64px;
        padding-top: 24px;
        border-top: 1px solid var(--border-color);
        font-size: 13px;
        color: var(--text-muted);
        display: flex;
        justify-content: space-between;
        align-items: center;
    }
    
    .footer-links {
        display: flex;
        gap: 16px;
    }
    
    .footer-links a {
        color: var(--text-secondary);
    }
    
    /* Edit page link */
    .edit-page {
        display: inline-flex;
        align-items: center;
        gap: 6px;
        font-size: 13px;
        color: var(--text-muted);
        margin-top: 32px;
    }
    
    /* Search results dropdown */
    .search-results {
        position: absolute;
        top: 100%;
        left: 0;
        right: 0;
        margin-top: 8px;
        background: var(--bg-primary);
        border: 1px solid var(--border-color);
        border-radius: 10px;
        box-shadow: 0 10px 40px rgba(0,0,0,0.15);
        max-height: 400px;
        overflow-y: auto;
        display: none;
        z-index: 200;
    }
    
    .search-results.active { display: block; }
    
    .search-result-item {
        display: block;
        padding: 12px 16px;
        color: var(--text-primary);
        text-decoration: none;
        border-bottom: 1px solid var(--border-color);
        transition: background 0.15s;
    }
    
    .search-result-item:last-child { border-bottom: none; }
    
    .search-result-item:hover {
        background: var(--bg-secondary);
    }
    
    .search-result-title {
        font-weight: 600;
        margin-bottom: 4px;
    }
    
    .search-result-path {
        font-size: 12px;
        color: var(--text-muted);
    }
    
    .search-no-results {
        padding: 24px 16px;
        text-align: center;
        color: var(--text-muted);
    }
    
    /* Backdrop for mobile sidebar */
    .sidebar-backdrop {
        display: none;
        position: fixed;
        inset: 0;
        background: rgba(0,0,0,0.5);
        z-index: 40;
        opacity: 0;
        transition: opacity 0.3s;
    }
    
    .sidebar-backdrop.active {
        display: block;
        opacity: 1;
    }
    
    /* Responsive */
    @media (max-width: 1024px) {
        .sidebar {
            transform: translateX(-100%);
        }

        .sidebar.open {
            transform: translateX(0);
        }

        .content-wrapper {
            margin-left: 0;
        }

        .menu-toggle {
            display: flex;
        }

        .content {
            padding: 24px;
        }

        .search-container {
            display: none;
        }
    }
    
    @media (max-width: 640px) {
        .nav-right { display: none; }
        
        h1 { font-size: 1.75rem; }
        h2 { font-size: 1.25rem; }
        h3 { font-size: 1.1rem; }
        
        .card-grid { grid-template-columns: 1fr; }
        
        .footer {
            flex-direction: column;
            gap: 16px;
            text-align: center;
        }
    }
    """

    # JavaScript for interactivity
    JS_SCRIPT = """
    <script>
    (function() {
        // Sidebar state
        const sidebar = document.querySelector('.sidebar');
        const backdrop = document.querySelector('.sidebar-backdrop');
        const menuToggle = document.querySelector('.menu-toggle');
        
        // Mobile sidebar toggle
        if (menuToggle) {
            menuToggle.addEventListener('click', () => {
                sidebar.classList.toggle('open');
                backdrop.classList.toggle('active');
            });
        }
        
        if (backdrop) {
            backdrop.addEventListener('click', () => {
                sidebar.classList.remove('open');
                backdrop.classList.remove('active');
            });
        }
        
        // Expand sidebar groups containing active link
        document.querySelectorAll('.sidebar-link.active').forEach(link => {
            const group = link.closest('.sidebar-group-items');
            if (group) group.classList.add('expanded');
        });
        
        // Sidebar group toggle
        document.querySelectorAll('.sidebar-group-header[data-toggle]').forEach(header => {
            header.addEventListener('click', () => {
                const targetId = header.getAttribute('data-toggle');
                const target = document.getElementById(targetId);
                if (target) {
                    const isExpanded = target.classList.toggle('expanded');
                    header.classList.toggle('expanded');
                    // Update aria-expanded for accessibility
                    header.setAttribute('aria-expanded', isExpanded);
                }
            });
            
            // Keyboard support for accessibility (Enter/Space)
            header.addEventListener('keydown', (e) => {
                if (e.key === 'Enter' || e.key === ' ') {
                    e.preventDefault();
                    header.click();
                }
            });
        });
        
        // Search functionality
        const searchInput = document.querySelector('.search-input');
        const searchResults = document.querySelector('.search-results');
        let searchData = [];
        
        // Build search index from sidebar links
        document.querySelectorAll('.sidebar-link').forEach(link => {
            const title = link.textContent.trim();
            const path = link.getAttribute('href');
            const group = link.closest('.sidebar-nav-group')?.querySelector('.sidebar-group-header')?.textContent?.trim() || '';
            searchData.push({ title, path, group });
        });
        
        if (searchInput && searchResults) {
            searchInput.addEventListener('input', (e) => {
                const query = e.target.value.toLowerCase().trim();
                
                if (!query) {
                    searchResults.classList.remove('active');
                    return;
                }
                
                const results = searchData.filter(item => 
                    item.title.toLowerCase().includes(query) || 
                    item.group.toLowerCase().includes(query)
                ).slice(0, 8);
                
                if (results.length === 0) {
                    searchResults.innerHTML = '<div class="search-no-results">No results found</div>';
                } else {
                    searchResults.innerHTML = results.map(r => 
                        '<a href="' + r.path + '" class="search-result-item">' +
                        '<div class="search-result-title">' + r.title + '</div>' +
                        '<div class="search-result-path">' + r.group + '</div>' +
                        '</a>'
                    ).join('');
                }
                
                searchResults.classList.add('active');
            });
            
            // Close search on click outside
            document.addEventListener('click', (e) => {
                if (!searchInput.contains(e.target) && !searchResults.contains(e.target)) {
                    searchResults.classList.remove('active');
                }
            });
            
            // Keyboard shortcut (Cmd/Ctrl + K)
            document.addEventListener('keydown', (e) => {
                if ((e.metaKey || e.ctrlKey) && e.key === 'k') {
                    e.preventDefault();
                    searchInput.focus();
                }
            });
        }
        
        // TOC scroll spy
        const tocLinks = document.querySelectorAll('.toc-link');
        const headings = document.querySelectorAll('h2[id], h3[id]');
        
        if (tocLinks.length > 0 && headings.length > 0) {
            const observer = new IntersectionObserver((entries) => {
                entries.forEach(entry => {
                    if (entry.isIntersecting) {
                        tocLinks.forEach(link => link.classList.remove('active'));
                        const activeLink = document.querySelector('.toc-link[href="#' + entry.target.id + '"]');
                        if (activeLink) activeLink.classList.add('active');
                    }
                });
            }, { rootMargin: '-80px 0px -80% 0px' });
            
            headings.forEach(h => observer.observe(h));
        }
        
        // Copy code buttons
        document.querySelectorAll('.code-copy-btn').forEach(btn => {
            btn.addEventListener('click', async () => {
                const code = btn.closest('.code-block-wrapper').querySelector('code').textContent;
                await navigator.clipboard.writeText(code);
                btn.textContent = '✓ Copied';
                setTimeout(() => btn.innerHTML = '<span>📋</span> Copy', 2000);
            });
        });
    })();
    </script>
    """
    
    @classmethod
    def _extract_toc(cls, html: str) -> List[TocItem]:
        """Extract table of contents from HTML headers"""
        toc = []
        for match in re.finditer(r'<h([23]) id="([^"]+)">([^<]+)</h\1>', html):
            level = int(match.group(1))
            slug = match.group(2)
            text = match.group(3)
            toc.append(TocItem(level=level, text=text, slug=slug))
        return toc
    
    @classmethod
    def _build_sidebar(cls, current_path: str = "", base_url: str = "/documentation") -> str:
        """Build sidebar navigation HTML - links are handled by main.py"""
        # Note: Categories will be populated by the caller with actual file data
        # This returns a template that gets filled in render_page/render_home
        return ""
    
    @classmethod
    def _slugify(cls, text: str) -> str:
        """Convert text to URL-friendly slug"""
        return re.sub(r'[^\w\s-]', '', text.lower()).strip().replace(' ', '-')
    
    @classmethod
    def render_markdown(cls, content: str) -> Tuple[str, List[TocItem]]:
        """Convert markdown to HTML with enhanced formatting. Returns (html, toc_items)."""
        html = content
        
        # Escape HTML entities first (but preserve our tags)
        html = html.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
        
        # Convert code blocks with language hints
        def code_block_replacer(match):
            lang = match.group(1) or 'text'
            code = match.group(2).strip()
            # Unescape for code blocks
            code = code.replace('&lt;', '<').replace('&gt;', '>').replace('&amp;', '&')
            
            # Language colors
            lang_colors = {
                'python': '#3776AB',
                'javascript': '#F7DF1E',
                'typescript': '#3178C6',
                'json': '#292929',
                'bash': '#4EAA25',
                'shell': '#4EAA25',
                'sql': '#336791',
                'http': '#009688',
                'yaml': '#CB171E',
                'dockerfile': '#2496ED',
            }
            color = lang_colors.get(lang.lower(), '#6b7280')
            
            return f'''<div class="code-block-wrapper">
                <div class="code-header">
                    <span class="code-lang"><span class="code-lang-dot" style="background:{color}"></span>{lang}</span>
                    <button class="code-copy-btn"><span>📋</span> Copy</button>
                </div>
                <pre><code class="language-{lang}">{code}</code></pre>
            </div>'''
        
        html = re.sub(r'```(\w+)?\n(.*?)```', code_block_replacer, html, flags=re.DOTALL)
        
        # Convert inline code
        html = re.sub(r'`([^`]+)`', r'<code>\1</code>', html)
        
        # Convert headers with IDs for linking
        def header_replacer(match):
            level = int(len(match.group(1)))
            text = match.group(2)
            slug = cls._slugify(text)
            return f'<h{level} id="{slug}">{text}</h{level}>'
        
        html = re.sub(r'^(#{1,6})\s+(.+)$', header_replacer, html, flags=re.MULTILINE)
        
        # Convert tables with enhanced formatting
        def table_replacer(match):
            lines = match.group(0).strip().split('\n')
            if len(lines) < 2:
                return match.group(0)
            
            headers = [cell.strip() for cell in lines[0].split('|') if cell.strip()]
            data_rows = []
            for line in lines[2:]:
                cells = [cell.strip() for cell in line.split('|') if cell.strip()]
                if cells:
                    data_rows.append(cells)
            
            table_html = '<div class="table-wrapper"><table><thead><tr>'
            for h in headers:
                table_html += f'<th>{h}</th>'
            table_html += '</tr></thead><tbody>'
            
            for row in data_rows:
                table_html += '<tr>'
                for cell in row:
                    # Add method badges
                    if cell.upper() in ['GET', 'POST', 'PUT', 'DELETE', 'PATCH']:
                        cell = f'<span class="method-badge method-{cell.lower()}">{cell}</span>'
                    table_html += f'<td>{cell}</td>'
                table_html += '</tr>'
            
            table_html += '</tbody></table></div>'
            return table_html
        
        html = re.sub(r'(\|.+\|\n)+', table_replacer, html)
        
        # Convert callouts (blockquotes with special markers)
        def callout_replacer(match):
            marker = match.group(1).lower() if match.group(1) else None
            text = match.group(2)
            if marker in ['!warning', '!warn']:
                return f'<div class="callout callout-warning"><span class="callout-icon">⚠️</span><div class="callout-content"><div class="callout-title">Warning</div><p>{text}</p></div></div>'
            elif marker in ['!info', '!note']:
                return f'<div class="callout callout-info"><span class="callout-icon">ℹ️</span><div class="callout-content"><div class="callout-title">Info</div><p>{text}</p></div></div>'
            elif marker in ['!tip']:
                return f'<div class="callout callout-success"><span class="callout-icon">💡</span><div class="callout-content"><div class="callout-title">Tip</div><p>{text}</p></div></div>'
            elif marker in ['!danger', '!error']:
                return f'<div class="callout callout-error"><span class="callout-icon">🚨</span><div class="callout-content"><div class="callout-title">Danger</div><p>{text}</p></div></div>'
            return f'<blockquote><p>{text}</p></blockquote>'
        
        html = re.sub(r'^&gt;\s*(!\w+)?\s*(.+)$', callout_replacer, html, flags=re.MULTILINE)
        
        # Convert bold and italic
        html = re.sub(r'\*\*\*(.+?)\*\*\*', r'<strong><em>\1</em></strong>', html)
        html = re.sub(r'\*\*(.+?)\*\*', r'<strong>\1</strong>', html)
        html = re.sub(r'\*(.+?)\*', r'<em>\1</em>', html)
        
        # Convert links
        html = re.sub(r'\[([^\]]+)\]\(([^)]+)\)', r'<a href="\2">\1</a>', html)
        
        # Convert horizontal rules
        html = re.sub(r'^---+$', '<hr>', html, flags=re.MULTILINE)
        
        # Convert unordered lists
        html = re.sub(r'^[-*]\s+(.+)$', r'<li>\1</li>', html, flags=re.MULTILINE)
        
        # Convert ordered lists
        html = re.sub(r'^\d+\.\s+(.+)$', r'<li>\1</li>', html, flags=re.MULTILINE)
        
        # Wrap consecutive list items
        html = re.sub(r'(<li>.+</li>\n?)+', lambda m: f'<ul>{m.group(0)}</ul>', html)
        
        # Convert paragraphs
        paragraphs = html.split('\n\n')
        processed = []
        for p in paragraphs:
            p = p.strip()
            if p and not p.startswith('<'):
                p = f'<p>{p}</p>'
            processed.append(p)
        html = '\n'.join(processed)
        
        # Clean up newlines within paragraphs
        html = re.sub(r'<p>(.+?)</p>', lambda m: f'<p>{m.group(1).replace(chr(10), " ")}</p>', html, flags=re.DOTALL)
        
        # Extract TOC
        toc = cls._extract_toc(html)
        
        return html, toc
    
    @classmethod
    def render_page(
        cls,
        content: str,
        title: str,
        path: str = "",
        base_url: str = "/documentation",
        categories: List[DocCategory] = None
    ) -> str:
        """Render a complete HTML page with navigation"""
        html_content, toc = cls.render_markdown(content)
        
        # Build breadcrumb
        breadcrumb_html = f'<a href="{base_url}">Docs</a>'
        if path:
            parts = path.split('/')
            current_path = ""
            for i, part in enumerate(parts[:-1]):
                current_path += f"/{part}" if current_path else part
                breadcrumb_html += f' <span class="breadcrumb-sep">/</span> <a href="{base_url}/{current_path}">{part}</a>'
            if parts:
                breadcrumb_html += f' <span class="breadcrumb-sep">/</span> <span class="breadcrumb-current">{parts[-1]}</span>'
        
        # Build sidebar
        sidebar_html = cls._build_sidebar_html(categories, path, base_url)
        
        # Build TOC sidebar
        toc_html = ""
        if toc:
            toc_html = '<div class="toc-sidebar"><div class="toc-title">On this page</div><ul class="toc-list">'
            for item in toc:
                level_class = f" level-{item.level}" if item.level == 3 else ""
                toc_html += f'<li class="toc-item"><a href="#{item.slug}" class="toc-link{level_class}">{item.text}</a></li>'
            toc_html += '</ul></div>'
        
        # Determine raw URL
        raw_url = f"{base_url}/{path}?format=raw" if path else f"{base_url}?format=raw"
        
        return f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{title} - API Documentation</title>
    <link rel="preconnect" href="https://fonts.googleapis.com">
    <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
    <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap" rel="stylesheet">
    <style>{cls.CSS_STYLES}</style>
</head>
<body>
    <nav class="top-nav">
        <div class="nav-left">
            <button class="menu-toggle" aria-label="Toggle menu">
                <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                    <line x1="3" y1="6" x2="21" y2="6"></line>
                    <line x1="3" y1="12" x2="21" y2="12"></line>
                    <line x1="3" y1="18" x2="21" y2="18"></line>
                </svg>
            </button>
            <a href="{base_url}" class="nav-brand">
                <span class="nav-brand-icon">A</span>
                <span>API Docs</span>
            </a>
        </div>
        
        <div class="search-container">
            <div class="search-box">
                <span class="search-icon">🔍</span>
                <input type="text" class="search-input" placeholder="Search documentation...">
                <span class="search-shortcut">⌘K</span>
                <div class="search-results"></div>
            </div>
        </div>
        
        <div class="nav-right">
            <a href="/docs" class="nav-link">OpenAPI</a>
            <a href="/redoc" class="nav-link">ReDoc</a>
        </div>
    </nav>
    
    <div class="sidebar-backdrop"></div>
    
    <div class="layout">
        <aside class="sidebar">
            {sidebar_html}
        </aside>
        
        <div class="content-wrapper">
            <main class="content">
                <nav class="breadcrumb">{breadcrumb_html}</nav>
                <article>{html_content}</article>
                <div class="edit-page">
                    <span>📄</span>
                    <a href="{raw_url}">View raw markdown</a>
                </div>
            </main>
            {toc_html}
        </div>
    </div>
    
    <a href="{raw_url}" class="raw-link" title="Raw markdown for LLM/API consumption">
        <span>📄</span> Raw MD
    </a>
    
    {cls.JS_SCRIPT}
</body>
</html>"""
    
    @classmethod
    def _build_sidebar_html(
        cls,
        categories: List[DocCategory],
        current_path: str,
        base_url: str
    ) -> str:
        """Build sidebar HTML from categories"""
        if not categories:
            return ""
        
        html = '<div class="sidebar-section"><div class="sidebar-section-title">Documentation</div></div>'
        
        for category in categories:
            # Check if current path is in this category
            is_active = current_path.startswith(category.path + "/") or current_path == category.path
            expanded_class = " expanded" if is_active else ""

            if category.files:
                aria_expanded = "true" if is_active else "false"
                html += f'''
                <div class="sidebar-nav-group">
                    <div class="sidebar-group-header{expanded_class}" data-toggle="group-{cls._slugify(category.name)}" role="button" tabindex="0" aria-expanded="{aria_expanded}">
                        <span class="sidebar-icon">{cls._get_category_icon(category.name)}</span>
                        <span class="sidebar-text">{category.title}</span>
                        <span class="sidebar-chevron">▶</span>
                    </div>
                    <div id="group-{cls._slugify(category.name)}" class="sidebar-group-items{expanded_class}">'''

                for f in category.files:
                    file_full_path = f"{category.path}/{f.name}"
                    is_current = current_path == file_full_path
                    active_class = " active" if is_current else ""
                    icon = "📖" if f.is_readme else "📄"

                    html += f'''
                        <a href="{base_url}/{file_full_path}" class="sidebar-link{active_class}">
                            <span class="sidebar-link-icon">{icon}</span>
                            {f.title}
                        </a>'''

                html += '</div></div>'
            else:
                # Category with no files, just a link
                is_current = current_path == category.path
                active_class = " active" if is_current else ""
                html += f'''
                <div class="sidebar-nav-group">
                    <a href="{base_url}/{category.path}" class="sidebar-group-header{active_class}">
                        <span class="sidebar-icon">{cls._get_category_icon(category.name)}</span>
                        <span class="sidebar-text">{category.title}</span>
                    </a>
                </div>'''
        
        return html
    
    @classmethod
    def _get_category_icon(cls, name: str) -> str:
        """Get an appropriate icon for a category"""
        icons = {
            'users': '👥',
            'groups': '📁',
            'projects': '🎯',
            'roles': '🔑',
            'permissions': '🔐',
            'audit_logs': '📋',
            'audit': '📋',
            'usage': '📖',
            'api': '🔌',
            'guides': '📚',
            'getting-started': '🚀',
            'authentication': '🔐',
            'admin': '⚙️',
        }
        name_lower = name.lower().replace('-', '').replace('_', '')
        return icons.get(name_lower, '📁')
    
    @classmethod
    def render_index(
        cls,
        title: str,
        files: List[DocumentationFile],
        base_url: str = "/documentation",
        categories: List[DocCategory] = None
    ) -> str:
        """Render an index page listing documentation files"""
        file_items = ""
        for f in files:
            icon = "📖" if f.is_readme else "📄"
            file_items += f'''
            <a href="{base_url}/{f.path}" class="file-item">
                <span class="file-item-icon">{icon}</span>
                <span class="file-item-title">{f.title}</span>
                <span class="file-item-arrow">→</span>
            </a>'''
        
        sidebar_html = cls._build_sidebar_html(categories, "", base_url)
        
        return f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{title} - API Documentation</title>
    <link rel="preconnect" href="https://fonts.googleapis.com">
    <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
    <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap" rel="stylesheet">
    <style>{cls.CSS_STYLES}</style>
</head>
<body>
    <nav class="top-nav">
        <div class="nav-left">
            <button class="menu-toggle" aria-label="Toggle menu">
                <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                    <line x1="3" y1="6" x2="21" y2="6"></line>
                    <line x1="3" y1="12" x2="21" y2="12"></line>
                    <line x1="3" y1="18" x2="21" y2="18"></line>
                </svg>
            </button>
            <a href="{base_url}" class="nav-brand">
                <span class="nav-brand-icon">A</span>
                <span>API Docs</span>
            </a>
        </div>
        
        <div class="search-container">
            <div class="search-box">
                <span class="search-icon">🔍</span>
                <input type="text" class="search-input" placeholder="Search documentation...">
                <span class="search-shortcut">⌘K</span>
                <div class="search-results"></div>
            </div>
        </div>
        
        <div class="nav-right">
            <a href="/docs" class="nav-link">OpenAPI</a>
            <a href="/redoc" class="nav-link">ReDoc</a>
        </div>
    </nav>
    
    <div class="sidebar-backdrop"></div>
    
    <div class="layout">
        <aside class="sidebar">
            {sidebar_html}
        </aside>
        
        <div class="content-wrapper">
            <main class="content">
                <h1>📁 {title}</h1>
                <ul class="file-list">
                    {file_items}
                </ul>
            </main>
        </div>
    </div>
    
    {cls.JS_SCRIPT}
</body>
</html>"""
    
    @classmethod
    def render_home(
        cls,
        categories: List[DocCategory],
        base_url: str = "/documentation"
    ) -> str:
        """Render the documentation home page with categories"""
        # Build cards for each category
        category_cards = ""
        for cat in categories:
            icon = cls._get_category_icon(cat.name)
            file_count = len(cat.files)
            category_cards += f'''
            <a href="{base_url}/{cat.path}" class="card">
                <div class="card-header">
                    <div class="card-icon">{icon}</div>
                    <div class="card-title">{cat.title}</div>
                </div>
                <div class="card-description">
                    {file_count} document{"s" if file_count != 1 else ""} available
                </div>
            </a>'''
        
        # Build sidebar
        sidebar_html = cls._build_sidebar_html(categories, "", base_url)
        
        return f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>API Documentation</title>
    <link rel="preconnect" href="https://fonts.googleapis.com">
    <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
    <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap" rel="stylesheet">
    <style>{cls.CSS_STYLES}</style>
</head>
<body>
    <nav class="top-nav">
        <div class="nav-left">
            <button class="menu-toggle" aria-label="Toggle menu">
                <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                    <line x1="3" y1="6" x2="21" y2="6"></line>
                    <line x1="3" y1="12" x2="21" y2="12"></line>
                    <line x1="3" y1="18" x2="21" y2="18"></line>
                </svg>
            </button>
            <a href="{base_url}" class="nav-brand">
                <span class="nav-brand-icon">A</span>
                <span>API Docs</span>
            </a>
        </div>
        
        <div class="search-container">
            <div class="search-box">
                <span class="search-icon">🔍</span>
                <input type="text" class="search-input" placeholder="Search documentation...">
                <span class="search-shortcut">⌘K</span>
                <div class="search-results"></div>
            </div>
        </div>
        
        <div class="nav-right">
            <a href="/docs" class="nav-link">OpenAPI</a>
            <a href="/redoc" class="nav-link">ReDoc</a>
        </div>
    </nav>
    
    <div class="sidebar-backdrop"></div>
    
    <div class="layout">
        <aside class="sidebar">
            {sidebar_html}
        </aside>
        
        <div class="content-wrapper">
            <main class="content">
                <h1>Welcome to the API Documentation</h1>
                <p style="font-size: 17px; color: var(--text-secondary); margin-top: -8px;">
                    Comprehensive guides and references for the authentication API.
                </p>
                
                <div class="section-title">
                    <span>⚡</span> Quick Links
                </div>
                <div class="card-grid">
                    <a href="/docs" class="card">
                        <div class="card-header">
                            <div class="card-icon" style="background: rgba(34, 197, 94, 0.1);">🔌</div>
                            <div class="card-title">OpenAPI / Swagger</div>
                        </div>
                        <div class="card-description">
                            Interactive API explorer with try-it-out functionality
                        </div>
                    </a>
                    <a href="/redoc" class="card">
                        <div class="card-header">
                            <div class="card-icon" style="background: rgba(168, 85, 247, 0.1);">📘</div>
                            <div class="card-title">ReDoc</div>
                        </div>
                        <div class="card-description">
                            Alternative API documentation with clean three-panel layout
                        </div>
                    </a>
                </div>
                
                <div class="section-title">
                    <span>📚</span> Documentation
                </div>
                <div class="card-grid">
                    {category_cards}
                </div>
            </main>
        </div>
    </div>
    
    {cls.JS_SCRIPT}
</body>
</html>"""


def get_documentation_files(docs_path: Path, subpath: str = "") -> List[DocumentationFile]:
    """Get list of documentation files from a directory"""
    target_path = docs_path / subpath if subpath else docs_path
    files = []
    
    if not target_path.exists():
        return files
    
    for f in sorted(target_path.glob("*.md")):
        title = f.stem.replace("-", " ").replace("_", " ").title()
        if f.stem.lower() == "readme":
            title = "Overview"
        
        rel_path = f"{subpath}/{f.name}" if subpath else f.name
        files.append(DocumentationFile(
            name=f.name,
            path=rel_path,
            title=title,
            is_readme=f.stem.lower() == "readme"
        ))
    
    # Sort with README first
    files.sort(key=lambda x: (not x.is_readme, x.name))
    
    return files


def get_documentation_categories(docs_path: Path) -> List[DocCategory]:
    """Get all documentation categories with their files"""
    categories = []
    
    # Get USAGE subdirectories as categories
    usage_path = docs_path / "USAGE"
    if not usage_path.exists():
        return categories
    
    # Find all subdirectories in USAGE
    for subdir in sorted(usage_path.iterdir()):
        if subdir.is_dir():
            name = subdir.name
            title = name.replace("-", " ").replace("_", " ").title()
            files = get_documentation_files(docs_path, f"USAGE/{name}")
            
            categories.append(DocCategory(
                name=name,
                title=title,
                path=f"USAGE/{name}",
                files=files
            ))
    
    # Add root USAGE files as "Guides" category
    root_files = []
    for f in sorted(usage_path.glob("*.md")):
        if f.stem.lower() == "readme":
            continue
        title = f.stem.replace("-", " ").replace("_", " ").title()
        root_files.append(DocumentationFile(
            name=f.name,
            path=f"USAGE/{f.name}",
            title=title,
            is_readme=False
        ))
    
    if root_files:
        categories.insert(0, DocCategory(
            name="guides",
            title="General Guides",
            path="USAGE",
            files=root_files
        ))
    
    return categories