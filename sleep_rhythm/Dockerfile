# Optional container image (any Docker host). Render users can skip this and use render.yaml.
FROM python:3.13-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PORT=8000
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt && useradd --create-home rhythm
COPY --chown=rhythm:rhythm sleepapp ./sleepapp
COPY --chown=rhythm:rhythm web ./web
COPY --chown=rhythm:rhythm run.py ./run.py
USER rhythm
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=3s --start-period=10s CMD python -c "import os,urllib.request; urllib.request.urlopen('http://127.0.0.1:'+os.environ.get('PORT','8000')+'/healthz',timeout=2)" || exit 1
CMD ["python", "run.py", "--production", "--host", "0.0.0.0", "--no-browser"]
