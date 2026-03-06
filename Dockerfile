# Sử dụng một base image Python
FROM python:3.9-slim

# Cài đặt curl cho healthcheck
RUN apt-get update && apt-get install -y curl && rm -rf /var/lib/apt/lists/*

# Thiết lập thư mục làm việc
WORKDIR /app

# Sao chép tệp requirements.txt vào thư mục làm việc
COPY requirements.txt .

# Cài đặt các dependencies từ tệp requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

# Sao chép các tệp cần thiết vào thư mục làm việc
COPY . .

# Thiết lập biến môi trường
ENV PROXY_PORT=8999
# ENV PROXY_ALLOWED_IPS=192.168.1.0/24,10.0.0.5
# ENV PROXY_CONFIG=/app/config.json

# Chạy ứng dụng khi container khởi động
CMD ["python", "main.py"]