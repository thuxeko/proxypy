# Reverse Proxy Server - Hướng dẫn sử dụng

Proxy server hỗ trợ 3 providers: OpenAI, Google Gemini và Anthropic Claude.

> **⚠️ LƯU Ý QUAN TRỌNG:** Đây là **BYPASS PROXY** - chỉ là trạm trung chuyển để vượt qua region block. **Server KHÔNG lưu API key**. Người dùng phải tự truyền API key của họ trong mỗi request.

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

---

## OpenAI-Compatible Endpoint (Khuyên dùng)

Endpoint `/v1/chat/completions` hỗ trợ **OpenAI format** cho cả 3 providers. Proxy tự động detect provider từ tên model và convert request/response.

### Cách sử dụng

```bash
curl http://localhost:8999/v1/chat/completions \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer YOUR_API_KEY" \
  -d '{
    "model": "gemini-2.0-flash",
    "messages": [{"role": "user", "content": "Hello"}],
    "temperature": 0.7,
    "max_tokens": 1000
  }'
```

### Mapping Model → Provider

| Model Prefix | Provider | Ví dụ |
|--------------|----------|-------|
| `gpt-*` hoặc `o1*` hoặc `o3*` | OpenAI | `gpt-4o`, `o1-mini` |
| `gemini-*` | Google Gemini | `gemini-2.0-flash` |
| `claude-*` | Anthropic Claude | `claude-3-sonnet-20240229` |

### Ví dụ cho từng Provider

**Gemini (dùng Gemini API key):**
```bash
curl http://localhost:8999/v1/chat/completions \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer YOUR_GEMINI_API_KEY" \
  -d '{"model": "gemini-2.0-flash", "messages": [{"role": "user", "content": "Hello"}]}'
```

**Claude (dùng Claude API key):**
```bash
curl http://localhost:8999/v1/chat/completions \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer YOUR_CLAUDE_API_KEY" \
  -d '{"model": "claude-3-sonnet-20240229", "messages": [{"role": "user", "content": "Hello"}]}'
```

**OpenAI (dùng OpenAI API key):**
```bash
curl http://localhost:8999/v1/chat/completions \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer YOUR_OPENAI_API_KEY" \
  -d '{"model": "gpt-4o", "messages": [{"role": "user", "content": "Hello"}]}'
```

### Cách Proxy xử lý API Key

| Provider | Cách proxy gọi API |
|----------|-------------------|
| **OpenAI** | Dùng header `Authorization: Bearer <key>` |
| **Gemini** | Append `?key=<key>` vào URL |
| **Claude** | Dùng header `x-api-key: <key>` |

### Streaming Support

Tất cả 3 providers đều hỗ trợ streaming với format OpenAI:

```bash
curl http://localhost:8999/v1/chat/completions \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer YOUR_API_KEY" \
  -d '{
    "model": "gemini-2.0-flash",
    "messages": [{"role": "user", "content": "Hello"}],
    "stream": true
  }'
```

Response streaming format (SSE):
```
data: {"id":"chatcmpl-...","object":"chat.completion.chunk","choices":[{"delta":{"content":"Hello"}}]}

data: {"id":"chatcmpl-...","object":"chat.completion.chunk","choices":[{"delta":{"content":"!"}}]}

data: [DONE]
```

| Provider | Stream Endpoint | Cách xử lý |
|----------|-----------------|------------|
| OpenAI | `/v1/chat/completions` | Forward trực tiếp |
| Gemini | `:streamGenerateContent?alt=sse` | Convert SSE → OpenAI format |
| Claude | `/v1/messages` với `stream: true` | Convert SSE → OpenAI format |

---

## Cách gọi API Native (Legacy)

Nếu muốn gọi trực tiếp API native của từng provider:

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

---

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

---

## Docker

### Build

```bash
docker build -t proxy-server .
```

### Run

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
      - ./Logs:/app/Logs
    environment:
      - PROXY_PORT=8999
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
