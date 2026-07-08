from fastapi import FastAPI

app = FastAPI(title="Proxy")


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}
