"""L2 분석 런타임. 분석기가 공통으로 쓰는 뼈대.

수집 런타임(`votelink/collect/`)과 대칭이며, **서로를 import 하지 않는다.**
두 계층은 공통 레코드 계약으로만 연결된다 (docs/00-overview.md §3).
"""

from votelink.analyze.base import AnalyzeError, BaseAnalyzer, ComputeResult
from votelink.analyze.meta import AnalyzerMeta
from votelink.analyze.runner import AnalysisReport, run
from votelink.contract.models import Rejected

__all__ = [
    "AnalysisReport",
    "AnalyzeError",
    "AnalyzerMeta",
    "BaseAnalyzer",
    "ComputeResult",
    "Rejected",
    "run",
]
