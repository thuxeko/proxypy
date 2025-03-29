# Sử dụng một base image Python
FROM python:3.9-slim

# Thiết lập thư mục làm việc
WORKDIR /app

# Sao chép tệp requirements.txt vào thư mục làm việc
COPY requirements.txt .

# Cài đặt các dependencies từ tệp requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

# Sao chép các tệp cần thiết vào thư mục làm việc
COPY . .

# Thiết lập biến môi trường
ENV PORT=8999
ENV GEMINI_API_KEY=xxx

# Chạy ứng dụng khi container khởi động
CMD ["sh", "-c", "python main.py --port $PORT --gemini-api-key $GEMINI_API_KEY"]