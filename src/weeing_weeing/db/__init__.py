"""db — PostgreSQL 저장소 (2차).

책임: telemetry · incident · analysis · report · approval · user · document 테이블과 저장·조회.
의존 가능: contracts
메모: 드라이버·ORM(예: SQLAlchemy + psycopg)은 2차 착수 때 uv add로 추가한다.
      SQL은 문자열 조립 대신 바인딩 파라미터를 쓴다(ruff S608).
"""
