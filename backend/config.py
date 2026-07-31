from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    mongodb_uri: str = "mongodb://localhost:27017/rankengine"
    redis_url: str = "redis://localhost:6379"
    neo4j_uri: str = "bolt://localhost:7687"
    neo4j_user: str = "neo4j"
    neo4j_password: str = "rankengine123"
    groq_api_key: str = ""
    serp_api_key: str = ""
    dataforseo_login: str = ""
    dataforseo_password: str = ""
    crawl_max_pages: int = 50
    crawl_concurrency: int = 5
    crawl_timeout_seconds: int = 360
    log_level: str = "INFO"
    log_dir: str = "logs"

    model_config = {"env_file": ".env", "extra": "ignore"}

settings = Settings()
