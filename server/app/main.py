from fastapi import FastAPI


def create_app() -> FastAPI:
    app = FastAPI(title="digital-twin server")

    @app.get("/api/health")
    async def health() -> dict:
        return {"ok": True}

    return app


app = create_app()