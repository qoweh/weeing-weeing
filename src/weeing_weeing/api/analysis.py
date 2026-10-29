"""#104: 영속 작업 대기열을 단일 스레드에서 처리한다. 센서 수신에서 LLM을 호출하지 않는다."""

import logging
import time
from threading import Event, Lock, Thread
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from weeing_weeing.agent.interface import get_analyzer
from weeing_weeing.api.auth import CurrentUser, require_roles
from weeing_weeing.contracts import AnalysisResult, Role
from weeing_weeing.db import interface as db
from weeing_weeing.rag.interface import get_retriever

logger = logging.getLogger("uvicorn.error.analysis")
router = APIRouter(tags=["analysis"])


class AnalysisService:
    """API 프로세스당 하나. 운영은 --workers 1, replica 1개만 지원한다."""

    def __init__(
        self, repository=db.get_analysis_jobs, analyzer=None, *, poll_seconds=0.5
    ):
        self.repository = repository
        self.analyzer = analyzer or (lambda: get_analyzer(get_retriever()))
        self.poll_seconds = poll_seconds
        self.stop_event = Event()
        self.wakeup = Event()
        self.thread = None
        self.write_lock = Lock()
        self.notified = set()
        self.last_worker_error = None
        self.pending_result = None

    def start(self):
        self.thread = Thread(target=self._loop, name="incident-analysis", daemon=True)
        self.thread.start()

    def stop(self):
        self.stop_event.set()
        self.wakeup.set()
        if self.thread:
            self.thread.join(timeout=5)
            if self.thread.is_alive():
                logger.warning(
                    "[분석 종료 대기] 실행 중 호출은 강제 재시도하지 않음; 재시작 시 interrupted 처리"
                )

    def ingest(self, record, incidents):
        try:
            with self.write_lock:
                jobs = self.repository().record_frame(record, incidents)
                for job in jobs:
                    if job["job_id"] not in self.notified:
                        logger.info(
                            "[분석 등록] incident=%s job=%s state=%s",
                            job["incident_id"],
                            job["job_id"],
                            job["status"],
                        )
                        # 로그 중복 억제만 담당. 실행 중복 방지의 기준은 DB다.
                        if len(self.notified) >= 1000:
                            self.notified.clear()
                        self.notified.add(job["job_id"])
            self.wakeup.set()
            return {
                "agent_status": "connected",
                "db_status": "saved",
                "analysis_jobs": jobs,
            }
        except Exception as exc:
            logger.error(
                "[분석 저장 실패] record=%s code=%s (센서 탐지는 계속됨)",
                record.record_id,
                type(exc).__name__,
            )
            return {
                "agent_status": "storage_failed",
                "db_status": "failed",
                "analysis_jobs": [],
            }

    def process_one(self):
        repo = self.repository()
        if self.pending_result is not None:
            # LLM 응답 뒤 DB가 끊겨도 유료 호출은 반복하지 않고 저장만 재시도한다.
            job_id, result = self.pending_result
            with self.write_lock:
                if result is None:
                    repo.fail(job_id, "execution_or_save_failed")
                else:
                    repo.finish(job_id, result)
            self.pending_result = None
            logger.info("[분석 저장 복구] job=%s LLM 재호출 없음", job_id)
            return True
        with self.write_lock:
            claimed = repo.claim()
        if claimed is None:
            return False
        job_id, incident = claimed
        started = time.monotonic()
        logger.info(
            "[분석 시작] incident=%s job=%s codes=%s",
            incident.incident_id,
            job_id,
            ",".join(incident.codes),
        )
        try:
            result = self.analyzer().analyze(incident)
            result = AnalysisResult.model_validate(result.model_dump())
            if result.incident_id != incident.incident_id:
                raise ValueError("분석 사건 ID 불일치")
            self.pending_result = (job_id, result)
            with self.write_lock:
                analysis_id = repo.finish(job_id, result)
            self.pending_result = None
            logger.info(
                "[분석 저장 완료] incident=%s job=%s analysis=%s result=%s evidence=%d elapsed=%.1fs",
                incident.incident_id,
                job_id,
                analysis_id,
                result.status,
                len(result.evidence),
                time.monotonic() - started,
            )
        except db.DatabaseUnavailableError:
            # finish에서 실패하면 메모리의 결과를 보존한다. 프로세스 종료 시에는
            # RUNNING 기록이 남으므로 다음 시작에서 interrupted로 바꾼다.
            if self.pending_result is None:
                self.pending_result = (job_id, None)
            raise
        except Exception as exc:
            # 응답 원문·API 키·공급자 예외 메시지는 로그나 DB에 넣지 않는다.
            logger.error(
                "[분석 실패] incident=%s job=%s code=%s (수동 재요청 필요)",
                incident.incident_id,
                job_id,
                type(exc).__name__,
            )
            self.pending_result = (job_id, None)
            with self.write_lock:
                repo.fail(job_id, "execution_or_save_failed")
            self.pending_result = None
        return True

    def _loop(self):
        initialized = False
        while not self.stop_event.is_set():
            try:
                if not initialized:
                    with self.write_lock:
                        count = self.repository().recover_interrupted()
                    logger.info("[분석 대기] interrupted=%d 자동 재호출 없음", count)
                    initialized = True
                if self.process_one():
                    self.last_worker_error = None
                    continue
                self.last_worker_error = None
            except Exception as exc:
                if self.pending_result is None:
                    # 선점 COMMIT만 성공하고 응답이 유실됐으면 job_id를 모른다.
                    # 단일 worker이므로 다음 주기에 고아 RUNNING을 FAILED로 복구한다.
                    initialized = False
                code = type(exc).__name__
                if code != self.last_worker_error:
                    logger.error("[분석 실행기 대기] code=%s (DB 복구 대기)", code)
                    self.last_worker_error = code
            self.wakeup.wait(self.poll_seconds)
            self.wakeup.clear()


@router.get("/incidents/{incident_id}/analysis")
def latest_analysis(incident_id: str, user: CurrentUser, request: Request):
    service = getattr(request.app.state, "analysis_service", None)
    repo = service.repository() if service else db.get_analysis_jobs()
    if repo.get_incident(incident_id) is None:
        raise HTTPException(404, "저장된 사건이 없습니다")
    result = repo.latest_analysis(incident_id)
    return {
        "job": repo.latest_job(incident_id),
        "analysis": result.model_dump(mode="json") if result else None,
    }


class RetryAnalysis(BaseModel):
    request_id: UUID  # 같은 버튼 요청을 재전송할 때 같은 UUID를 쓴다


@router.post(
    "/incidents/{incident_id}/analysis/retry",
    status_code=202,
    dependencies=[Depends(require_roles(Role.CONTROL, Role.MAINT_LEAD))],
)
def retry_analysis(incident_id: str, body: RetryAnalysis, request: Request):
    service = getattr(request.app.state, "analysis_service", None)
    if service is None:
        raise HTTPException(503, "자동 분석이 비활성 상태입니다")
    try:
        with service.write_lock:
            job = service.repository().retry(incident_id, str(body.request_id))
    except db.UnknownIncidentError as exc:
        raise HTTPException(404, "저장된 사건이 없습니다") from exc
    except db.AnalysisConflictError as exc:
        raise HTTPException(409, str(exc)) from exc
    service.wakeup.set()
    logger.info(
        "[분석 수동 요청] incident=%s job=%s state=%s",
        incident_id,
        job["job_id"],
        job["status"],
    )
    return job
