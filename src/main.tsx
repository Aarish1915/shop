import React from "react";
import ReactDOM from "react-dom/client";
import ShopkeeperWebApp from "./App";
import "./styles.css";

// Register Service Worker for PWA and WhatsApp Share Target
if ("serviceWorker" in navigator) {
  window.addEventListener("load", () => {
    navigator.serviceWorker.register("/sw.js").catch(() => {});
  });
}

ReactDOM.createRoot(document.getElementById("root") as HTMLElement).render(
  <React.StrictMode>
    <ShopkeeperWebApp />
  </React.StrictMode>
);
