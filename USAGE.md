# Reverse Proxy Server - Hướng dẫn sử dụng

Proxy server hỗ trợ 3 providers: OpenAI, Google Gemini và Anthropic Claude.

## Cấu hình

### 1. File `config.json` (khuyên dùng cho Docker)

Tạo file `config.json`:

```json
{
  "port": 8999,
  "allowed_ips": [
    "192.168.1.0/24",
    "10.0.0.5",
    "127.0.0.1"
  ]
}
```

Khởi động server:
```bash
python main.py
# hoặc chỉ định config khác
python main.py --config /path/to/config.json
```

### 2. Environment Variables

| Variable | Mô tả | Ví dụ |
|----------|-------|-------|
| `PROXY_CONFIG` | Đường dẫn file config | `/app/config.json` |
| `PROXY_PORT` | Port server | `8999` |
| `PROXY_ALLOWED_IPS` | Danh sách IP, phân cách bằng dấu phẩy | `192.168.1.0/24,10.0.0.5` |

```bash
export PROXY_ALLOWED_IPS="192.168.1.0/24,127.0.0.1"
export PROXY_PORT=8999
python main.py
```

### 3. Command Line Arguments

```bash
python main.py --port 8999 --allow-ip 192.168.1.100 --allow-ip 192.168.1.0/24
```

### Thứ tự ưu tiên cấu hình (cao → thấp)

1. **Command line arguments** (`--port`, `--allow-ip`)
2. **Environment variables** (`PROXY_PORT`, `PROXY_ALLOWED_IPS`)
3. **Config file** (`config.json` hoặc `PROXY_CONFIG`)
4. **Giá trị mặc định** (port: 8999, allowed_ips: [] cho phép tất cả)

> **Lưu ý bảo mật:** Nếu không cấu hình `allowed_ips`, server sẽ chấp nhận request từ tất cả IP. **KHÔNG NÊN** khi deploy public!

## Cách gọi API cho từng Provider

### 1. OpenAI API

**Endpoint:** `http://localhost:8999/v1/chat/completions`

```bash
curl http://localhost:8999/v1/chat/completions \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer YOUR_OPENAI_API_KEY" \
  -d '{
    "model": "gpt-4o",
    "messages": [{"role": "user", "content": "Hello"}]
  }'
```

**Lưu ý:** Proxy sẽ forward header `Authorization` nguyên bản đến OpenAI.

### 2. Google Gemini API

**Endpoint:** `http://localhost:8999/v1beta/models/{model_name}:{method}?key=YOUR_GEMINI_KEY`

```bash
curl "http://localhost:8999/v1beta/models/gemini-2.0-flash:generateContent?key=YOUR_GEMINI_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "contents": [{"parts": [{"text": "Hello"}]}]
  }'
```

**Lưu ý:** 
- **BẮT BUỘC** thêm `?key=YOUR_GEMINI_API_KEY` vào URL
- Có thể dùng `:generateContent` hoặc `:streamGenerateContent` cho streaming

### 3. Anthropic Claude API

**Endpoint:** `http://localhost:8999/v1/messages`

```bash
curl http://localhost:8999/v1/messages \
  -H "Content-Type: application/json" \
  -H "x-api-key: YOUR_CLAUDE_API_KEY" \
  -H "anthropic-version: 2023-06-01" \
  -d '{
    "model": "claude-3-sonnet-20240229",
    "max_tokens": 1024,
    "messages": [{"role": "user", "content": "Hello"}]
  }'
```

**Lưu ý:** Proxy sẽ forward headers nguyên bản đến Anthropic.

## Tóm tắt Routing

| Provider | Path trên Proxy | Forward đến |
|----------|-----------------|-------------|
| OpenAI | `/v1/chat/completions` | `https://api.openai.com/v1/chat/completions` |
| Gemini | `/v1beta/models/...` | `https://generativelanguage.googleapis.com/v1beta/models/...` |
| Claude | `/v1/messages` | `https://api.anthropic.com/v1/messages` |

## Xác thực

| Provider | Cách truyền key | Ví dụ |
|----------|-----------------|-------|
| OpenAI | Header `Authorization: Bearer xxx` | `-H "Authorization: Bearer sk-..."` |
| Gemini | Query param `?key=xxx` | `.../v1beta/models/...?key=AIza...` |
| Claude | Header `x-api-key: xxx` | `-H "x-api-key: sk-ant-..."` |

## Streaming

OpenAI streaming được hỗ trợ tự động. Thêm `"stream": true` vào body:

```bash
curl http://localhost:8999/v1/chat/completions \
  -H "Authorization: Bearer YOUR_KEY" \
  -H "Content-Type: application/json" \
  -d '{"model": "gpt-4o", "messages": [...], "stream": true}'
```

## Log

Các request với status != 200 sẽ được log vào thư mục `Logs/` theo ngày (định dạng JSON).

## Docker

### Build

```bash
docker build -t proxy-server .
```

### Run với config file

```bash
# Mount config.json vào container
docker run -d \
  -p 8999:8999 \
  -v $(pwd)/config.json:/app/config.json \
  --name proxy-server \
  proxy-server
```

### Run với environment variables

```bash
docker run -d \
  -p 8999:8999 \
  -e PROXY_PORT=8999 \
  -e PROXY_ALLOWED_IPS="192.168.1.0/24,10.0.0.5" \
  --name proxy-server \
  proxy-server
```

### Docker Compose

```yaml
version: '3.8'

services:
  proxy:
    build: .
    ports:
      - "8999:8999"
    volumes:
      - ./config.json:/app/config.json
      - ./Logs:/app/Logs
    environment:
      # Optional: override config file
      - PROXY_ALLOWED_IPS=192.168.1.0/24,127.0.0.1
    restart: unless-stopped
```

Chạy:
```bash
docker-compose up -d
```

### Cập nhật IP whitelist (không rebuild)

**Cách 1: Sửa config.json và restart container**
```bash
# Sửa file config.json trên host
vi config.json

# Restart container
docker restart proxy-server
```

**Cách 2: Dùng env variable và recreate**
```bash
# Stop và remove container hiện tại
docker stop proxy-server
docker rm proxy-server

# Run lại với IP mới
docker run -d \
  -p 8999:8999 \
  -e PROXY_ALLOWED_IPS="NEW_IP1,NEW_IP2" \
  --name proxy-server \
  proxy-server
```
