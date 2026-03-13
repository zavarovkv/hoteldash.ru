"""Веб-сервер для embed-дашборда с JWT-токеном."""

from __future__ import annotations

import os
import time
from http.server import HTTPServer, BaseHTTPRequestHandler

import jwt
from dotenv import load_dotenv

load_dotenv()

METABASE_SECRET_KEY = os.getenv("METABASE_SECRET_KEY", "")
METABASE_DASHBOARD_ID = int(os.getenv("METABASE_DASHBOARD_ID", "3"))
METABASE_URL = os.getenv("METABASE_URL", "https://hoteldash.ru/metabase")
PORT = int(os.getenv("WEB_PORT", "8080"))


def generate_token() -> str:
    payload = {
        "resource": {"dashboard": METABASE_DASHBOARD_ID},
        "params": {},
        "exp": round(time.time()) + (60 * 10),  # 10 минут
        "_embedding_params": {},
    }
    return jwt.encode(payload, METABASE_SECRET_KEY, algorithm="HS256")


HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="ru">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>HotelDash — мониторинг цен на отели</title>
    <style>
        * {{ margin: 0; padding: 0; box-sizing: border-box; }}
        body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; }}
        metabase-dashboard {{ display: block; width: 100%; height: 100vh; }}
        /* Hide "Powered by Metabase" badge */
        [class*="PoweredBy"], [class*="powered-by"], a[href*="metabase.com"] {{ display: none !important; }}
    </style>
</head>
<body>

<script defer src="{metabase_url}/app/embed.js"></script>
<script>
    function defineMetabaseConfig(config) {{
        window.metabaseConfig = config;
    }}
</script>

<script>
    defineMetabaseConfig({{
        "theme": {{
            "preset": "light"
        }},
        "isGuest": true,
        "instanceUrl": "{metabase_url}"
    }});
</script>

<metabase-dashboard token="{token}" with-title="true" with-downloads="true"></metabase-dashboard>

<script>
    // Hide "Powered by Metabase" badge everywhere
    (function() {{
        var css = 'a[href*="metabase.com"], [class*="PoweredBy"], [class*="powered-by"], [class*="EmbedFrame-Actionbuttons"] {{ display: none !important; }} iframe {{ height: 100vh !important; }}';

        function injectStyle(root) {{
            if (!root) return;
            var s = document.createElement('style');
            s.textContent = css;
            root.appendChild(s);
        }}

        function hideInNode(node) {{
            // Hide any link to metabase.com
            node.querySelectorAll('a[href*="metabase.com"], a[href*="metabase"], [class*="PoweredBy"], [class*="powered"]').forEach(function(el) {{
                el.style.display = 'none';
            }});
            // Also hide by text content
            node.querySelectorAll('a, span, div, p').forEach(function(el) {{
                if (el.textContent && el.textContent.indexOf('Powered by Metabase') !== -1) {{
                    el.style.display = 'none';
                    if (el.parentElement) el.parentElement.style.display = 'none';
                }}
            }});
        }}

        function tryHide() {{
            // 1. Main document
            hideInNode(document);

            // 2. Shadow DOM of metabase-dashboard
            var mb = document.querySelector('metabase-dashboard');
            if (mb && mb.shadowRoot) {{
                injectStyle(mb.shadowRoot);
                hideInNode(mb.shadowRoot);

                // 3. iframe inside shadow DOM
                var iframes = mb.shadowRoot.querySelectorAll('iframe');
                iframes.forEach(function(iframe) {{
                    try {{
                        var doc = iframe.contentDocument || iframe.contentWindow.document;
                        if (doc) {{
                            injectStyle(doc.head || doc.documentElement);
                            hideInNode(doc);
                        }}
                    }} catch(e) {{}}
                }});

                // Watch for new elements in shadow DOM
                new MutationObserver(function() {{
                    hideInNode(mb.shadowRoot);
                    mb.shadowRoot.querySelectorAll('iframe').forEach(function(iframe) {{
                        try {{
                            var doc = iframe.contentDocument || iframe.contentWindow.document;
                            if (doc) {{ injectStyle(doc.head || doc.documentElement); hideInNode(doc); }}
                        }} catch(e) {{}}
                    }});
                }}).observe(mb.shadowRoot, {{ childList: true, subtree: true }});
            }}
        }}

        // Retry until shadow DOM is ready
        var attempts = 0;
        var timer = setInterval(function() {{
            tryHide();
            attempts++;
            if (attempts > 60) clearInterval(timer);
        }}, 1000);
    }})();
</script>

</body>
</html>"""


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        token = generate_token()
        html = HTML_TEMPLATE.format(
            metabase_url=METABASE_URL,
            token=token,
        )
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        self.wfile.write(html.encode())

    def log_message(self, format, *args):
        pass  # тихий логинг


def main():
    if not METABASE_SECRET_KEY:
        raise RuntimeError("METABASE_SECRET_KEY is required. Check .env file.")
    server = HTTPServer(("0.0.0.0", PORT), Handler)
    print(f"Embed server running on port {PORT}")
    server.serve_forever()


if __name__ == "__main__":
    main()
