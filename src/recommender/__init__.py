"""确定性推荐算法。"""

from .engine import RecommendationEngine
from .errors import RecommendationError

__all__ = ["RecommendationEngine", "RecommendationError"]
