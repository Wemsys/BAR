FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 8501

# Healthcheck sobre el endpoint interno de Streamlit (útil para Coolify/Traefik/Docker).
HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
  CMD python -c "import urllib.request,sys; sys.exit(0) if urllib.request.urlopen('http://localhost:8501/_stcore/health').status==200 else sys.exit(1)"

# Las credenciales se pasan en tiempo de ejecución, nunca se incluyen en la imagen:
#   docker run -p 8501:8501 -e BINANCE_API_KEY=... -e BINANCE_API_SECRET=... binance-export
ENTRYPOINT ["streamlit", "run", "app.py", "--server.port=8501", "--server.address=0.0.0.0"]
