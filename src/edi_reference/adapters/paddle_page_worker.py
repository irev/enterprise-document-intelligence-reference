"""PaddleOCR page worker, executed by the isolated PaddleOCR runtime interpreter.

Never imported by the core process. Input and output are files in a private
work directory: request.json + input document -> result.json. Document bytes
are data only; the argument vector is fixed by the caller.
"""

import json
import os
import sys
from pathlib import Path


def main(work: Path) -> None:
    os.environ.update(HF_HUB_OFFLINE="1", PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK="True")
    request = json.loads((work / "request.json").read_text(encoding="utf-8"))
    import pypdfium2 as pdfium  # type: ignore[import-not-found]
    from paddleocr import PaddleOCR  # type: ignore[import-not-found]
    from PIL import Image  # type: ignore[import-not-found]

    Image.MAX_IMAGE_PIXELS = 50_000_000
    source = work / "input"
    images: list[Path] = []
    text_layer: list[str] = []
    if request["media"] == "application/pdf":
        document = pdfium.PdfDocument(str(source))
        try:
            total = len(document)
            for index in range(min(total, int(request["max_pages"]))):
                page = document[index]
                text_layer.append(page.get_textpage().get_text_range())
                width, height = page.get_size()
                target = work / f"page-{index:03d}.png"
                page.render(scale=min(200 / 72, 2400 / max(width, height))).to_pil().convert("RGB").save(target)
                images.append(target)
        finally:
            document.close()
    else:
        total = 1
        target = work / "page-000.png"
        with Image.open(source) as image:
            image.convert("RGB").save(target)
        images.append(target)

    ocr = request["ocr"]
    pipeline = PaddleOCR(
        text_detection_model_name=ocr["det_name"], text_detection_model_dir=ocr["det_dir"],
        text_recognition_model_name=ocr["rec_name"], text_recognition_model_dir=ocr["rec_dir"],
        use_doc_orientation_classify=False, use_doc_unwarping=False, use_textline_orientation=False,
    )
    pages = []
    for image in images:
        results = list(pipeline.predict(str(image)))
        if len(results) != 1:
            raise SystemExit("INVALID_OCR_PAGE_COUNT")
        result = results[0]
        payload = result.json() if callable(result.json) else result.json
        res = payload.get("res", payload)
        shape = result["doc_preprocessor_res"]["output_img"].shape
        pages.append({"res": {
            "rec_texts": [str(t) for t in res["rec_texts"]],
            "rec_boxes": [[int(v) for v in box] for box in res["rec_boxes"]],
            "rec_scores": [float(v) for v in res["rec_scores"]],
            "input_img_shape": [int(shape[0]), int(shape[1])],
        }})
    output = {"pages": pages, "text_layer": text_layer, "total_pages": total}
    (work / "result.json").write_text(json.dumps(output, ensure_ascii=False), encoding="utf-8")


if __name__ == "__main__":
    main(Path(sys.argv[1]))
