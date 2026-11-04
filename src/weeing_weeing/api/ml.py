"""로그인 사용자의 읽기 전용 미래 Error 예측 조회. 추론/분석을 새로 요청하지 않는다."""

from fastapi import APIRouter, Query, Request, Response

from weeing_weeing.api.auth import CurrentUser

router = APIRouter(tags=["ml"])


@router.get("/ml/prediction")
def latest_prediction(request: Request, response: Response, user: CurrentUser):
    response.headers["Cache-Control"] = "no-store"
    return request.app.state.ml_service.snapshot()


@router.get("/ml/predictions")
def recent_predictions(
    request: Request,
    response: Response,
    user: CurrentUser,
    limit: int = Query(default=50, ge=1, le=200),
):
    response.headers["Cache-Control"] = "no-store"
    service = request.app.state.ml_service
    return service.recent_snapshot(limit)
