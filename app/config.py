from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime configuration, read from environment variables (or `.env`)."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql+psycopg://reconx:reconx@localhost:5432/reconx"
    # A 100,000-row statement is about 8 MB of CSV.
    max_upload_bytes: int = Field(default=25_000_000, gt=0)
