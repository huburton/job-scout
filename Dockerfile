FROM python:3.12-slim
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY scout ./scout
COPY profile.example.md .
ENV SCOUT_BIND=0.0.0.0 SCOUT_DATA=/data SCOUT_OUT_DIR=/out SCOUT_PROFILE=/app/profile.md
EXPOSE 8096
CMD ["python", "-m", "scout", "serve"]
