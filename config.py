from pydantic import BaseModel


class ScopedConfig(BaseModel):
    api_url: str
    api_token: str | None = None


class Config(BaseModel):
    rhythmnest: ScopedConfig
