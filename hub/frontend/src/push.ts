// @ts-nocheck
// Migrated classic-script file. Types intentionally loose during
// the big-bang JS-to-TS bundle migration. Narrow later, per-file.
/* Orochi Push Notifications -- PWA Web Push client */
/* globals: token, apiUrl */

var pushSupported = "PushManager" in window && "serviceWorker" in navigator;
var pushSubscription = null;
var pushEnabled = localStorage.getItem("orochi_push_enabled") === "true";

/* Convert base64url VAPID key to Uint8Array for subscribe() */
function urlBase64ToUint8Array(base64String) {
  var padding = "=".repeat((4 - (base64String.length % 4)) % 4);
  var base64 = (base64String + padding).replace(/-/g, "+").replace(/_/g, "/");
  var rawData = atob(base64);
  var outputArray = new Uint8Array(rawData.length);
  for (var i = 0; i < rawData.length; i++) {
    outputArray[i] = rawData.charCodeAt(i);
  }
  return outputArray;
}

/* Fetch the VAPID public key from server */
async function fetchVapidKey() {
  try {
    var res = await fetch(apiUrl("/api/push/vapid-key"));
    if (!res.ok) return null;
    var data = await res.json();
    return data.public_key || null;
  } catch (e) {
    console.error("Failed to fetch VAPID key:", e);
    return null;
  }
}

/* Subscribe to push notifications */
async function subscribeToPush() {
  if (!pushSupported) {
    console.warn("Push notifications not supported");
    return false;
  }
  var vapidKey = await fetchVapidKey();
  if (!vapidKey) {
    console.error("No VAPID key -- push not configured");
    return false;
  }
  var permission = await Notification.requestPermission();
  if (permission !== "granted") {
    console.warn("Notification permission denied");
    return false;
  }
  try {
    var registration = await navigator.serviceWorker.ready;
    var subscription = await registration.pushManager.subscribe({
      userVisibleOnly: true,
      applicationServerKey: urlBase64ToUint8Array(vapidKey),
    });
    var subJson = subscription.toJSON();
    var res = await fetch(apiUrl("/api/push/subscribe"), {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        endpoint: subJson.endpoint,
        keys: subJson.keys,
      }),
    });
    if (!res.ok) {
      console.error("Failed to send subscription:", res.status);
      return false;
    }
    pushSubscription = subscription;
    pushEnabled = true;
    localStorage.setItem("orochi_push_enabled", "true");
    updatePushToggleUI();
    return true;
  } catch (e) {
    console.error("Push subscription error:", e);
    return false;
  }
}

/* Unsubscribe from push notifications */
async function unsubscribeFromPush() {
  if (!pushSubscription) {
    var registration = await navigator.serviceWorker.ready;
    pushSubscription = await registration.pushManager.getSubscription();
  }
  if (pushSubscription) {
    var endpoint = pushSubscription.endpoint;
    await pushSubscription.unsubscribe();
    await fetch(apiUrl("/api/push/unsubscribe"), {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ endpoint: endpoint }),
    }).catch(function (e) {
      console.warn("Failed to notify server of unsubscribe:", e);
    });
  }
  pushSubscription = null;
  pushEnabled = false;
  localStorage.setItem("orochi_push_enabled", "false");
  updatePushToggleUI();
}

/* Toggle push notifications on/off */
async function togglePush() {
  if (pushEnabled) {
    await unsubscribeFromPush();
  } else {
    await subscribeToPush();
  }
}

/* Update the push toggle button UI */
function updatePushToggleUI() {
  var btn = document.getElementById("push-toggle");
  if (!btn) return;
  if (!pushSupported) {
    btn.style.display = "none";
    return;
  }
  btn.textContent = pushEnabled ? "🔔 Notifications: ON" : "🔕 Notifications: OFF";
  btn.classList.toggle("push-on", pushEnabled);
  btn.classList.toggle("push-off", !pushEnabled);
  var statusEl = document.getElementById("push-status-msg");
  if (statusEl) {
    statusEl.textContent = pushEnabled
      ? "Subscribed — you'll receive push notifications on this device."
      : "Not subscribed. Click to enable push notifications on this device.";
  }
}

/* Check existing push subscription on load */
async function checkPushState() {
  if (!pushSupported) return;
  try {
    var registration = await navigator.serviceWorker.ready;
    pushSubscription = await registration.pushManager.getSubscription();
    if (pushSubscription) {
      pushEnabled = true;
      localStorage.setItem("orochi_push_enabled", "true");
    } else {
      pushEnabled = false;
      localStorage.setItem("orochi_push_enabled", "false");
    }
  } catch (e) {
    console.warn("Could not check push state:", e);
  }
  updatePushToggleUI();
}

/* Wire the push toggle button and check current subscription state.
 * Called from settings-tab.js wireSettingsForms() after settings content loads. */
function initPushUI() {
  var btn = document.getElementById("push-toggle");
  var statusEl = document.getElementById("push-status-msg");
  if (!pushSupported) {
    if (btn) {
      btn.textContent = "Not supported in this browser";
      btn.disabled = true;
    }
    return;
  }
  if (statusEl) {
    statusEl.textContent = "Checking subscription status…";
  }
  checkPushState().then(function () {
    if (statusEl) {
      statusEl.textContent = pushEnabled
        ? "Subscribed — you'll receive push notifications on this device."
        : "Not subscribed. Click to enable push notifications on this device.";
    }
  });
}
