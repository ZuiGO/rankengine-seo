from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    mongodb_uri: str = "mongodb://localhost:27017/rankengine"
    redis_url: str = "redis://localhost:6379"
    neo4j_uri: str = "bolt://localhost:7687"
    neo4j_user: str = "neo4j"
    neo4j_password: str = "rankengine123"
    groq_api_key: str = ""
    groq_model: str = "openai/gpt-oss-120b"
    serp_api_key: str = ""
    dataforseo_login: str = ""
    dataforseo_password: str = ""
    gemini_api_key: str = ""
    pagespeed_api_key: str = ""
    slack_webhook_url: str = ""
    action_webhook_url: str = ""
    github_token: str = ""
    broken_link_alert_threshold: int = 5
    gemini_cost_per_million: float = 0.125
    groq_cost_per_million: float = 0.0
    dataforseo_cost_per_million: float = 0.0
    crawl_max_pages: int = 50
    crawl_concurrency: int = 5
    crawl_timeout_seconds: int = 360
    crawl_politeness_delay: float = 0.5
    crawl_robots_delay_max: float = 5.0
    mobile_crawl_concurrency: int = 5
    download_concurrency: int = 6
    psi_concurrency: int = 5
    extract_workers: int = 4
    competitor_crawl_max_pages: int = 5000
    competitor_psi_all_pages: bool = True
    log_level: str = "INFO"
    log_dir: str = "logs"

    model_config = {"env_file": ".env", "extra": "ignore"}

settings = Settings()
