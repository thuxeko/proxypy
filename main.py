import aiohttp
import asyncio
from aiohttp import web
import json
import logging
from datetime import datetime
import os
import argparse
import urllib.parse
from ipaddress import ip_network, ip_address

# Danh sách IP cho phép (global)
ALLOWED_IPS = []


def load_config(config_path=None):
    """Load cấu hình từ file JSON hoặc env variable"""
    config = {
        "allowed_ips": [],
        "port": 8999
    }
    
    # Lấy đường dẫn config từ env hoặc tham số
    if config_path is None:
        config_path = os.environ.get("PROXY_CONFIG", "config.json")
    
    if os.path.exists(config_path):
        try:
            with open(config_path, "r") as f:
                file_config = json.load(f)
                config.update(file_config)
            print(f"Loaded config from: {config_path}")
        except (json.JSONDecodeError, IOError) as e:
            print(f"Warning: Failed to load config from {config_path}: {e}")
    else:
        print(f"Warning: Config file not found: {config_path}")
    
    # Env variable PROXY_ALLOWED_IPS override config file
    env_ips = os.environ.get("PROXY_ALLOWED_IPS")
    if env_ips:
        config["allowed_ips"] = [ip.strip() for ip in env_ips.split(",") if ip.strip()]
        print(f"Using allowed_ips from PROXY_ALLOWED_IPS env: {config['allowed_ips']}")
    
    # Env variable PORT override config file
    env_port = os.environ.get("PROXY_PORT")
    if env_port:
        try:
            config["port"] = int(env_port)
            print(f"Using port from PROXY_PORT env: {config['port']}")
        except ValueError:
            print(f"Warning: Invalid PROXY_PORT value: {env_port}")
    
    return config


def is_ip_allowed(client_ip):
    """Kiểm tra IP có trong danh sách cho phép không"""
    if not ALLOWED_IPS:  # Nếu không cấu hình IP nào thì cho phép tất cả
        return True
    try:
        client = ip_address(client_ip)
        for allowed in ALLOWED_IPS:
            if "/" in allowed:  # CIDR notation (vd: 192.168.1.0/24)
                if client in ip_network(allowed, strict=False):
                    return True
            else:  # Single IP
                if client == ip_address(allowed):
                    return True
        return False
    except ValueError:
        return False


@web.middleware
async def ip_whitelist_middleware(request, handler):
    """Middleware kiểm tra IP whitelist"""
    client_ip = request.remote
    if not is_ip_allowed(client_ip):
        print(f"Blocked request from IP: {client_ip}")
        return web.Response(
            status=403,
            body=json.dumps({"error": "Forbidden", "message": f"IP {client_ip} not allowed"}),
            content_type="application/json"
        )
    return await handler(request)

# Cấu hình logging
LOG_DIR = "Logs"
os.makedirs(LOG_DIR, exist_ok=True)  # Tạo thư mục Logs nếu chưa tồn tại


def setup_logger():
    date_str = datetime.now().strftime("%Y-%m-%d")
    log_file = os.path.join(LOG_DIR, f"access_{date_str}.log")
    logger = logging.getLogger(f"access_{date_str}")
    logger.setLevel(logging.INFO)
    if not logger.handlers:  # Tránh thêm handler nhiều lần
        handler = logging.FileHandler(log_file)
        handler.setFormatter(logging.Formatter("%(message)s"))
        logger.addHandler(handler)
    return logger


# Target API
TARGET_APIS = {
    "/v1/chat/completions": "https://api.openai.com",
    "/v1beta/models/": "https://generativelanguage.googleapis.com",
    "/v1/messages": "https://api.anthropic.com",
}


async def log_request(request, target, response_status=None, response_body=None):
    logger = setup_logger()
    log_data = {
        "timestamp": datetime.now().isoformat(),
        "method": request.method,
        "url": str(request.rel_url),
        "headers": dict(request.headers),
        "body": await request.text() or "No body",
        "target": target,
        "status": response_status or "Pending",
    }
    if response_body:
        log_data["response_body"] = response_body.decode("utf-8", errors="ignore")[:500]
    logger.info(json.dumps(log_data, indent=2))


# ================== OpenAI Compatible Driver ==================

def detect_provider_from_model(model_name):
    """Detect provider từ model name"""
    model_lower = model_name.lower()
    if model_lower.startswith("gpt-") or model_lower.startswith("o1") or model_lower.startswith("o3"):
        return "openai"
    elif model_lower.startswith("gemini-"):
        return "gemini"
    elif model_lower.startswith("claude-"):
        return "claude"
    return None


def get_api_key_from_request(request):
    """Lấy API key từ Authorization header"""
    auth_header = request.headers.get("Authorization", "")
    if auth_header.startswith("Bearer "):
        return auth_header[7:]  # Bỏ "Bearer "
    return None


def convert_openai_to_gemini(openai_body):
    """Convert OpenAI request format → Gemini format"""
    gemini_body = {}
    
    # Convert messages → contents
    if "messages" in openai_body:
        contents = []
        for msg in openai_body["messages"]:
            role = "user" if msg["role"] == "user" else "model"
            contents.append({
                "role": role,
                "parts": [{"text": msg["content"]}]
            })
        gemini_body["contents"] = contents
    
    # Convert generationConfig
    config = {}
    if "temperature" in openai_body:
        config["temperature"] = openai_body["temperature"]
    if "max_tokens" in openai_body:
        config["maxOutputTokens"] = openai_body["max_tokens"]
    if "top_p" in openai_body:
        config["topP"] = openai_body["top_p"]
    if config:
        gemini_body["generationConfig"] = config
    
    return gemini_body


def convert_openai_to_claude(openai_body):
    """Convert OpenAI request format → Claude format"""
    claude_body = {
        "model": openai_body.get("model"),
        "messages": openai_body.get("messages", []),
        "max_tokens": openai_body.get("max_tokens", 1024)
    }
    
    if "temperature" in openai_body:
        claude_body["temperature"] = openai_body["temperature"]
    if "top_p" in openai_body:
        claude_body["top_p"] = openai_body["top_p"]
    if "stream" in openai_body:
        claude_body["stream"] = openai_body["stream"]
    
    # Convert system message nếu có
    messages = openai_body.get("messages", [])
    system_msg = None
    filtered_messages = []
    for msg in messages:
        if msg.get("role") == "system":
            system_msg = msg.get("content")
        else:
            filtered_messages.append(msg)
    
    if system_msg:
        claude_body["system"] = system_msg
        claude_body["messages"] = filtered_messages
    
    return claude_body


def convert_gemini_to_openai(gemini_response, model):
    """Convert Gemini response → OpenAI format"""
    try:
        data = json.loads(gemini_response)
    except:
        return gemini_response
    
    # Extract text from Gemini response
    content = ""
    if "candidates" in data and len(data["candidates"]) > 0:
        candidate = data["candidates"][0]
        if "content" in candidate and "parts" in candidate["content"]:
            for part in candidate["content"]["parts"]:
                if "text" in part:
                    content += part["text"]
    
    openai_response = {
        "id": f"chatcmpl-{datetime.now().strftime('%Y%m%d%H%M%S')}",
        "object": "chat.completion",
        "created": int(datetime.now().timestamp()),
        "model": model,
        "choices": [{
            "index": 0,
            "message": {
                "role": "assistant",
                "content": content
            },
            "finish_reason": "stop"
        }],
        "usage": {
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "total_tokens": 0
        }
    }
    
    return json.dumps(openai_response)


def convert_claude_to_openai(claude_response, model):
    """Convert Claude response → OpenAI format"""
    try:
        data = json.loads(claude_response)
    except:
        return claude_response
    
    # Extract content
    content = ""
    if "content" in data and len(data["content"]) > 0:
        for item in data["content"]:
            if item.get("type") == "text":
                content += item.get("text", "")
    
    openai_response = {
        "id": data.get("id", f"chatcmpl-{datetime.now().strftime('%Y%m%d%H%M%S')}"),
        "object": "chat.completion",
        "created": int(datetime.now().timestamp()),
        "model": model,
        "choices": [{
            "index": 0,
            "message": {
                "role": "assistant",
                "content": content
            },
            "finish_reason": data.get("stop_reason", "stop")
        }],
        "usage": data.get("usage", {
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "total_tokens": 0
        })
    }
    
    return json.dumps(openai_response)


async def openai_compatible_handler(request):
    """Handler cho OpenAI-compatible endpoint /v1/chat/completions
    
    Proxy server chỉ là trạm trung chuyển (bypass region block).
    Ngườ dùng phải tự truyền API key của họ trong Authorization header.
    """
    try:
        body = await request.json()
        model = body.get("model")
        
        if not model:
            return web.Response(
                status=400,
                body=json.dumps({"error": "Missing 'model' in request"}),
                content_type="application/json"
            )
        
        provider = detect_provider_from_model(model)
        
        if not provider:
            return web.Response(
                status=400,
                body=json.dumps({"error": f"Unknown model: {model}"}),
                content_type="application/json"
            )
        
        # Lấy API key từ Authorization header
        api_key = get_api_key_from_request(request)
        if not api_key:
            return web.Response(
                status=401,
                body=json.dumps({"error": "Missing Authorization header", "message": "Please provide 'Authorization: Bearer YOUR_API_KEY'"}),
                content_type="application/json"
            )
        
        is_stream = body.get("stream", False)
        
        async with aiohttp.ClientSession() as session:
            if provider == "openai":
                # Forward trực tiếp đến OpenAI với key của ngườ dùng
                headers = {
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json"
                }
                
                async with session.post(
                    "https://api.openai.com/v1/chat/completions",
                    headers=headers,
                    json=body,
                    timeout=aiohttp.ClientTimeout(total=120)
                ) as response:
                    if is_stream:
                        resp = web.StreamResponse(
                            status=response.status,
                            headers={"Content-Type": "text/event-stream"}
                        )
                        await resp.prepare(request)
                        async for chunk in response.content:
                            await resp.write(chunk)
                        await resp.write_eof()
                        return resp
                    else:
                        response_body = await response.read()
                        return web.Response(
                            body=response_body,
                            status=response.status,
                            content_type="application/json"
                        )
            
            elif provider == "gemini":
                gemini_body = convert_openai_to_gemini(body)
                model_name = model.replace("gemini-", "gemini-")
                
                endpoint = "streamGenerateContent" if is_stream else "generateContent"
                url = f"https://generativelanguage.googleapis.com/v1beta/models/{model_name}:{endpoint}?key={api_key}&alt=sse"
                
                async with session.post(
                    url,
                    headers={"Content-Type": "application/json"},
                    json=gemini_body,
                    timeout=aiohttp.ClientTimeout(total=120)
                ) as response:
                    if is_stream:
                        resp = web.StreamResponse(
                            status=response.status,
                            headers={"Content-Type": "text/event-stream"}
                        )
                        await resp.prepare(request)
                        
                        async for line in response.content:
                            line_str = line.decode('utf-8').strip()
                            if line_str.startswith('data: '):
                                try:
                                    data = json.loads(line_str[6:])
                                    if "candidates" in data and len(data["candidates"]) > 0:
                                        candidate = data["candidates"][0]
                                        if "content" in candidate and "parts" in candidate["content"]:
                                            for part in candidate["content"]["parts"]:
                                                if "text" in part:
                                                    openai_chunk = {
                                                        "id": f"chatcmpl-{datetime.now().strftime('%Y%m%d%H%M%S')}",
                                                        "object": "chat.completion.chunk",
                                                        "created": int(datetime.now().timestamp()),
                                                        "model": model,
                                                        "choices": [{
                                                            "index": 0,
                                                            "delta": {"content": part["text"]},
                                                            "finish_reason": None
                                                        }]
                                                    }
                                                    chunk_line = f"data: {json.dumps(openai_chunk)}\n\n"
                                                    await resp.write(chunk_line.encode('utf-8'))
                                except:
                                    pass
                        await resp.write(b"data: [DONE]\n\n")
                        await resp.write_eof()
                        return resp
                    else:
                        gemini_response = await response.read()
                        
                        if response.status != 200:
                            return web.Response(
                                status=response.status,
                                body=gemini_response,
                                content_type="application/json"
                            )
                        
                        openai_response = convert_gemini_to_openai(gemini_response, model)
                        return web.Response(
                            body=openai_response,
                            status=200,
                            content_type="application/json"
                        )
            
            elif provider == "claude":
                claude_body = convert_openai_to_claude(body)
                
                headers = {
                    "x-api-key": api_key,
                    "Content-Type": "application/json",
                    "anthropic-version": "2023-06-01"
                }
                
                async with session.post(
                    "https://api.anthropic.com/v1/messages",
                    headers=headers,
                    json=claude_body,
                    timeout=aiohttp.ClientTimeout(total=120)
                ) as response:
                    if is_stream:
                        resp = web.StreamResponse(
                            status=response.status,
                            headers={"Content-Type": "text/event-stream"}
                        )
                        await resp.prepare(request)
                        
                        async for line in response.content:
                            line_str = line.decode('utf-8').strip()
                            if line_str.startswith('data: '):
                                try:
                                    data = json.loads(line_str[6:])
                                    event_type = data.get("type")
                                    
                                    if event_type == "content_block_delta":
                                        delta = data.get("delta", {})
                                        if delta.get("type") == "text_delta":
                                            openai_chunk = {
                                                "id": f"chatcmpl-{datetime.now().strftime('%Y%m%d%H%M%S')}",
                                                "object": "chat.completion.chunk",
                                                "created": int(datetime.now().timestamp()),
                                                "model": model,
                                                "choices": [{
                                                    "index": 0,
                                                    "delta": {"content": delta.get("text", "")},
                                                    "finish_reason": None
                                                }]
                                            }
                                            chunk_line = f"data: {json.dumps(openai_chunk)}\n\n"
                                            await resp.write(chunk_line.encode('utf-8'))
                                    elif event_type == "message_stop":
                                        openai_chunk = {
                                            "id": f"chatcmpl-{datetime.now().strftime('%Y%m%d%H%M%S')}",
                                            "object": "chat.completion.chunk",
                                            "created": int(datetime.now().timestamp()),
                                            "model": model,
                                            "choices": [{
                                                "index": 0,
                                                "delta": {},
                                                "finish_reason": "stop"
                                            }]
                                        }
                                        chunk_line = f"data: {json.dumps(openai_chunk)}\n\n"
                                        await resp.write(chunk_line.encode('utf-8'))
                                except:
                                    pass
                        await resp.write(b"data: [DONE]\n\n")
                        await resp.write_eof()
                        return resp
                    else:
                        claude_response = await response.read()
                        
                        if response.status != 200:
                            return web.Response(
                                status=response.status,
                                body=claude_response,
                                content_type="application/json"
                            )
                        
                        openai_response = convert_claude_to_openai(claude_response, model)
                        return web.Response(
                            body=openai_response,
                            status=200,
                            content_type="application/json"
                        )
    
    except Exception as e:
        print(f"OpenAI Compatible Error: {str(e)}")
        return web.Response(
            status=500,
            body=json.dumps({"error": "Internal Server Error", "message": str(e)}),
            content_type="application/json"
        )


async def proxy_handler(request):
    # Xác định target
    path = str(request.rel_url)
    target = None

    for prefix, api_target in TARGET_APIS.items():
        if path.startswith(prefix):
            target = api_target
            break

    if target is None:
        error_msg = f"No target found for path: {path}"
        print(error_msg)
        await log_request(request, "None", 500, error_msg.encode())
        return web.Response(
            status=500,
            body=json.dumps({"error": "Internal Server Error", "message": error_msg}),
        )

    # Chuẩn bị header và URL
    headers = {k: v for k, v in request.headers.items()}
    parsed_url = urllib.parse.urlparse(target)
    headers["Host"] = parsed_url.netloc
    body = await request.read()

    target_url = f"{target}{path}"
    print(f"Proxying request to: {target_url}")

    async with aiohttp.ClientSession() as session:
        try:
            async with session.request(
                method=request.method,
                url=target_url,
                headers=headers,
                data=body,
                timeout=aiohttp.ClientTimeout(total=30),
            ) as response:
                # Kiểm tra streaming từ OpenAI
                is_stream = "stream" in (await request.text()).lower()

                if is_stream:
                    resp = web.StreamResponse(
                        status=response.status,
                        headers={
                            "Content-Type": response.headers.get(
                                "Content-Type", "application/json"
                            ),
                            "Transfer-Encoding": "chunked",
                        },
                    )
                    await resp.prepare(request)
                    async for chunk in response.content:
                        await resp.write(chunk)
                    await resp.write_eof()
                    # Log chỉ khi không phải 200
                    if response.status != 200:
                        await log_request(request, target, response.status, chunk)
                    return resp
                else:
                    response_body = await response.read()
                    print(
                        f"Received response from: {target_url} - Status: {response.status}"
                    )
                    # Log chỉ khi không phải 200
                    if response.status != 200:
                        await log_request(
                            request, target, response.status, response_body
                        )

                    headers_out = dict(response.headers)
                    headers_out.pop("Content-Encoding", None)
                    headers_out.pop("Transfer-Encoding", None)
                    headers_out["Content-Length"] = str(len(response_body))
                    return web.Response(
                        body=response_body, status=response.status, headers=headers_out
                    )
        except Exception as e:
            error_msg = f"Proxy Error: {str(e)}"
            print(error_msg)
            await log_request(request, target, 502, error_msg.encode())
            return web.Response(
                status=502, body=json.dumps({"error": "Bad Gateway", "message": str(e)})
            )


# Khởi động server
def start_server(port, allowed_ips=None):
    global ALLOWED_IPS
    if allowed_ips:
        ALLOWED_IPS = allowed_ips
        print(f"Allowed IPs: {ALLOWED_IPS}")
    else:
        print("Warning: No IP whitelist configured. Allowing all IPs.")

    async def health_handler(request):
        return web.Response(
            status=200,
            body=json.dumps({"status": "ok"}),
            content_type="application/json"
        )

    app = web.Application(middlewares=[ip_whitelist_middleware])
    app.router.add_get("/health", health_handler)
    # OpenAI-compatible endpoint (đặt trước catch-all route)
    app.router.add_post("/v1/chat/completions", openai_compatible_handler)
    # Legacy proxy handler
    app.router.add_route("*", "/{path:.*}", proxy_handler)

    print(f"Starting reverse proxy on port {port}...")
    print("Legacy Targets:", TARGET_APIS)
    print("OpenAI-compatible endpoint: /v1/chat/completions")
    web.run_app(app, host="0.0.0.0", port=port)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Reverse Proxy Server")
    parser.add_argument(
        "--config",
        type=str,
        default=None,
        help="Path to config JSON file (default: PROXY_CONFIG env or config.json)"
    )
    parser.add_argument(
        "--port",
        type=int,
        default=None,
        help="Port to run the server on (override config file)"
    )
    parser.add_argument(
        "--allow-ip",
        type=str,
        action="append",
        help="Allowed IP address or CIDR, can be specified multiple times (override config file)"
    )
    args = parser.parse_args()

    # Load config từ file
    config = load_config(args.config)
    
    # Command line args override config file
    port = args.port if args.port is not None else config["port"]
    allowed_ips = args.allow_ip if args.allow_ip is not None else config["allowed_ips"]
    
    start_server(port, allowed_ips)
