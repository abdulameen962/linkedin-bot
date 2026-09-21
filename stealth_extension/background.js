// Stealth DOM Reader Background Service Worker
// Operates exclusively on the active foreground tab
// NEVER uses chrome.debugger (No yellow banner)
// NEVER creates new tabs

const DEFAULT_SERVER_URL = "ws://127.0.0.1:10088/ws";
const RECONCILE_ALARM = "stealth-bridge-reconcile";
const RECONCILE_INTERVAL_MINUTES = 0.5;

class StealthWebSocketClient {
  constructor() {
    this.socket = null;
    this.state = "disconnected";
    this.serverUrl = DEFAULT_SERVER_URL;
    this.connectingTimer = null;
  }

  isConnected() {
    return this.state === "connected";
  }

  start() {
    chrome.alarms.create(RECONCILE_ALARM, { periodInMinutes: RECONCILE_INTERVAL_MINUTES });
    this.reconcile();
  }

  reconcile() {
    if (this.state === "connected" || this.state === "connecting") {
      return;
    }
    this.openSocket(this.serverUrl);
  }

  openSocket(url) {
    this.state = "connecting";
    this.serverUrl = url;
    console.log("[StealthBridge] Connecting to:", url);

    try {
      const ws = new WebSocket(url);
      this.socket = ws;

      this.connectingTimer = setTimeout(() => {
        if (this.socket === ws && this.state === "connecting") {
          console.warn("[StealthBridge] Connect timeout, closing.");
          ws.close();
        }
      }, 8000);

      ws.addEventListener("open", () => {
        if (this.socket !== ws) {
          ws.close();
          return;
        }
        this.state = "connected";
        clearTimeout(this.connectingTimer);
        console.log("[StealthBridge] Connected to Python RPC Server!");
        this.send({
          type: "hello",
          payload: {
            extension: "Stealth DOM Reader",
            version: chrome.runtime.getManifest().version
          }
        });
      });

      ws.addEventListener("message", (event) => {
        try {
          const data = JSON.parse(event.data);
          this.handleMessage(data);
        } catch (err) {
          console.error("[StealthBridge] Failed to parse message:", err);
        }
      });

      ws.addEventListener("close", () => {
        if (this.socket === ws) {
          this.socket = null;
          this.state = "disconnected";
          clearTimeout(this.connectingTimer);
          console.log("[StealthBridge] Disconnected from server.");
        }
      });

      ws.addEventListener("error", (err) => {
        console.warn("[StealthBridge] Socket error:", err);
      });
    } catch (e) {
      this.state = "disconnected";
      console.error("[StealthBridge] Error creating WebSocket:", e);
    }
  }

  send(data) {
    if (this.socket && this.socket.readyState === WebSocket.OPEN) {
      this.socket.send(JSON.stringify(data));
    }
  }

  async handleMessage(msg) {
    switch (msg.type) {
      case "ping":
        this.send({ type: "pong" });
        break;
      case "hello_ack":
        console.log("[StealthBridge] Handshake acknowledged by server.");
        break;
      case "tool_call":
        await this.handleToolCall(msg);
        break;
      default:
        console.log("[StealthBridge] Unknown message type:", msg.type);
    }
  }

  async handleToolCall(msg) {
    const { requestId, payload } = msg;
    const toolName = payload?.name;
    const toolArgs = payload?.args || {};

    try {
      let result;
      if (toolName === "get_dom_structure") {
        result = await executeGetDomStructure(toolArgs);
      } else {
        throw new Error(`Unknown stealth tool: '${toolName}'. Supported: ['get_dom_structure']`);
      }

      this.send({
        type: "tool_result",
        responseToRequestId: requestId,
        payload: { data: result }
      });
    } catch (err) {
      this.send({
        type: "tool_result",
        responseToRequestId: requestId,
        payload: { error: err.message || String(err) }
      });
    }
  }
}

// ==============================================================================
// STEALTH DOM EXTRACTION LOGIC (Strictly Active Tab, No Debugger, Read-Only)
// ==============================================================================

async function getActiveForegroundTab() {
  const tabs = await chrome.tabs.query({ active: true, currentWindow: true });
  if (!tabs || tabs.length === 0) {
    // Fallback: check across any normal window
    const anyActive = await chrome.tabs.query({ active: true });
    if (anyActive && anyActive.length > 0) {
      return anyActive[0];
    }
    throw new Error("No active tab found. Please open a webpage in Chrome.");
  }
  const tab = tabs[0];
  if (!tab.url || tab.url.startsWith("chrome://") || tab.url.startsWith("chrome-extension://") || tab.url.startsWith("edge://")) {
    throw new Error(`Active tab is a protected system page (${tab.url || "blank"}). Please focus on a normal webpage.`);
  }
  return tab;
}

// Injected function executed inside the webpage's DOM to dump the entire DOM structure
function dumpEntireDomStructure() {
  try {
    const root = document.body || document.documentElement;
    if (!root) {
      return {
        title: document.title || "",
        url: window.location.href || "",
        dom: "<html><body>Empty Page</body></html>"
      };
    }

    // Clone to avoid modifying the live page
    const clone = root.cloneNode(true);

    // Strip out non-semantic bloat (scripts, styles, noscript, svg, iframe)
    const bloat = clone.querySelectorAll("script, style, noscript, svg, iframe");
    bloat.forEach(el => el.remove());

    // Replace heavy inline base64 image strings to avoid wasting context
    const dataImages = clone.querySelectorAll("img[src^='data:'], source[srcset^='data:']");
    dataImages.forEach(img => img.setAttribute("src", "[image]"));

    return {
      title: document.title || "",
      url: window.location.href || "",
      dom: clone.outerHTML
    };
  } catch (err) {
    return {
      title: document.title || "",
      url: window.location.href || "",
      dom: (document.body ? document.body.outerHTML : "") || String(err)
    };
  }
}

async function executeGetDomStructure(args) {
  const tab = await getActiveForegroundTab();

  const injectionResults = await chrome.scripting.executeScript({
    target: { tabId: tab.id },
    func: dumpEntireDomStructure
  });

  if (!injectionResults || injectionResults.length === 0 || !injectionResults[0].result) {
    throw new Error("Failed to execute stealth DOM extraction script on active tab.");
  }

  return injectionResults[0].result;
}

// Initialize and start client
const client = new StealthWebSocketClient();
client.start();

chrome.alarms.onAlarm.addListener((alarm) => {
  if (alarm.name === RECONCILE_ALARM) {
    client.reconcile();
  }
});

chrome.runtime.onMessage.addListener((msg, sender, sendResponse) => {
  if (msg.type === "GET_STATUS") {
    sendResponse({
      connected: client.isConnected(),
      serverUrl: client.serverUrl
    });
  }
  return true;
});
