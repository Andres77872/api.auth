"""
Documentation Renderer Utility

Provides markdown-to-HTML rendering with modern UI/UX styling
and support for raw markdown output for LLM consumption.
"""

import re
from pathlib import Path
from typing import Optional, Tuple, List
from dataclasses import dataclass


@dataclass
class DocumentationFile:
    """Represents a documentation file"""
    name: str
    path: str
    title: str
    is_readme: bool = False


class DocumentationRenderer:
    """
    Renders markdown documentation as styled HTML.
    Supports raw markdown output for LLM consumption.
    """
    
    # Modern dark theme CSS
    CSS_STYLES = """
    :root {
        --bg-primary: #0d1117;
        --bg-secondary: #161b22;
        --bg-tertiary: #21262d;
        --text-primary: #c9d1d9;
        --text-secondary: #8b949e;
        --text-muted: #6e7681;
        --border-color: #30363d;
        --accent-color: #58a6ff;
        --accent-hover: #79c0ff;
        --success-color: #3fb950;
        --warning-color: #d29922;
        --error-color: #f85149;
        --code-bg: #1f2428;
        --nav-bg: #010409;
    }
    
    * { box-sizing: border-box; margin: 0; padding: 0; }
    
    body {
        font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', 'Noto Sans', Helvetica, Arial, sans-serif;
        font-size: 16px;
        line-height: 1.6;
        color: var(--text-primary);
        background: var(--bg-primary);
        min-height: 100vh;
    }
    
    /* Navigation */
    .nav {
        position: sticky;
        top: 0;
        z-index: 100;
        background: var(--nav-bg);
        border-bottom: 1px solid var(--border-color);
        padding: 12px 24px;
        display: flex;
        align-items: center;
        gap: 24px;
        backdrop-filter: blur(10px);
    }
    
    .nav-brand {
        font-weight: 600;
        font-size: 18px;
        color: var(--text-primary);
        text-decoration: none;
        display: flex;
        align-items: center;
        gap: 8px;
    }
    
    .nav-links {
        display: flex;
        gap: 16px;
        margin-left: auto;
    }
    
    .nav-link {
        color: var(--text-secondary);
        text-decoration: none;
        padding: 6px 12px;
        border-radius: 6px;
        font-size: 14px;
        transition: all 0.2s;
    }
    
    .nav-link:hover {
        color: var(--text-primary);
        background: var(--bg-tertiary);
    }
    
    .nav-link.active {
        color: var(--accent-color);
        background: rgba(88, 166, 255, 0.1);
    }
    
    /* Main content */
    .container {
        max-width: 980px;
        margin: 0 auto;
        padding: 32px 24px;
    }
    
    /* Typography */
    h1, h2, h3, h4, h5, h6 {
        color: var(--text-primary);
        font-weight: 600;
        margin-top: 24px;
        margin-bottom: 16px;
        line-height: 1.25;
    }
    
    h1 { font-size: 2em; padding-bottom: 0.3em; border-bottom: 1px solid var(--border-color); }
    h2 { font-size: 1.5em; padding-bottom: 0.3em; border-bottom: 1px solid var(--border-color); }
    h3 { font-size: 1.25em; }
    h4 { font-size: 1em; }
    
    p { margin-bottom: 16px; }
    
    a {
        color: var(--accent-color);
        text-decoration: none;
    }
    
    a:hover {
        text-decoration: underline;
        color: var(--accent-hover);
    }
    
    /* Code */
    code {
        font-family: 'SF Mono', 'Fira Code', 'Consolas', monospace;
        font-size: 85%;
        background: var(--bg-tertiary);
        padding: 0.2em 0.4em;
        border-radius: 6px;
        color: var(--text-primary);
    }
    
    pre {
        background: var(--code-bg);
        border: 1px solid var(--border-color);
        border-radius: 8px;
        padding: 16px;
        overflow-x: auto;
        margin: 16px 0;
        position: relative;
    }
    
    pre code {
        background: transparent;
        padding: 0;
        font-size: 14px;
        line-height: 1.5;
        color: #e6edf3;
    }
    
    /* Copy button for code blocks */
    .code-block {
        position: relative;
    }
    
    .copy-btn {
        position: absolute;
        top: 8px;
        right: 8px;
        background: var(--bg-tertiary);
        border: 1px solid var(--border-color);
        color: var(--text-secondary);
        padding: 4px 8px;
        border-radius: 4px;
        font-size: 12px;
        cursor: pointer;
        opacity: 0;
        transition: opacity 0.2s;
    }
    
    .code-block:hover .copy-btn { opacity: 1; }
    .copy-btn:hover { background: var(--bg-primary); color: var(--text-primary); }
    
    /* Tables */
    table {
        width: 100%;
        border-collapse: collapse;
        margin: 16px 0;
        display: block;
        overflow-x: auto;
    }
    
    th, td {
        padding: 12px 16px;
        border: 1px solid var(--border-color);
        text-align: left;
    }
    
    th {
        background: var(--bg-secondary);
        font-weight: 600;
    }
    
    tr:nth-child(even) { background: var(--bg-secondary); }
    
    /* Lists */
    ul, ol {
        padding-left: 2em;
        margin-bottom: 16px;
    }
    
    li { margin: 8px 0; }
    li > ul, li > ol { margin-bottom: 0; }
    
    /* Blockquotes */
    blockquote {
        border-left: 4px solid var(--accent-color);
        padding: 12px 16px;
        margin: 16px 0;
        background: var(--bg-secondary);
        border-radius: 0 8px 8px 0;
        color: var(--text-secondary);
    }
    
    /* Horizontal rules */
    hr {
        border: none;
        border-top: 1px solid var(--border-color);
        margin: 24px 0;
    }
    
    /* Cards for index pages */
    .card-grid {
        display: grid;
        grid-template-columns: repeat(auto-fill, minmax(300px, 1fr));
        gap: 16px;
        margin: 24px 0;
    }
    
    .card {
        background: var(--bg-secondary);
        border: 1px solid var(--border-color);
        border-radius: 12px;
        padding: 20px;
        transition: all 0.2s;
    }
    
    .card:hover {
        border-color: var(--accent-color);
        transform: translateY(-2px);
    }
    
    .card-title {
        font-size: 18px;
        font-weight: 600;
        color: var(--text-primary);
        margin-bottom: 8px;
        display: flex;
        align-items: center;
        gap: 8px;
    }
    
    .card-title a {
        color: inherit;
    }
    
    .card-description {
        color: var(--text-secondary);
        font-size: 14px;
    }
    
    /* File list */
    .file-list {
        list-style: none;
        padding: 0;
    }
    
    .file-item {
        display: flex;
        align-items: center;
        padding: 12px 16px;
        border: 1px solid var(--border-color);
        border-radius: 8px;
        margin: 8px 0;
        background: var(--bg-secondary);
        transition: all 0.2s;
    }
    
    .file-item:hover {
        border-color: var(--accent-color);
        background: var(--bg-tertiary);
    }
    
    .file-item a {
        color: var(--text-primary);
        font-weight: 500;
        flex: 1;
    }
    
    .file-icon {
        margin-right: 12px;
        font-size: 20px;
    }
    
    /* Breadcrumb */
    .breadcrumb {
        display: flex;
        align-items: center;
        gap: 8px;
        margin-bottom: 24px;
        color: var(--text-secondary);
        font-size: 14px;
    }
    
    .breadcrumb a {
        color: var(--text-secondary);
    }
    
    .breadcrumb a:hover {
        color: var(--accent-color);
    }
    
    .breadcrumb-sep {
        color: var(--text-muted);
    }
    
    /* Table of contents */
    .toc {
        background: var(--bg-secondary);
        border: 1px solid var(--border-color);
        border-radius: 8px;
        padding: 16px 20px;
        margin: 16px 0;
    }
    
    .toc-title {
        font-weight: 600;
        margin-bottom: 12px;
        color: var(--text-primary);
    }
    
    .toc ul {
        list-style: none;
        padding-left: 0;
        margin: 0;
    }
    
    .toc li {
        margin: 6px 0;
    }
    
    .toc a {
        color: var(--text-secondary);
        font-size: 14px;
    }
    
    .toc a:hover {
        color: var(--accent-color);
    }
    
    /* Badges */
    .badge {
        display: inline-block;
        padding: 2px 8px;
        border-radius: 12px;
        font-size: 12px;
        font-weight: 500;
    }
    
    .badge-get { background: rgba(63, 185, 80, 0.2); color: var(--success-color); }
    .badge-post { background: rgba(88, 166, 255, 0.2); color: var(--accent-color); }
    .badge-put { background: rgba(210, 153, 34, 0.2); color: var(--warning-color); }
    .badge-delete { background: rgba(248, 81, 73, 0.2); color: var(--error-color); }
    
    /* Raw mode link */
    .raw-link {
        position: fixed;
        bottom: 24px;
        right: 24px;
        background: var(--bg-secondary);
        border: 1px solid var(--border-color);
        padding: 8px 16px;
        border-radius: 8px;
        color: var(--text-secondary);
        font-size: 13px;
        text-decoration: none;
        display: flex;
        align-items: center;
        gap: 6px;
        transition: all 0.2s;
    }
    
    .raw-link:hover {
        background: var(--bg-tertiary);
        color: var(--text-primary);
        text-decoration: none;
    }
    
    /* Responsive */
    @media (max-width: 768px) {
        .nav { padding: 12px 16px; gap: 12px; }
        .nav-links { gap: 8px; }
        .nav-link { padding: 6px 8px; font-size: 13px; }
        .container { padding: 24px 16px; }
        .card-grid { grid-template-columns: 1fr; }
    }
    """
    
    @classmethod
    def render_markdown(cls, content: str) -> str:
        """Convert markdown to HTML with enhanced formatting"""
        html = content
        
        # Escape HTML entities first (but preserve our tags)
        html = html.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
        
        # Convert code blocks with language hints
        def code_block_replacer(match):
            lang = match.group(1) or 'text'
            code = match.group(2).strip()
            # Unescape for code blocks
            code = code.replace('&lt;', '<').replace('&gt;', '>').replace('&amp;', '&')
            return f'<div class="code-block"><button class="copy-btn" onclick="copyCode(this)">Copy</button><pre><code class="language-{lang}">{code}</code></pre></div>'
        
        html = re.sub(r'```(\w+)?\n(.*?)```', code_block_replacer, html, flags=re.DOTALL)
        
        # Convert inline code
        html = re.sub(r'`([^`]+)`', r'<code>\1</code>', html)
        
        # Convert headers with IDs for linking
        def header_replacer(match):
            level = len(match.group(1))
            text = match.group(2)
            slug = re.sub(r'[^\w\s-]', '', text.lower()).strip().replace(' ', '-')
            return f'<h{level} id="{slug}">{text}</h{level}>'
        
        html = re.sub(r'^(#{1,6})\s+(.+)$', header_replacer, html, flags=re.MULTILINE)
        
        # Convert tables
        def table_replacer(match):
            lines = match.group(0).strip().split('\n')
            if len(lines) < 2:
                return match.group(0)
            
            # Header row
            headers = [cell.strip() for cell in lines[0].split('|') if cell.strip()]
            
            # Skip separator row and get data rows
            data_rows = []
            for line in lines[2:]:
                cells = [cell.strip() for cell in line.split('|') if cell.strip()]
                if cells:
                    data_rows.append(cells)
            
            table_html = '<table><thead><tr>'
            for h in headers:
                table_html += f'<th>{h}</th>'
            table_html += '</tr></thead><tbody>'
            
            for row in data_rows:
                table_html += '<tr>'
                for cell in row:
                    # Add method badges
                    if cell.upper() in ['GET', 'POST', 'PUT', 'DELETE', 'PATCH']:
                        cell = f'<span class="badge badge-{cell.lower()}">{cell}</span>'
                    table_html += f'<td>{cell}</td>'
                table_html += '</tr>'
            
            table_html += '</tbody></table>'
            return table_html
        
        html = re.sub(r'(\|.+\|\n)+', table_replacer, html)
        
        # Convert blockquotes
        html = re.sub(r'^&gt;\s*(.+)$', r'<blockquote>\1</blockquote>', html, flags=re.MULTILINE)
        
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
        
        # Convert paragraphs (text blocks separated by blank lines)
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
        
        return html
    
    @classmethod
    def render_page(cls, content: str, title: str, path: str = "", base_url: str = "/documentation") -> str:
        """Render a complete HTML page with navigation"""
        html_content = cls.render_markdown(content)
        
        # Build breadcrumb
        breadcrumb_html = f'<a href="{base_url}">📚 Docs</a>'
        if path:
            parts = path.split('/')
            current_path = ""
            for i, part in enumerate(parts[:-1]):
                current_path += f"/{part}" if current_path else part
                breadcrumb_html += f' <span class="breadcrumb-sep">/</span> <a href="{base_url}/{current_path}">{part}</a>'
            if parts:
                breadcrumb_html += f' <span class="breadcrumb-sep">/</span> <span>{parts[-1]}</span>'
        
        # Determine raw URL
        raw_url = f"{base_url}/{path}?format=raw" if path else f"{base_url}?format=raw"
        
        return f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{title} - API Documentation</title>
    <style>{cls.CSS_STYLES}</style>
</head>
<body>
    <nav class="nav">
        <a href="{base_url}" class="nav-brand">📚 API Docs</a>
        <div class="nav-links">
            <a href="{base_url}" class="nav-link">Home</a>
            <a href="{base_url}/USAGE" class="nav-link">Usage Guides</a>
            <a href="/docs" class="nav-link">OpenAPI</a>
            <a href="/redoc" class="nav-link">ReDoc</a>
        </div>
    </nav>
    
    <div class="container">
        <div class="breadcrumb">{breadcrumb_html}</div>
        {html_content}
    </div>
    
    <a href="{raw_url}" class="raw-link" title="Get raw markdown (for LLM/API consumption)">
        📄 Raw MD
    </a>
    
    <script>
        function copyCode(btn) {{
            const code = btn.parentElement.querySelector('code').innerText;
            navigator.clipboard.writeText(code).then(() => {{
                btn.textContent = 'Copied!';
                setTimeout(() => btn.textContent = 'Copy', 2000);
            }});
        }}
    </script>
</body>
</html>"""
    
    @classmethod
    def render_index(cls, title: str, files: List[DocumentationFile], base_url: str = "/documentation") -> str:
        """Render an index page listing documentation files"""
        file_items = ""
        for f in files:
            icon = "📖" if f.is_readme else "📄"
            file_items += f'''
            <li class="file-item">
                <span class="file-icon">{icon}</span>
                <a href="{base_url}/{f.path}">{f.title}</a>
            </li>'''
        
        return f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{title} - API Documentation</title>
    <style>{cls.CSS_STYLES}</style>
</head>
<body>
    <nav class="nav">
        <a href="{base_url}" class="nav-brand">📚 API Docs</a>
        <div class="nav-links">
            <a href="{base_url}" class="nav-link active">Home</a>
            <a href="{base_url}/USAGE" class="nav-link">Usage Guides</a>
            <a href="/docs" class="nav-link">OpenAPI</a>
            <a href="/redoc" class="nav-link">ReDoc</a>
        </div>
    </nav>
    
    <div class="container">
        <h1>📁 {title}</h1>
        <ul class="file-list">
            {file_items}
        </ul>
    </div>
</body>
</html>"""
    
    @classmethod
    def render_home(cls, usage_files: List[DocumentationFile], base_url: str = "/documentation") -> str:
        """Render the documentation home page"""
        usage_cards = ""
        for f in usage_files:
            usage_cards += f'''
            <div class="card">
                <div class="card-title">
                    <span>📄</span>
                    <a href="{base_url}/USAGE/{f.name}">{f.title}</a>
                </div>
                <div class="card-description">Usage guide and examples</div>
            </div>'''
        
        return f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>API Documentation</title>
    <style>{cls.CSS_STYLES}</style>
</head>
<body>
    <nav class="nav">
        <a href="{base_url}" class="nav-brand">📚 API Docs</a>
        <div class="nav-links">
            <a href="{base_url}" class="nav-link active">Home</a>
            <a href="{base_url}/USAGE" class="nav-link">Usage Guides</a>
            <a href="/docs" class="nav-link">OpenAPI</a>
            <a href="/redoc" class="nav-link">ReDoc</a>
        </div>
    </nav>
    
    <div class="container">
        <h1>📚 API Documentation</h1>
        
        <div class="card-grid">
            <div class="card">
                <div class="card-title">
                    <span>🔧</span>
                    <a href="/docs">OpenAPI / Swagger</a>
                </div>
                <div class="card-description">Interactive API explorer with try-it-out functionality</div>
            </div>
            <div class="card">
                <div class="card-title">
                    <span>📘</span>
                    <a href="/redoc">ReDoc</a>
                </div>
                <div class="card-description">Alternative API documentation with clean layout</div>
            </div>
        </div>
        
        <h2>📖 Usage Guides</h2>
        <div class="card-grid">
            {usage_cards}
        </div>
        
        <div class="toc">
            <div class="toc-title">💡 Quick Access</div>
            <ul>
                <li><a href="{base_url}/USAGE/authentication-usage-cases.md">Authentication - Login, sessions, tokens</a></li>
                <li><a href="{base_url}/USAGE/users-usage-cases.md">Users - Profile, admin operations</a></li>
                <li><a href="{base_url}/USAGE/groups/README.md">Groups - User groups, project groups, flows</a></li>
                <li><a href="{base_url}/USAGE/projects/README.md">Projects - Project management suite</a></li>
                <li><a href="{base_url}/USAGE/permissions-usage-cases.md">Permissions - Roles, permission groups</a></li>
                <li><a href="{base_url}/USAGE/admin-usage-cases.md">Admin - Dashboard, bulk operations</a></li>
            </ul>
        </div>
    </div>
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
            title = "README"
        
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
