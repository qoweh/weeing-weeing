# hmi — Streamlit 화면 (5차)

모니터링, Incident 목록, 보고서 작성, 결재, 매뉴얼 열람 화면을 둔다.

- 데이터는 반드시 `api`를 통해 읽고 쓴다. DB나 다른 모듈을 직접 import하지 않는다(나중에 서버를 분리해도 그대로 동작).
- 시작할 때 `uv add streamlit` 후 `hmi/app.py`를 만들고, 실행은 `uv run streamlit run hmi/app.py`.
- 화면 목록과 권한은 노션 '전체 할 일 정리 (분류별)' 6·8번을 따른다.
