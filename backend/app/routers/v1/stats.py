"""
统计路由（P2-9）— 给 Dashboard 提供真实数字。

GET /api/v1/stats/overview → 当前用户的知识库/文档/失败文档/会话/消息数
"""

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_db
from app.models.user import User
from app.routers.v1 import get_current_user
from app.schemas.common import Response
from app.services.stats_service import StatsService

router = APIRouter(prefix="/stats", tags=["统计"])


def get_stats_service(db: AsyncSession = Depends(get_db)) -> StatsService:
    return StatsService(db)


@router.get(
    "/overview",
    summary="当前用户数据概览（Dashboard 用）",
    response_model=Response[dict],
)
async def overview(
    current_user: User = Depends(get_current_user),
    service: StatsService = Depends(get_stats_service),
):
    """
    当前用户的概览统计。

    只统计**属于自己**的数据；管理员也不会看到别人的数字
    （需要全局看板的话应该是另一个带权限校验的接口）。
    """
    data = await service.overview(current_user.id)
    return Response(data=data)
