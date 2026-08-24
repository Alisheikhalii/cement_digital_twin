"""Visualization layer (PRD v1.1.1 Sections 17-19, 29).

Self-contained HTML/CSS/SVG twin renderer whose every animation parameter is bound to
``Twin.current_state_snapshot()`` (Section 19.4, AC-21), Plotly chart builders, the ten
dashboard views, and Factory Presentation Mode. No panel may contain a hard-coded numeric
value (NFR-6, AC-12).
"""
