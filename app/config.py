"""
Application configuration using Pydantic Settings.
Loads from environment variables or .env file.
"""
from pydantic_settings import BaseSettings
from functools import lru_cache


class Settings(BaseSettings):
    """Application settings loaded from environment."""
    
    # App
    app_name: str = "ApniFarm API"
    debug: bool = False
    
    # Database
    database_url: str = "postgresql+asyncpg://postgres:postgres@localhost:5432/apnifarm"
    
    # Firebase
    firebase_credentials_path: str = "firebase-credentials.json"
    
    # CORS
    cors_origins: list[str] = ["http://localhost:3000", "http://localhost:8080"]
    
    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"


@lru_cache
def get_settings() -> Settings:
    """Cached settings instance."""
    return Settings()
