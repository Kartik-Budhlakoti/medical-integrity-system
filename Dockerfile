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

# Unprivileged user. /app/uploads is the only place the app writes (local storage mode).
RUN groupadd --system --gid 1000 appuser \
 && useradd --system --uid 1000 --gid appuser --no-create-home --shell /usr/sbin/nologin appuser \
 && mkdir -p /app/uploads \
 && chown appuser:appuser /app/uploads

COPY . .

USER appuser

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]