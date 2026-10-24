"""Measure-aware comparison of score notes and performed notes."""

from .analysis import align_performance
from .models import AlignmentConfig

__all__ = ['AlignmentConfig', 'align_performance']
