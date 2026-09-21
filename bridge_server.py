import asyncio
import json
import logging
import threading
import websockets
from typing import Dict, Any, Optional

logging.basicConfig(level=logging.INFO, format="[BridgeServer] %(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger("BridgeServer")

class ChromeRPCBridge:
    def __init__(self, host: str = "127.0.0.1", port: int = 10086):
        self.host = host
        self.port = port
        self.active_websocket = None
        self.pending_requests: Dict[str, asyncio.Future] = {}
        self.request_counter = 0
        self.server = None
        self.is_connected = False
        self.loop: Optional[asyncio.AbstractEventLoop] = None
        self.thread: Optional[threading.Thread] = None

    async def start(self):
        self.server = await websockets.serve(self._handle_client, self.host, self.port)
        logger.info(f"WebSocket RPC Server running on ws://{self.host}:{self.port}/ws")

    def start_in_background(self):
        """Starts the WebSocket RPC server in a dedicated background thread with its own asyncio loop."""
        if self.thread and self.thread.is_alive():
            return

        def run_loop():
            self.loop = asyncio.new_event_loop()
            asyncio.set_event_loop(self.loop)
            self.loop.run_until_complete(self.start())
            self.loop.run_forever()

        self.thread = threading.Thread(target=run_loop, daemon=True)
        self.thread.start()

    async def _handle_client(self, websocket):
        logger.info("Chrome Extension (Ascentrader WebBridge) connected!")
        self.active_websocket = websocket
        self.is_connected = True

        try:
            async for message in websocket:
                try:
                    data = json.loads(message)
                    await self._handle_message(data)
                except Exception as e:
                    logger.error(f"Error parsing message: {e}")
        except websockets.exceptions.ConnectionClosed:
            logger.warning("Extension connection closed")
        finally:
            self.active_websocket = None
            self.is_connected = False
            logger.info("Extension disconnected.")

    async def _handle_message(self, data: Dict[str, Any]):
        msg_type = data.get("type")
        if msg_type == "hello":
            logger.info(f"Received hello from extension v{data.get('payload', {}).get('extensionVersion')}")
            if self.active_websocket:
                await self.active_websocket.send(json.dumps({"type": "hello_ack"}))
        elif msg_type == "ping":
            if self.active_websocket:
                await self.active_websocket.send(json.dumps({"type": "pong"}))
        elif msg_type == "tool_result":
            req_id = data.get("responseToRequestId")
            if req_id in self.pending_requests:
                future = self.pending_requests.pop(req_id)
                payload = data.get("payload", {})
                if "error" in payload:
                    future.set_exception(RuntimeError(payload["error"]))
                else:
                    future.set_result(payload.get("data"))

    async def call_tool(self, name: str, args: Optional[Dict[str, Any]] = None, timeout: float = 60.0) -> Any:
        if not self.is_connected or not self.active_websocket:
            raise RuntimeError("Ascentrader WebBridge extension is not connected! Please load the extension in Chrome.")

        self.request_counter += 1
        req_id = f"req_{self.request_counter}"
        future = asyncio.get_event_loop().create_future()
        self.pending_requests[req_id] = future

        msg = {
            "type": "tool_call",
            "requestId": req_id,
            "payload": {
                "name": name,
                "args": args or {}
            }
        }
        await self.active_websocket.send(json.dumps(msg))

        try:
            return await asyncio.wait_for(future, timeout=timeout)
        except asyncio.TimeoutError:
            self.pending_requests.pop(req_id, None)
            raise RuntimeError(f"Tool call '{name}' timed out after {timeout} seconds.")

    # High level helper shortcuts
    async def navigate(self, url: str, group_title: str = "Ascentrade", session_id: str = "ascentrader_session", timeout: float = 60.0) -> Dict[str, Any]:
        return await self.call_tool("navigate", {
            "url": url,
            "group_title": group_title,
            "_session": session_id
        }, timeout=timeout)

    async def snapshot(self) -> Dict[str, Any]:
        return await self.call_tool("snapshot", {})

    async def click(self, selector: str) -> Dict[str, Any]:
        return await self.call_tool("click", {"selector": selector})

    async def fill(self, selector: str, value: str) -> Dict[str, Any]:
        return await self.call_tool("fill", {"selector": selector, "value": value})

    async def evaluate(self, code: str) -> Dict[str, Any]:
        return await self.call_tool("evaluate", {"code": code})

    async def send_keys(self, keys: str) -> Dict[str, Any]:
        return await self.call_tool("send_keys", {"keys": keys})

    async def screenshot(self, format: str = "png") -> Dict[str, Any]:
        return await self.call_tool("screenshot", {"format": format})

    async def mouse_click(self, selector: str) -> Dict[str, Any]:
        return await self.call_tool("mouse_click", {"selector": selector})

    async def scroll(self, direction: str = "down", amount: int = 500) -> Dict[str, Any]:
        dy = amount if direction.lower() == "down" else -amount
        code = f"window.scrollBy({{ top: {dy}, behavior: 'smooth' }});"
        return await self.evaluate(code)

# Singleton instance
bridge = ChromeRPCBridge()

if __name__ == "__main__":
    async def main():
        await bridge.start()
        print("Waiting for Chrome extension connection...")
        while True:
            await asyncio.sleep(1)

    asyncio.run(main())
