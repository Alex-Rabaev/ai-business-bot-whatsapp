from pydantic_settings import BaseSettings
from pydantic import Field


class Settings(BaseSettings):
    # WhatsApp (Meta)
    ACCESS_TOKEN: str = Field(..., description="Permanent token (System User) или temp")
    PHONE_NUMBER_ID: str = Field(..., description="ID номера из WhatsApp Business")
    VERIFY_TOKEN: str = Field(..., description="Любая фраза для верификации вебхука в Meta")
    VERSION: str = Field("v18.0", description="Версия Graph API, напр. v20.0, v19.0, v18.0")
    RECIPIENT_WAID: str = Field(..., description="ID пользователя из WhatsApp Business")
    APP_ID: str = Field(..., description="ID приложения из WhatsApp Business")
    APP_SECRET: str = Field(..., description="Secret приложения из WhatsApp Business")
    # Mongo
    MONGO_URI: str
    MONGO_DB: str

    # Webhook
    WEBHOOK_URL: str = Field(..., description="URL вебхука")

    # LLM
    OPENAI_API_KEY: str

    class Config:
        env_file = ".env"


settings = Settings()