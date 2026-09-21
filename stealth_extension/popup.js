async function updatePopup() {
  try {
    const status = await chrome.runtime.sendMessage({ type: "GET_STATUS" });
    const dot = document.getElementById("dot");
    const statusText = document.getElementById("statusText");

    if (status && status.connected) {
      dot.className = "indicator connected";
      statusText.textContent = "Connected";
    } else {
      dot.className = "indicator";
      statusText.textContent = "Disconnected";
    }
  } catch (err) {
    console.error(err);
  }

  try {
    const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
    if (tab) {
      document.getElementById("tabTitle").textContent = tab.title || "No Title";
      document.getElementById("tabUrl").textContent = tab.url || "";
    }
  } catch (err) {
    console.error(err);
  }
}

document.addEventListener("DOMContentLoaded", updatePopup);
