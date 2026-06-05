"""
处理管道模块

提供前处理管道（图片处理）和后处理管道（字段值处理）功能。
管道使用管道符 | 连接多个处理步骤，按从左到右顺序执行。
"""

import json
import logging
import re
from typing import Any, Callable

import cv2
import numpy as np

logger = logging.getLogger(__name__)


# ============================================================
# 管道解析工具
# ============================================================

def parse_pipeline(pipeline: str) -> list[tuple[str, list[str]]]:
    """
    解析管道字符串为步骤列表。

    Args:
        pipeline: 管道字符串，如 "strip|to_number|round(2)"

    Returns:
        list[tuple[str, list[str]]]: 步骤列表，每个元素为 (函数名, 参数列表)
            例如 [("strip", []), ("to_number", []), ("round", ["2"])]

    Raises:
        ValueError: 管道格式无效时抛出。
    """
    if not pipeline or not pipeline.strip():
        return []

    steps = []
    parts = pipeline.split("|")

    for part in parts:
        part = part.strip()
        if not part:
            continue

        # 匹配函数名和参数：func_name 或 func_name(arg1,arg2)
        match = re.match(r"^(\w+)(?:\(([^)]*)\))?$", part)
        if not match:
            raise ValueError(f"无效的管道步骤格式: '{part}'")

        func_name = match.group(1)
        args_str = match.group(2)

        if args_str:
            # 分割参数（注意：参数中不应包含管道符）
            args = [arg.strip() for arg in args_str.split(",")]
        else:
            args = []

        steps.append((func_name, args))

    return steps


# ============================================================
# 后处理函数（对字段值处理）
# ============================================================

def post_strip(value: Any) -> str:
    """去除字符串首尾空白"""
    if value is None:
        return ""
    return str(value).strip()


def post_lower(value: Any) -> str:
    """转小写"""
    if value is None:
        return ""
    return str(value).lower()


def post_upper(value: Any) -> str:
    """转大写"""
    if value is None:
        return ""
    return str(value).upper()


def post_to_number(value: Any) -> Any:
    """
    尝试转换为数字（整数或浮点数）。

    转换失败则保留原值。
    """
    if value is None:
        return None

    if isinstance(value, (int, float)):
        return value

    s = str(value).strip()

    # 尝试去除千分位逗号
    s = s.replace(",", "")

    try:
        # 尝试解析为整数
        if "." not in s:
            return int(s)
        else:
            return float(s)
    except ValueError:
        logger.warning(f"to_number: 无法将 '{value}' 转换为数字，保留原值")
        return value


def post_to_string(value: Any) -> str:
    """强制转为字符串"""
    if value is None:
        return ""
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False)
    return str(value)


def post_json_parse(value: Any) -> Any:
    """
    尝试解析 JSON 字符串为 Python 对象。

    解析失败则保留原值。
    """
    if value is None:
        return None

    if isinstance(value, (dict, list)):
        return value

    s = str(value).strip()

    try:
        return json.loads(s)
    except json.JSONDecodeError:
        logger.warning(f"json_parse: 无法解析 '{s[:50]}...'，保留原值")
        return value


def post_round(value: Any, decimals: str = "0") -> Any:
    """
    对数字四舍五入保留 N 位小数。

    Args:
        value: 输入值
        decimals: 保留的小数位数（字符串格式）

    Returns:
        四舍五入后的数字，非数字则返回原值
    """
    if value is None:
        return None

    try:
        d = int(decimals)
    except ValueError:
        logger.warning(f"round: 无效的小数位数 '{decimals}'，使用默认值 0")
        d = 0

    if isinstance(value, (int, float)):
        return round(value, d)

    # 尝试转换
    try:
        num = float(str(value).replace(",", ""))
        return round(num, d)
    except ValueError:
        logger.warning(f"round: '{value}' 不是有效数字，保留原值")
        return value


def post_replace(value: Any, old: str = " ", new: str = "") -> Any:
    """
    替换子串。

    Args:
        value: 输入值
        old: 要替换的子串
        new: 替换为的子串

    Returns:
        替换后的字符串
    """
    if value is None:
        return None

    s = str(value)
    return s.replace(old, new)


# 后处理函数注册表
POST_PROCESSORS: dict[str, Callable] = {
    "strip": post_strip,
    "lower": post_lower,
    "upper": post_upper,
    "to_number": post_to_number,
    "to_string": post_to_string,
    "json_parse": post_json_parse,
    "round": post_round,
    "replace": post_replace,
}


def execute_post_process_pipeline(value: Any, pipeline: str) -> Any:
    """
    执行后处理管道。

    按从左到右的顺序依次执行每个处理函数。

    Args:
        value: 初始值
        pipeline: 管道字符串，如 "strip|to_number|round(2)"

    Returns:
        处理后的值

    Raises:
        ValueError: 管道格式无效或函数不存在时抛出。
    """
    if not pipeline or not pipeline.strip():
        return value

    steps = parse_pipeline(pipeline)
    result = value

    for func_name, args in steps:
        if func_name not in POST_PROCESSORS:
            raise ValueError(f"未知的后处理函数: '{func_name}'")

        func = POST_PROCESSORS[func_name]

        try:
            result = func(result, *args)
            logger.debug(f"后处理步骤 '{func_name}({', '.join(args)})' 执行成功: {result}")
        except Exception as e:
            logger.error(f"后处理步骤 '{func_name}' 执行失败: {e}")
            raise ValueError(f"后处理步骤 '{func_name}' 执行失败: {e}") from e

    return result


# ============================================================
# 前处理函数（对图片处理）
# ============================================================

def pre_fix_orientation(image: np.ndarray) -> np.ndarray:
    """
    根据 EXIF 信息自动旋转图片。

    注意：当前实现假设图片已被正确读取，EXIF 信息可能已丢失。
    此函数预留用于处理 EXIF 方向标签。

    Args:
        image: OpenCV 图像数组

    Returns:
        处理后的图像数组
    """
    # OpenCV 读取时默认不处理 EXIF 方向
    # 如果需要处理 EXIF，需要使用 PIL 或其他库读取原始 EXIF 信息
    # 当前版本作为占位符，直接返回原图
    logger.debug("fix_orientation: 当前版本暂不处理 EXIF 方向")
    return image


def pre_deskew(image: np.ndarray) -> np.ndarray:
    """
    倾斜矫正。

    使用霍夫变换检测倾斜角度并旋转矫正。

    Args:
        image: OpenCV 图像数组

    Returns:
        矫正后的图像数组
    """
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY) if len(image.shape) == 3 else image

    # 边缘检测
    edges = cv2.Canny(gray, 50, 150, apertureSize=3)

    # 霍夫变换检测直线
    lines = cv2.HoughLinesP(
        edges, rho=1, theta=np.pi / 180, threshold=100,
        minLineLength=100, maxLineGap=10
    )

    if lines is None or len(lines) == 0:
        logger.debug("deskew: 未检测到直线，跳过矫正")
        return image

    # 计算所有直线的角度
    angles = []
    for line in lines:
        x1, y1, x2, y2 = line[0]
        if x2 - x1 != 0:
            angle = np.degrees(np.arctan2(y2 - y1, x2 - x1))
            # 只考虑接近水平或垂直的直线
            if abs(angle) < 45 or abs(angle) > 135:
                angles.append(angle)

    if not angles:
        logger.debug("deskew: 未找到有效的倾斜角度")
        return image

    # 取中位数角度
    median_angle = np.median(angles)

    # 角度太小则不矫正
    if abs(median_angle) < 0.5:
        logger.debug(f"deskew: 倾斜角度过小 ({median_angle:.2f}°)，跳过矫正")
        return image

    # 旋转图像
    (h, w) = image.shape[:2]
    center = (w // 2, h // 2)
    rotation_matrix = cv2.getRotationMatrix2D(center, median_angle, 1.0)

    # 计算旋转后的画布大小
    cos = np.abs(rotation_matrix[0, 0])
    sin = np.abs(rotation_matrix[0, 1])
    new_w = int(h * sin + w * cos)
    new_h = int(h * cos + w * sin)

    # 调整旋转矩阵
    rotation_matrix[0, 2] += (new_w - w) / 2
    rotation_matrix[1, 2] += (new_h - h) / 2

    rotated = cv2.warpAffine(
        image, rotation_matrix, (new_w, new_h),
        flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_CONSTANT,
        borderValue=(255, 255, 255) if len(image.shape) == 3 else 255
    )

    logger.info(f"deskew: 矫正倾斜角度 {median_angle:.2f}°")
    return rotated


def pre_denoise(image: np.ndarray) -> np.ndarray:
    """
    去噪。

    使用非局部均值去噪算法。

    Args:
        image: OpenCV 图像数组

    Returns:
        去噪后的图像数组
    """
    if len(image.shape) == 3:
        # 彩色图像
        denoised = cv2.fastNlMeansDenoisingColored(image, None, h=10, hColor=10, templateWindowSize=7, searchWindowSize=21)
    else:
        # 灰度图像
        denoised = cv2.fastNlMeansDenoising(image, None, h=10, templateWindowSize=7, searchWindowSize=21)

    logger.debug("denoise: 去噪完成")
    return denoised


def pre_scale(image: np.ndarray, short_edge: str = "1024") -> np.ndarray:
    """
    缩放图片短边到指定像素。

    Args:
        image: OpenCV 图像数组
        short_edge: 目标短边像素数（字符串格式）

    Returns:
        缩放后的图像数组
    """
    try:
        target = int(short_edge)
    except ValueError:
        logger.warning(f"scale: 无效的目标短边 '{short_edge}'，使用默认值 1024")
        target = 1024

    h, w = image.shape[:2]
    current_short = min(h, w)

    if current_short == target:
        return image

    scale = target / current_short
    new_w = int(w * scale)
    new_h = int(h * scale)

    resized = cv2.resize(image, (new_w, new_h), interpolation=cv2.INTER_AREA if scale < 1 else cv2.INTER_LINEAR)

    logger.debug(f"scale: 缩放 {w}x{h} -> {new_w}x{new_h}")
    return resized


def pre_crop(image: np.ndarray, x1: str = "0", y1: str = "0", x2: str = "1", y2: str = "1") -> np.ndarray:
    """
    裁剪图片区域。

    Args:
        image: OpenCV 图像数组
        x1, y1, x2, y2: 裁剪区域坐标（支持百分比 0-1 或像素值）

    Returns:
        裁剪后的图像数组
    """
    h, w = image.shape[:2]

    def parse_coord(val: str, max_val: int) -> int:
        """解析坐标值，支持百分比和像素值"""
        val = val.strip()
        if "." in val:
            # 百分比
            ratio = float(val)
            return int(ratio * max_val)
        else:
            # 像素值
            return int(val)

    try:
        px1 = parse_coord(x1, w)
        py1 = parse_coord(y1, h)
        px2 = parse_coord(x2, w)
        py2 = parse_coord(y2, h)
    except ValueError as e:
        logger.warning(f"crop: 无效的坐标值: {e}")
        return image

    # 边界检查
    px1 = max(0, min(px1, w))
    py1 = max(0, min(py1, h))
    px2 = max(0, min(px2, w))
    py2 = max(0, min(py2, h))

    if px1 >= px2 or py1 >= py2:
        logger.warning(f"crop: 无效的裁剪区域 ({px1},{py1})-({px2},{py2})")
        return image

    cropped = image[py1:py2, px1:px2]
    logger.debug(f"crop: 裁剪 ({px1},{py1})-({px2},{py2})")
    return cropped


def pre_to_grayscale(image: np.ndarray) -> np.ndarray:
    """
    转为灰度图。

    Args:
        image: OpenCV 图像数组

    Returns:
        灰度图像数组
    """
    if len(image.shape) == 3:
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        logger.debug("to_grayscale: 转换完成")
        return gray
    else:
        logger.debug("to_grayscale: 图像已是灰度图")
        return image


def pre_enhance_contrast(image: np.ndarray) -> np.ndarray:
    """
    增强对比度。

    使用 CLAHE（对比度受限的自适应直方图均衡化）。

    Args:
        image: OpenCV 图像数组

    Returns:
        增强后的图像数组
    """
    if len(image.shape) == 3:
        # 彩色图像：在 LAB 颜色空间的 L 通道上应用 CLAHE
        lab = cv2.cvtColor(image, cv2.COLOR_BGR2LAB)
        l, a, b = cv2.split(lab)
        clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
        l = clahe.apply(l)
        lab = cv2.merge([l, a, b])
        enhanced = cv2.cvtColor(lab, cv2.COLOR_LAB2BGR)
    else:
        # 灰度图像
        clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
        enhanced = clahe.apply(image)

    logger.debug("enhance_contrast: 对比度增强完成")
    return enhanced


# 前处理函数注册表
PRE_PROCESSORS: dict[str, Callable] = {
    "fix_orientation": pre_fix_orientation,
    "deskew": pre_deskew,
    "denoise": pre_denoise,
    "scale": pre_scale,
    "crop": pre_crop,
    "to_grayscale": pre_to_grayscale,
    "enhance_contrast": pre_enhance_contrast,
}


def execute_pre_process_pipeline(image_bytes: bytes, pipeline: str) -> bytes:
    """
    执行前处理管道。

    按从左到右的顺序依次执行每个处理函数。

    Args:
        image_bytes: 原始图片字节数据
        pipeline: 管道字符串，如 "fix_orientation|deskew|scale(1024)"

    Returns:
        处理后的图片字节数据

    Raises:
        ValueError: 管道格式无效或函数不存在时抛出。
    """
    if not pipeline or not pipeline.strip():
        return image_bytes

    steps = parse_pipeline(pipeline)

    # 解码图片
    nparr = np.frombuffer(image_bytes, np.uint8)
    image = cv2.imdecode(nparr, cv2.IMREAD_COLOR)

    if image is None:
        raise ValueError("无法解码图片")

    # 执行每个处理步骤
    for func_name, args in steps:
        if func_name not in PRE_PROCESSORS:
            raise ValueError(f"未知的前处理函数: '{func_name}'")

        func = PRE_PROCESSORS[func_name]

        try:
            image = func(image, *args)
            logger.debug(f"前处理步骤 '{func_name}({', '.join(args)})' 执行成功")
        except Exception as e:
            logger.error(f"前处理步骤 '{func_name}' 执行失败: {e}")
            raise ValueError(f"前处理步骤 '{func_name}' 执行失败: {e}") from e

    # 编码为 JPEG
    encode_params = [int(cv2.IMWRITE_JPEG_QUALITY), 85]
    success, encoded = cv2.imencode('.jpg', image, encode_params)

    if not success:
        raise ValueError("无法将处理后的图片编码为 JPEG")

    result = encoded.tobytes()
    logger.info(f"前处理管道完成: {len(steps)} 个步骤, 大小 {len(image_bytes)} -> {len(result)} bytes")

    return result


# ============================================================
# 扩展机制
# ============================================================

def register_post_processor(name: str, func: Callable) -> None:
    """
    注册自定义后处理函数。

    Args:
        name: 函数名称
        func: 处理函数，接受一个值和可选参数，返回处理后的值
    """
    POST_PROCESSORS[name] = func
    logger.info(f"注册自定义后处理函数: {name}")


def register_pre_processor(name: str, func: Callable) -> None:
    """
    注册自定义前处理函数。

    Args:
        name: 函数名称
        func: 处理函数，接受一个 numpy 图像数组和可选参数，返回处理后的图像数组
    """
    PRE_PROCESSORS[name] = func
    logger.info(f"注册自定义前处理函数: {name}")
