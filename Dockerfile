FROM python:3.12-slim
WORKDIR /srv
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
COPY requirements-app.txt .
RUN pip install --no-cache-dir -r requirements-app.txt
COPY app ./app
COPY start.sh .
RUN sed -i "s/$//" start.sh && chmod +x start.sh
# ROLE=web (default) or ROLE=worker — same image, two Railway services.
CMD ["./start.sh"]
