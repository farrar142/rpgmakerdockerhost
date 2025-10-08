from typing import Literal
import reflex as rx
from redis.asyncio import Redis

import enum


class GameStatus(enum.Enum):
    RUNNING = "RUNNING"
    STOPPED = "STOPPED"
    NOTCREATED = "NOTCREATED"


class Game(rx.Model, table=True):
    dir: str
    port: int
    container_name: str
    status: GameStatus = GameStatus.NOTCREATED
    image: str = "farrar142/mvix"
