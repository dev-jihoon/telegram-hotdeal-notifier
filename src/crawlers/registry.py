REGISTRY: dict[str, type] = {}


def register_crawler(site_key: str):
    def decorator(cls):
        cls.site_key = site_key
        REGISTRY[site_key] = cls
        return cls

    return decorator
