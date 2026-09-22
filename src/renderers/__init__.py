"""渲染层：把引擎输出格式化为 Markdown 榜单与改枪指南。

只做格式化，不产出数值。
"""

from src.renderers.ttk_report import (
    band_doc_name,
    band_doc_ref,
    main_band_doc_prefix,
    render_band_doc,
    render_band_top_preview,
    render_gunsmith_guide,
    render_readme,
    scenario_doc_stem,
)

__all__ = [
    "render_readme",
    "render_band_doc",
    "render_band_top_preview",
    "render_gunsmith_guide",
    "scenario_doc_stem",
    "main_band_doc_prefix",
    "band_doc_name",
    "band_doc_ref",
]
