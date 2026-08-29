# Copyright (c) Huawei Technologies Co., Ltd. 2023-2024. All rights reserved.
import os
import cv2
import numpy as np
import requests
import logging
from src.enum.ocr import OcrMethodEnum
from src.service.instruct_scan import InstructScanService
from src.config.config import Config
logger = logging.getLogger(__name__)


def _resolve_ocr_model_dir(name):
    candidates = [os.path.join('src', 'model', 'ocr', name)]
    cache_root = os.environ.get('SHENNONG_OCR_MODELS_DIR')
    if cache_root:
        candidates.append(os.path.join(cache_root, name))
    for candidate in candidates:
        if os.path.isdir(candidate):
            return candidate
    return candidates[0]


class OcrTool:
    det_model_dir = _resolve_ocr_model_dir('ch_PP-OCRv4_det_infer')
    rec_model_dir = _resolve_ocr_model_dir('ch_PP-OCRv4_rec_infer')
    cls_model_dir = _resolve_ocr_model_dir('ch_ppocr_mobile_v2.0_cls_infer')
    # 优化 OCR 参数配置
    if InstructScanService.check_avx512_support() and Config().get_config().ocr_config.method == OcrMethodEnum.OFFLINE:
        missing_models = [d for d in (det_model_dir, rec_model_dir, cls_model_dir) if not os.path.isdir(d)]
        if missing_models:
            unavailable_reason = (
                "[OCRTool] 本地 OCR 模型缺失: " + ", ".join(missing_models)
                + "。请运行 'shennong-setup install' 联网自动下载（online 包），"
                "或改用内置模型的 offline 包。详见 README「OCR 模型获取」。"
            )
            logger.error(unavailable_reason)
            model = None
        else:
            from paddleocr import PaddleOCR
            model = PaddleOCR(
                det_model_dir=det_model_dir,
                rec_model_dir=rec_model_dir,
                cls_model_dir=cls_model_dir,
                use_angle_cls=True,
                lang="ch",
                show_log=False
            )
    else:
        unavailable_reason = "[OCRTool] 当前机器不支持 AVX-512，无法进行OCR识别"
        model = None

    @staticmethod
    async def ocr_from_image_path(image_path: str) -> list | None:
        try:
            # 打开图片
            if Config().get_config().ocr_config.method == OcrMethodEnum.ONLINE and Config().get_config().ocr_config.api_url:
                result = requests.get(Config().get_config().ocr_config.api_url, files={'file': (
                    image_path, open(image_path, 'rb'), 'image/jpeg')}).json()
                return result.get("result", [])
            if OcrTool.model is None:
                err = getattr(OcrTool, 'unavailable_reason', None) or "[OCRTool] OCR 模型不可用"
                logging.error(err)
                return None
            image = cv2.imread(image_path)
            result = OcrTool.model.ocr(image, cls=True)
            return result
        except Exception as e:
            err = f"[OCRTool] OCR识别失败: {e}"
            logging.exception(err)
            return None

    @staticmethod
    async def ocr_from_image(image: np.ndarray) -> list | None:
        try:

            # 尝试OCR识别
            if OcrTool.model is None:
                err = getattr(OcrTool, 'unavailable_reason', None) or "[OCRTool] OCR 模型不可用"
                logging.error(err)
                return None
            ocr_result = OcrTool.model.ocr(image)
            return ocr_result
        except Exception as e:
            err = f"[OCRTool] OCR识别失败: {e}"
            logging.exception(err)
            return None

    @staticmethod
    async def merge_text_from_ocr_result(ocr_result: list | None) -> list[str] | str:
        text_list = []
        try:
            if ocr_result is None or ocr_result[0] is None or len(ocr_result[0]) == 0:
                return ""
            # 先根据x坐标对文本行进行排序，再根据y坐标对文本行进行排序，最后合并文本行
            ocr_result[0].sort(key=lambda x: (x[0][0][0], x[0][0][1]))
            for i in range(len(ocr_result[0])):
                if len(text_list) == 0:
                    text_list.append(str(ocr_result[0][i][1][0]))
                else:
                    last_y1 = min(point[1] for point in ocr_result[0][i-1][0])
                    current_y_1 = min(point[1]
                                      for point in ocr_result[0][i][0])
                    current_y_2 = max(point[1]
                                      for point in ocr_result[0][i][0])
                    # 如果当前文本行与上一行的y坐标差距较小，则认为它们在同一行，进行合并
                    vertical_distance = abs(current_y_1 - last_y1)
                    height = current_y_2 - current_y_1
                    if vertical_distance < height * 0.5:
                        text_list[-1] = text_list[-1] + \
                            str(ocr_result[0][i][1][0])
                    else:
                        text_list.append(str(ocr_result[0][i][1][0]))
            return text_list
        except Exception as e:
            err = f"[OCRTool] OCR结果合并失败 {e}"
            logging.exception(err)
            return ''

    @staticmethod
    async def image_to_text_list(
            image_file_path: str) -> list[str] | str:
        try:
            ocr_result = await OcrTool.ocr_from_image_path(image_file_path)
            text_list = await OcrTool.merge_text_from_ocr_result(ocr_result)
            return text_list
        except Exception as e:
            err = f"[OCRTool] 图片转文本失败 {e}"
            logging.exception(err)
            return ''
