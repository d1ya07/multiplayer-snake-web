"""
Multiplayer Snake — Server (web version)
──────────────────────────────────────────
Serves the game webpage AND handles the WebSocket game logic from a single
URL, so players just open a link in their browser — no Python install needed
on their end.

Run locally with:  python3 server.py
Then open:          http://localhost:8765
"""

import asyncio
import json
import random
import os

from aiohttp import web, WSMsgType

from common import COLS, ROWS, SPEED, DEFAULT_PORT

STATIC_DIR = os.path.join(os.path.dirname(__file__), "static")


class Player:
    def __init__(self, player_id, ws, name):
        self.id = player_id
        self.ws = ws
        self.name = name
        self.snake = []
        self.dir = (1, 0)
        self.next_dir = (1, 0)
        self.alive = True
        self.score = 0
        self.death_reason = None   # "wall", "self", or None


class GameServer:
    def __init__(self):
        self.players = {}          # id -> Player
        self.food = (0, 0)
        self.over = False
        self.winner = None
        self.lock = asyncio.Lock()

    def _start_positions(self):
        return {
            1: [(5, ROWS // 2), (4, ROWS // 2), (3, ROWS // 2)],
            2: [(COLS - 6, ROWS // 2), (COLS - 5, ROWS // 2), (COLS - 4, ROWS // 2)],
        }

    def reset(self):
        starts = self._start_positions()
        dirs = {1: (1, 0), 2: (-1, 0)}
        for pid, p in self.players.items():
            p.snake = list(starts[pid])
            p.dir = dirs[pid]
            p.next_dir = dirs[pid]
            p.alive = True
            p.score = 0
            p.death_reason = None
        self.over = False
        self.winner = None
        self._place_food()

    def _place_food(self):
        occupied = set()
        for p in self.players.values():
            occupied.update(p.snake)
        while True:
            pos = (random.randint(0, COLS - 1), random.randint(0, ROWS - 1))
            if pos not in occupied:
                self.food = pos
                return

    async def tick(self):
        async with self.lock:
            if self.over or len(self.players) < 2:
                return

            for p in self.players.values():
                if p.alive:
                    p.dir = p.next_dir

            new_heads = {}
            for pid, p in self.players.items():
                if not p.alive:
                    continue
                hx, hy = p.snake[0]
                dx, dy = p.dir
                new_heads[pid] = (hx + dx, hy + dy)

            for pid, p in self.players.items():
                if not p.alive:
                    continue
                nx, ny = new_heads[pid]

                if not (0 <= nx < COLS and 0 <= ny < ROWS):
                    p.alive = False
                    p.death_reason = "wall"
                    continue

                if (nx, ny) in list(p.snake)[:-1]:
                    p.alive = False
                    p.death_reason = "self"
                    continue

                # Snakes pass through each other freely — no death on
                # crossing the other player's body or a head-on collision.

            for pid, p in self.players.items():
                if not p.alive:
                    continue
                p.snake.insert(0, new_heads[pid])
                if new_heads[pid] == self.food:
                    p.score += 10
                    self._place_food()
                else:
                    p.snake.pop()

            alive_ids = [pid for pid, p in self.players.items() if p.alive]
            if len(alive_ids) == 0:
                self.over = True
                self.winner = "draw"
            elif len(alive_ids) == 1 and len(self.players) == 2:
                self.over = True
                self.winner = alive_ids[0]

    def state_json(self):
        return json.dumps({
            "type": "state",
            "snakes": {
                str(pid): {
                    "body": p.snake,
                    "alive": p.alive,
                    "score": p.score,
                    "name": p.name,
                    "death_reason": p.death_reason,
                }
                for pid, p in self.players.items()
            },
            "food": self.food,
            "over": self.over,
            "winner": self.winner,
        })

    async def _send_to(self, pid, p, msg):
        try:
            # Hard timeout: if a client's connection is stalled (backgrounded
            # tab, flaky wifi, etc.) this send would otherwise block forever
            # and freeze the game loop for EVERY player, not just this one.
            await asyncio.wait_for(p.ws.send_str(msg), timeout=1.0)
            return None
        except (ConnectionResetError, asyncio.TimeoutError, RuntimeError, ConnectionError):
            return pid

    async def broadcast(self):
        if not self.players:
            return
        msg = self.state_json()
        # Send to all players concurrently (not one-after-another) so a slow
        # connection to Player A can't delay the update reaching Player B.
        results = await asyncio.gather(
            *(self._send_to(pid, p, msg) for pid, p in list(self.players.items()))
        )
        for pid in results:
            if pid is not None:
                self.players.pop(pid, None)


game = GameServer()


async def game_loop(app):
    while True:
        await asyncio.sleep(SPEED)
        if len(game.players) == 2:
            try:
                await game.tick()
                await game.broadcast()
            except Exception as e:
                # Never let one bad tick kill the loop for everyone —
                # this is what caused the game to "hang" permanently before.
                print(f"[game_loop] error during tick/broadcast: {e!r}")


async def start_background_tasks(app):
    app["game_loop"] = asyncio.create_task(game_loop(app))


async def websocket_handler(request):
    # heartbeat sends a ping every 15s and auto-closes the connection if the
    # client doesn't respond — catches truly-dead connections (closed laptop
    # lid, lost wifi, etc.) quickly instead of leaving a ghost player around.
    ws = web.WebSocketResponse(heartbeat=15)
    await ws.prepare(request)

    assigned = None
    async with game.lock:
        for pid in (1, 2):
            if pid not in game.players:
                assigned = pid
                break

    if assigned is None:
        await ws.send_str(json.dumps({"type": "full"}))
        await ws.close()
        return ws

    name = request.query.get("name", "").strip()[:20] or f"Player {assigned}"
    player = Player(assigned, ws, name)
    async with game.lock:
        game.players[assigned] = player
        if len(game.players) == 2:
            game.reset()

    await ws.send_str(json.dumps({"type": "welcome", "player_id": assigned}))
    await game.broadcast()

    try:
        async for msg in ws:
            if msg.type == WSMsgType.TEXT:
                data = json.loads(msg.data)
                if data.get("type") == "dir":
                    dx, dy = data["dx"], data["dy"]
                    cur = player.dir
                    if (dx, dy) != (-cur[0], -cur[1]):
                        player.next_dir = (dx, dy)
                elif data.get("type") == "restart":
                    async with game.lock:
                        if len(game.players) == 2:
                            game.reset()
                    await game.broadcast()
            elif msg.type == WSMsgType.ERROR:
                break
    finally:
        async with game.lock:
            game.players.pop(assigned, None)
            game.over = True
            game.winner = None
        await game.broadcast()

    return ws


async def index_handler(request):
    return web.FileResponse(os.path.join(STATIC_DIR, "index.html"))


def create_app():
    app = web.Application()
    app.router.add_get("/", index_handler)
    app.router.add_get("/ws", websocket_handler)
    app.router.add_static("/static/", STATIC_DIR)
    app.on_startup.append(start_background_tasks)
    return app


if __name__ == "__main__":
    port = int(os.environ.get("PORT", DEFAULT_PORT))
    web.run_app(create_app(), host="0.0.0.0", port=port)