import aiohttp
import asyncio
from aiohttp import web
import json
import logging
from datetime import datetime
import os

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
}
GEMINI_API_KEY = "xxx"  # Thay bằng key thật


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


async def proxy_handler(request):
    # Xác định target
    path = str(request.rel_url)
    target = None
    is_gemini = False

    for prefix, api_target in TARGET_APIS.items():
        if path.startswith(prefix):
            target = api_target
            if prefix == "/v1beta/models/":
                is_gemini = True
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
    headers["Host"] = (
        "api.openai.com" if not is_gemini else "generativelanguage.googleapis.com"
    )
    body = await request.read()

    target_url = (
        f"{target}{path}" if not is_gemini else f"{target}{path}&key={GEMINI_API_KEY}"
    )
    print(f"Proxying request to: {target_url}")

    # Log request (chỉ khi cần thiết, sẽ kiểm tra sau)
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
                is_stream = not is_gemini and "stream" in (await request.text()).lower()

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
app = web.Application()
app.router.add_route("*", "/{path:.*}", proxy_handler)

if __name__ == "__main__":
    print("Starting reverse proxy on port 8999...")
    print("Targets:", TARGET_APIS)
    web.run_app(app, host="0.0.0.0", port=8999)
