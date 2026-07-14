"""
处理管道模块（兼容层）

此文件保留用于向后兼容，实际代码已迁移至 processors/pipeline.py。
"""

from online.processors.pipeline import (
    parse_pipeline,
    execute_pre_process_pipeline,
    execute_post_process_pipeline,
    register_pre_processor,
    register_post_processor,
    PRE_PROCESSORS,
    POST_PROCESSORS,
    pre_fix_orientation,
    pre_deskew,
    pre_denoise,
    pre_scale,
    pre_crop,
    pre_to_grayscale,
    pre_enhance_contrast,
    post_strip,
    post_lower,
    post_upper,
    post_to_number,
    post_to_string,
    post_json_parse,
    post_round,
    post_replace,
)

__all__ = [
    "parse_pipeline",
    "execute_pre_process_pipeline",
    "execute_post_process_pipeline",
    "register_pre_processor",
    "register_post_processor",
    "PRE_PROCESSORS",
    "POST_PROCESSORS",
]