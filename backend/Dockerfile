FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app

EXPOSE 8000


# --timeout-graceful-shutdown bounds how long a reload (or a real restart)
# waits for in-flight requests before forcing them closed. Without it, a
# still-open SSE stream (a board's live status feed — see
# `routers/boards.py`'s `board_events`) is a legitimately active connection
# for as long as the browser tab stays open, and --reload's default
# graceful shutdown will wait for it *indefinitely* rather than a bounded
# time — every code edit during active use would otherwise hang the server.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--reload", "--timeout-graceful-shutdown", "5"]
