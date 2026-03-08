"""Matrix Live Diarizer 入口"""
import uvicorn
from app import create_app
from app.config import config

app = create_app()

if __name__ == "__main__":
    uvicorn.run(
        app,
        host=config.server.host,
        port=config.server.port,
        workers=config.server.workers
    )
