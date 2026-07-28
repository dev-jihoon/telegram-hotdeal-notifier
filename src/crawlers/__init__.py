from __future__ import annotations

import importlib
import pkgutil

from ..config import Config
from .base import BaseCrawler  # noqa: F401
from .registry import REGISTRY

_SKIP = {"base", "registry"}

for _, _module_name, _ in pkgutil.iter_modules(__path__):
    if _module_name not in _SKIP:
        importlib.import_module(f"{__name__}.{_module_name}")


def load_all_crawlers(config: Config) -> list[BaseCrawler]:
    """config.yaml에 등록된 모든 사이트의 크롤러를 로드한다 (enabled 여부 무관).

    on/off는 이제 관리자가 텔레그램 버튼으로 런타임에 DB(site_state)를 통해
    제어하므로, config.yaml의 enabled 값은 최초 기본값으로만 쓰인다.
    """
    crawlers = []
    for site_config in config.sites.values():
        cls = REGISTRY.get(site_config.key)
        if cls is None:
            raise ValueError(
                f"Unknown site '{site_config.key}'. Available: {sorted(REGISTRY)}"
            )
        crawlers.append(cls(site_config, config.crawl))
    return crawlers
