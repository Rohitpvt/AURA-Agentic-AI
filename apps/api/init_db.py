import os
import asyncio

os.environ["DATABASE_URL"] = "sqlite+aiosqlite:///aura_dev.db"

import app.db.models
from app.db.base import Base
from app.db.session import engine

async def init():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    print("Database schema with all models created successfully.")

if __name__ == "__main__":
    asyncio.run(init())
