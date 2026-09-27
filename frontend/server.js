const path = require("path");
const express = require("express");
const { createProxyMiddleware } = require("http-proxy-middleware");

const PORT = process.env.PORT || 3000;
const BACKEND_URL = process.env.BACKEND_URL || "http://backend:8000";

const app = express();

const apiProxy = createProxyMiddleware({
  pathFilter: "/api",
  target: BACKEND_URL,
  changeOrigin: true,
  ws: true,
});

app.use(apiProxy);

app.use(express.static(path.join(__dirname, "public")));

app.get("*", (req, res) => {
  res.sendFile(path.join(__dirname, "public", "index.html"));
});

const server = app.listen(PORT, () => {
  console.log(`Manifestation Board frontend listening on ${PORT}, proxying /api -> ${BACKEND_URL}`);
});
// The board-events WebSocket handshake arrives as an HTTP Upgrade request,
// which Express's own request handling never sees — only the underlying
// http.Server's "upgrade" event does, so it has to be wired up explicitly.
server.on("upgrade", apiProxy.upgrade);
