from __future__ import annotations

import fcntl
import logging
import os
import sys
from pathlib import Path

logger = logging.getLogger(__name__)

# GC로 파일 핸들이 닫혀서 잠금이 풀리지 않도록 프로세스 생존 기간 동안 참조를 들고 있는다.
_lock_handle = None


def acquire_singleton_lock(db_path: str) -> None:
    """같은 DB를 대상으로 봇이 중복 실행되는 걸 막는다.

    Ctrl+Z로 프로세스를 완전히 안 끄고 재시작하거나, 서로 다른 폴더에서 각각
    docker compose up을 하는 등 인스턴스가 두 개 이상 같은 DB에 붙으면, 서로의
    부트스트랩/삭제 판정을 경합해서 옛날 글이 새 글로 재전송되는 등 데이터가
    꼬인다. 프로세스 시작 시점에 락 파일을 잡아서 두 번째 인스턴스는 아예
    뜨지 못하게 막는다.
    """
    global _lock_handle

    lock_path = Path(db_path).with_suffix(".lock")
    lock_path.parent.mkdir(parents=True, exist_ok=True)

    handle = open(lock_path, "w")
    try:
        fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        handle.close()
        print(
            f"[치명적 오류] 이미 다른 봇 프로세스가 실행 중입니다 ({lock_path}가 잠겨있음).\n"
            "중복 실행하면 부트스트랩/삭제 판정이 꼬여서 옛날 글이 새 글로 재전송될 수 있습니다.\n"
            "`ps aux | grep src.main` (또는 `docker ps -a`)로 기존 프로세스를 찾아 완전히 "
            "종료(kill, Ctrl+C가 안 먹히면 kill -9)한 뒤 다시 실행하세요.",
            file=sys.stderr,
        )
        sys.exit(1)

    handle.write(str(os.getpid()))
    handle.flush()
    _lock_handle = handle
    logger.info("singleton lock acquired: %s (pid %d)", lock_path, os.getpid())
