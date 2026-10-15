from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    app_name: str = "Forte Service"
    app_version: str = "0.1.0"
    environment: str = "development"

    # Injected by CDK as a Lambda environment variable
    dynamodb_users_table: str = "forte-users-dev"

    class Config:
        env_file = ".env"
        case_sensitive = False


settings = Settings()
