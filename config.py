from pydantic import BaseModel


class ScopedConfig(BaseModel):
    api_url: str
    api_token: str | None = None
    notification_feishu_app_id: str | None = None
    notification_feishu_chat_id: str | None = None


class Config(BaseModel):
    rhythmnest: ScopedConfig
