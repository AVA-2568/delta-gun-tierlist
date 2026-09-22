"""渲染层：把引擎输出格式化为 Markdown 榜单与改枪指南。

只做格式化，不产出数值。
"""

from src.renderers.ttk_report import (
    main_band_doc_name,
    render_band_doc,
    render_band_top_preview,
    render_gunsmith_guide,
    render_readme,
    render_scenario_markdown,
    scenario_doc_stem,
)

__all__ = [
    "render_readme",
    "render_scenario_markdown",
    "render_band_doc",
    "render_band_top_preview",
    "render_gunsmith_guide",
    "scenario_doc_stem",
    "main_band_doc_name",
]
