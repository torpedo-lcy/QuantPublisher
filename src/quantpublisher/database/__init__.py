"""quantpublisher.database 패키지.

Database 클래스와 init_db()를 패키지 최상위에서 노출한다.
개별 함수형 API가 필요하면 quantpublisher.database.connection을 직접 사용한다.
"""

from quantpublisher.database.core import Database, init_db

__all__ = ["Database", "init_db"]
