#!/bin/sh
set -e

alembic upgrade head

# uvicorn only trusts X-Forwarded-For from the proxies listed here. The default
# is 127.0.0.1, so every request looked like it came from Render's internal IP.
# 10.0.0.0/8 covers Render's internal addresses. The other two lists are
# Cloudflare's ranges (cloudflare.com/ips, copied 2026-11-04). Update them if
# Cloudflare changes them.
# Passing a list replaces that default, so 127.0.0.1 has to be listed again:
# on Render the requests reach the app from it.
RENDER_INTERNAL="127.0.0.1,10.0.0.0/8"
CLOUDFLARE_V4="173.245.48.0/20,103.21.244.0/22,103.22.200.0/22,103.31.4.0/22,141.101.64.0/18,108.162.192.0/18,190.93.240.0/20,188.114.96.0/20,197.234.240.0/22,198.41.128.0/17,162.158.0.0/15,104.16.0.0/13,104.24.0.0/14,172.64.0.0/13,131.0.72.0/22"
CLOUDFLARE_V6="2400:cb00::/32,2606:4700::/32,2803:f800::/32,2405:b500::/32,2405:8100::/32,2a06:98c0::/29,2c0f:f248::/32"

exec uvicorn app.main:app --host 0.0.0.0 --port 8000 --forwarded-allow-ips "$RENDER_INTERNAL,$CLOUDFLARE_V4,$CLOUDFLARE_V6"
