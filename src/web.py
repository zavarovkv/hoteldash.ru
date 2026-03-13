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
    // Hide "Powered by Metabase" badge inside Shadow DOM
    (function hideBadge() {{
        var el = document.querySelector('metabase-dashboard');
        if (!el || !el.shadowRoot) {{
            setTimeout(hideBadge, 500);
            return;
        }}
        var style = document.createElement('style');
        style.textContent = 'a[href*="metabase.com"], [class*="PoweredBy"], [class*="powered-by"] {{ display: none !important; }}';
        el.shadowRoot.appendChild(style);
        // Re-check in case Metabase re-renders
        setInterval(function() {{
            if (!el.shadowRoot.querySelector('style[data-hide-badge]')) {{
                var s = document.createElement('style');
                s.setAttribute('data-hide-badge', '1');
                s.textContent = style.textContent;
                el.shadowRoot.appendChild(s);
            }}
        }}, 2000);
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
