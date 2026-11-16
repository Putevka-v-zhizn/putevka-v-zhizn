FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PYTHONUTF8=1 HOME=/tmp
WORKDIR /app
COPY development_mcp/requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt
COPY development_mcp /app/development_mcp
# Models and dictionaries ship in wheels. Verify offline startup during the build.
RUN python -c "from development_mcp.redaction import RussianNER; n = RussianNER(); assert list(n.entities('Иван Иванов живёт в Томске.'))"
USER 10001:10001
ENTRYPOINT ["python", "-m", "development_mcp"]
