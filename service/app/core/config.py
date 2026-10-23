from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    app_name: str = "Forte Service"
    app_version: str = "0.1.0"
    environment: str = "development"

    # Injected by CDK as a Lambda environment variable
    dynamodb_users_table: str = "forte-users-dev"
    dynamodb_programs_table: str = "forte-programs-dev"
    dynamodb_content_table: str = "forte-content-dev"
    dynamodb_enrollments_table: str = "forte-enrollments-dev"
    dynamodb_completion_table: str = "forte-completion-dev"

    # JWT — the signing secret lives in SSM; CDK injects the parameter name.
    jwt_secret_param_name: str = ""
    jwt_algorithm: str = "HS256"
    jwt_expiry_days: int = 7

    class Config:
        env_file = ".env"
        case_sensitive = False


settings = Settings()
