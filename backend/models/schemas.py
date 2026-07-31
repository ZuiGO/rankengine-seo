from datetime import datetime
from pydantic import BaseModel, Field
from typing import Optional


class AnalysisJob(BaseModel):
    id: str = ""
    url: str
    status: str = "queued"  # queued, running, completed, failed
    progress: int = 0
    progress_message: str = ""
    created_at: datetime = Field(default_factory=datetime.utcnow)
    completed_at: Optional[datetime] = None
    error_message: Optional[str] = None
    summary: Optional[dict] = None


class PageData(BaseModel):
    url: str
    title: Optional[str] = None
    meta_description: Optional[str] = None
    word_count: int = 0
    status_code: int = 200
    h1_count: int = 0
    internal_links: int = 0
    external_links: int = 0
    image_count: int = 0
    images_missing_alt: int = 0
    has_structured_data: bool = False
    is_indexable: bool = True
    content_types: list = []


class ContentItem(BaseModel):
    id: str = ""
    job_id: str
    page_url: str
    content_type: str  # text, image, video, pdf, doc, xlsx, presentation
    source_url: str
    file_path: Optional[str] = None
    file_size: Optional[int] = None
    mime_type: Optional[str] = None
    seo_impact_score: Optional[float] = None
    identified_issues: list = []
    improvement_suggestions: list = []
    extracted_data: Optional[dict] = None


class ActionItem(BaseModel):
    id: str = ""
    content_item_id: str
    page_url: str
    content_type: str
    impact_on_ranking: str = ""  # high, medium, low
    identified_issue: str = ""
    how_to_improve: str = ""
    proposed_change: Optional[str] = None
    original_content: Optional[str] = None
    status: str = "pending"  # pending, approved, rejected, applied


class ReportData(BaseModel):
    job_id: str
    url: str
    generated_at: str
    total_pages: int
    total_links: int
    total_hyperlinks: int
    total_internal_links: int
    total_external_links: int
    total_backlinks: int
    content_breakdown: dict
    page_details: list
    health_score: Optional[float] = None
