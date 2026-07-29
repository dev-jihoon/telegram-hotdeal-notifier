from __future__ import annotations

import importlib
import logging
import pkgutil

from ..config import Config
from .base import BaseCrawler  # noqa: F401
from .registry import REGISTRY

logger = logging.getLogger(__name__)

_SKIP = {"base", "registry"}

for _, _module_name, _ in pkgutil.iter_modules(__path__):
    if _module_name not in _SKIP:
        importlib.import_module(f"{__name__}.{_module_name}")


def load_all_crawlers(config: Config) -> list[BaseCrawler]:
    """config.yaml에 등록된 사이트 중 폴링 크롤러가 구현된 것만 로드한다 (enabled 여부 무관).

    on/off는 이제 관리자가 텔레그램 버튼으로 런타임에 DB(site_state)를 통해
    제어하므로, config.yaml의 enabled 값은 최초 기본값으로만 쓰인다.

    등록된 크롤러 클래스가 없는 사이트 키는 에러를 내지 않고 조용히 건너뛴다 -
    브라우저 확장이 웹훅으로만 데이터를 보내는 "웹훅 전용" 사이트(예: 아카라이브의
    임의 게시판)는 애초에 폴링 크롤러가 필요 없기 때문이다.
    """
    crawlers = []
    for site_config in config.sites.values():
        cls = REGISTRY.get(site_config.key)
        if cls is None:
            logger.info(
                "site '%s' has no registered crawler - treating as webhook-only", site_config.key
            )
            continue
        crawlers.append(cls(site_config, config.crawl))
    return crawlers
