import asyncio
import json
import logging
import threading
import websockets
from typing import Dict, Any, Optional

logging.basicConfig(level=logging.INFO, format="[StealthBridge] %(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger("StealthBridge")

class StealthChromeRPCBridge:
    def __init__(self, host: str = "127.0.0.1", port: int = 10088):
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
        logger.info(f"Stealth WebSocket RPC Server running on ws://{self.host}:{self.port}/ws")

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

    def stop(self):
        """Stops the WebSocket server and loop."""
        if self.loop:
            if self.server:
                self.loop.call_soon_threadsafe(self.server.close)
            self.loop.call_soon_threadsafe(self.loop.stop)


    async def _handle_client(self, websocket):
        logger.info("Stealth Chrome Extension connected!")
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
            logger.warning("Stealth Extension connection closed")
        finally:
            self.active_websocket = None
            self.is_connected = False
            logger.info("Stealth Extension disconnected.")

    async def _handle_message(self, data: Dict[str, Any]):
        msg_type = data.get("type")
        if msg_type == "hello":
            logger.info(f"Received hello from Stealth Extension: {data.get('payload', {})}")
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

    async def call_tool(self, name: str, args: Optional[Dict[str, Any]] = None, timeout: float = 30.0) -> Any:
        if not self.is_connected or not self.active_websocket:
            raise RuntimeError(
                "Stealth DOM Extension is not connected! "
                "Please load 'stealth_extension' in Chrome (chrome://extensions) and ensure it is enabled."
            )

        self.request_counter += 1
        req_id = f"req_{self.request_counter}"
        future = self.loop.create_future() if self.loop else asyncio.get_event_loop().create_future()
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

    async def query_dom_structure(self, timeout: float = 30.0) -> Dict[str, Any]:
        """Queries the active foreground tab's DOM structure via the stealth extension."""
        return await self.call_tool("get_dom_structure", {}, timeout=timeout)

# Singleton instance
stealth_bridge = StealthChromeRPCBridge()

if __name__ == "__main__":
    async def main():
        await stealth_bridge.start()
        print("Stealth Bridge running on ws://127.0.0.1:10088/ws")
        print("Waiting for Stealth Chrome Extension connection...")
        while True:
            await asyncio.sleep(1)

    asyncio.run(main())
