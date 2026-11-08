FROM python:3.14-slim AS builder

WORKDIR /app

COPY requirements.txt .
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"
RUN pip install --no-cache-dir -r requirements.txt

FROM python:3.14-slim

WORKDIR /app

COPY --from=builder /opt/venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# No package installer in the runtime image: the app never uses pip, and the
# libraries bundled inside pip were what Trivy flagged.
RUN /opt/venv/bin/python -m pip uninstall -y pip \
 && /usr/local/bin/python -m pip uninstall -y pip

# Temporary: Debian has fixed two zlib heap-overflow CVEs (CVE-2026-76844,
# CVE-2026-85091) but the python:3.14-slim image does not have the fix yet.
# Remove this block once the base image ships zlib1g 1:1.3.dfsg+really1.3.1-1+deb13u1 or later.
RUN apt-get update \
 && apt-get install -y --no-install-recommends --only-upgrade zlib1g \
 && rm -rf /var/lib/apt/lists/*

# Unprivileged user. /app/uploads is the only place the app writes (local storage mode).
RUN groupadd --system --gid 1000 appuser \
 && useradd --system --uid 1000 --gid appuser --no-create-home --shell /usr/sbin/nologin appuser \
 && mkdir -p /app/uploads \
 && chown appuser:appuser /app/uploads

COPY . .

USER appuser

EXPOSE 8000

CMD ["sh", "scripts/start.sh"]