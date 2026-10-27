"""db — PostgreSQL 저장소 (2차).

책임: telemetry · incident · analysis · report · approval · user · document 테이블과 저장·조회.
의존 가능: contracts, config
지금 있는 테이블: document(#60), incident·analysis(#61), telemetry(#63). report·approval·user는 #62.
사용법: docs/DB.md
메모: SQLAlchemy 2.x + psycopg 3(동기), 스키마는 Alembic(db/migrations).
      개발용으로 DATABASE_URL=sqlite:///storage/dev.db도 같은 코드로 동작한다.
      SQL은 문자열 조립 대신 바인딩 파라미터를 쓴다(ruff S608).
"""
