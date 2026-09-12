FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 8501

# Las credenciales se pasan en tiempo de ejecución, nunca se incluyen en la imagen:
#   docker run -p 8501:8501 -e BINANCE_API_KEY=... -e BINANCE_API_SECRET=... binance-export
ENTRYPOINT ["streamlit", "run", "app.py", "--server.port=8501", "--server.address=0.0.0.0"]
