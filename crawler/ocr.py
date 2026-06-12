# !/usr/bin/env python
# _*_ coding: utf-8 _*_
"""
OCR辅助：Boss直聘对薪资等关键文字做了字体混淆（Unicode私有区编码 + 自定义字体映射），
直接读取HTML文本拿到的是占位编码而非真实数字。
这里通过对页面元素截图 + OCR识别的方式还原真实文字——
不管字体映射规则怎么变，读的都是浏览器最终渲染出的视觉效果，最为稳健。
"""

import io

from PIL import Image
from rapidocr_onnxruntime import RapidOCR

_ocr_engine = None

# 薪资等文字在页面上渲染得很小，直接截图分辨率不够、OCR容易认错字符，
# 放大几倍后再识别能显著提升准确率
UPSCALE_FACTOR = 2


def _get_engine():
    global _ocr_engine
    if _ocr_engine is None:
        _ocr_engine = RapidOCR()
    return _ocr_engine


def recognize_element_text(element) -> str:
    """对 Playwright 元素截图并用OCR识别出文字内容，识别失败时返回空字符串"""
    if element is None:
        return ""
    try:
        screenshot_bytes = element.screenshot()
    except Exception:
        return ""

    try:
        img = Image.open(io.BytesIO(screenshot_bytes))
        img = img.resize(
            (img.width * UPSCALE_FACTOR, img.height * UPSCALE_FACTOR),
            Image.LANCZOS,
        )
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        screenshot_bytes = buf.getvalue()
    except Exception:
        pass

    # 薪资文本本身就是单行短文本，跳过"文本检测"阶段、直接整图识别（use_det=False），
    # 既避免检测阶段把"-"这种又细又小的字符漏检/拆错框导致顺序错乱或丢字符，
    # 识别结果也天然就是按行顺序排好的，无需再排序拼接
    result, _ = _get_engine()(screenshot_bytes, use_det=False)
    if not result:
        return ""
    return "".join(item[0] for item in result).strip()
