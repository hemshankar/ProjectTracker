import os

MONGO_URI = os.environ.get("MONGO_URI", "mongodb://mongo:27017")
MONGO_DB_NAME = os.environ.get("MONGO_DB_NAME", "scatterboard")
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
ANTHROPIC_MODEL = os.environ.get("ANTHROPIC_MODEL", "claude-sonnet-5")

HUES = ["blue", "sage", "clay", "mauve", "ochre", "slate"]

CANVAS_W = 2600
CANVAS_H = 1600
MIN_W = 220
MIN_H = 180
