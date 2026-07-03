# ── Shared constants (must match on server and client) ──────────────────────
CELL   = 20          # px per grid cell
COLS   = 30           # grid columns
ROWS   = 25           # grid rows
WIDTH  = CELL * COLS
HEIGHT = CELL * ROWS
SPEED  = 0.12         # seconds between ticks (server tick rate)

BG           = "#FFFFFF"
FOOD_COLOR   = "#FFD700"
GRID_COLOR   = "#E0E0E0"
TEXT_COLOR   = "#000000"
OVERLAY_COLOR = "#333333"

# Two distinct color pairs, one per player
PLAYER_COLORS = {
    1: {"head": "#FF1493", "body": "#FF69B4", "bow": "#FF2D95", "knot": "#C2003D"},  # pink
    2: {"head": "#1E90FF", "body": "#87CEFA", "bow": "#0077FF", "knot": "#00408A"},  # blue
}

DEFAULT_PORT = 8765