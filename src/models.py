from dataclasses import dataclass
from enum import Enum


class ArticleStatus(str, Enum):
    ACTIVE = "active"
    ENDED = "ended"
    SOLDOUT = "soldout"


@dataclass
class Article:
    site: str
    article_id: str
    title: str
    url: str
    price: str | None = None
    likes: int | None = None
    thumbnail_url: str | None = None
    category: str | None = None
    mall: str | None = None
    delivery: str | None = None
    status: ArticleStatus = ArticleStatus.ACTIVE
