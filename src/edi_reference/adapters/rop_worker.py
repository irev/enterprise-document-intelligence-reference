"""Isolated provider executable. Provision its dependencies offline, outside core .venv."""

import json
import os
import sys
from pathlib import Path


def main(work: Path) -> None:
    # These switches complement, not replace, host/container deny-egress policy.
    os.environ.update(HF_HUB_OFFLINE="1", TRANSFORMERS_OFFLINE="1",
                      PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK="True")
    request = json.loads((work / "request.json").read_text(encoding="utf-8"))
    if request["operation"] == "prepare":
        import cv2  # type: ignore[import-not-found]
        import numpy as np  # type: ignore[import-not-found]
        from PIL import Image, ImageOps  # type: ignore[import-not-found]

        Image.MAX_IMAGE_PIXELS = 25_000_000

        def save(image, index):
            if image.width * image.height > 25_000_000 or min(image.size) < 100:
                raise ValueError("IMAGE_RESOLUTION_LIMIT")
            image = ImageOps.exif_transpose(image).convert("RGB")
            image.thumbnail((2400, 2400))
            array = np.array(image)
            gray = cv2.cvtColor(array, cv2.COLOR_RGB2GRAY)
            edges = cv2.Canny(gray, 50, 150)
            lines = cv2.HoughLinesP(edges, 1, np.pi / 180, 80, minLineLength=100, maxLineGap=10)
            if lines is not None:
                angles = [float(np.degrees(np.arctan2(y2 - y1, x2 - x1))) for [[x1, y1, x2, y2]] in lines]
                angles = [a for a in angles if abs(a) <= 10]
                if len(angles) >= 5:
                    angle = float(np.median(angles))
                    if 0.3 <= abs(angle) <= 7:
                        image = image.rotate(angle, resample=Image.Resampling.BICUBIC, expand=True, fillcolor="white")
            image.save(work / f"page-{index:03}.png", optimize=True)

        if request["media"] == "application/pdf":
            import pypdfium2 as pdfium  # type: ignore[import-not-found]
            document = pdfium.PdfDocument(work / "input-0")
            try:
                if not 1 <= len(document) <= 20:
                    raise ValueError("PAGE_LIMIT")
                for n in range(len(document)):
                    page = document[n]
                    width, height = page.get_size()
                    scale = min(200 / 72, 2400 / max(width, height))
                    bitmap = page.render(scale=scale)
                    try:
                        save(bitmap.to_pil(), n + 1)
                    finally:
                        bitmap.close()
                        page.close()
            finally:
                document.close()
        else:
            with Image.open(work / "input-0") as image:
                save(image, 1)
        return
    if request["operation"] != "ocr":
        raise ValueError("INVALID_OPERATION")
    from paddleocr import PaddleOCR  # type: ignore[import-not-found]
    pipeline = PaddleOCR(
        text_detection_model_name=request["detection"]["name"],
        text_detection_model_dir=request["detection"]["directory"],
        text_recognition_model_name=request["recognition"]["name"],
        text_recognition_model_dir=request["recognition"]["directory"],
        use_doc_orientation_classify=False, use_doc_unwarping=False, use_textline_orientation=False,
    )
    pages = []
    for n in range(request["count"]):
        # Explicit PNG suffix for the provider's input-format dispatcher.
        source = work / f"input-{n}.png"
        (work / f"input-{n}").rename(source)
        results = list(pipeline.predict(str(source)))
        if len(results) != 1:
            raise ValueError("INVALID_OCR_PAGE_COUNT")
        value = results[0].json
        value = value() if callable(value) else value
        pages.append(value.get("res", value))
    (work / "result.json").write_text(json.dumps(pages), encoding="utf-8")


if __name__ == "__main__":
    main(Path(sys.argv[1]))
