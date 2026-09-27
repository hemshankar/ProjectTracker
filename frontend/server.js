const path = require("path");
const express = require("express");
const { createProxyMiddleware } = require("http-proxy-middleware");

const PORT = process.env.PORT || 3000;
const BACKEND_URL = process.env.BACKEND_URL || "http://backend:8000";

const app = express();

app.use(
  createProxyMiddleware({
    pathFilter: "/api",
    target: BACKEND_URL,
    changeOrigin: true,
  })
);

app.use(express.static(path.join(__dirname, "public")));

app.get("*", (req, res) => {
  res.sendFile(path.join(__dirname, "public", "index.html"));
});

app.listen(PORT, () => {
  console.log(`Manifestation Board frontend listening on ${PORT}, proxying /api -> ${BACKEND_URL}`);
});
