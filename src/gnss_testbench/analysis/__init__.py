"""Анализ логов: эпохи, метрики, критерии приёмки, отчёты."""

from .criteria import CRITERIA, CheckResult, CriteriaError, Limit, evaluate, load_criteria, parse_limit
from .epochs import Epoch, build_epochs
from .metrics import Event, Metrics, Reference, compute_metrics
from .pipeline import AnalysisResult, analyze_bytes, analyze_file
from .report import to_dict, to_json, to_junit_xml, to_markdown

__all__ = [
    "CRITERIA", "AnalysisResult", "CheckResult", "CriteriaError", "Epoch", "Event", "Limit",
    "Metrics", "Reference", "analyze_bytes", "analyze_file", "build_epochs", "compute_metrics",
    "evaluate", "load_criteria", "parse_limit", "to_dict", "to_json", "to_junit_xml", "to_markdown",
]
