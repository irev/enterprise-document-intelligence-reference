# Runtime profiles

These files document deployment boundaries. They intentionally do not install every ML framework into one environment.

- `core`: service/runtime without ML frameworks.
- `paddle`: PaddleOCR worker; choose CPU or NVIDIA-compatible PaddlePaddle build during image construction.
- `qwen-vl`: PyTorch/Transformers VLM worker.
- `docling`: document parser worker.
- `surya`: optional OCR/layout benchmark worker.

Production images must pin tested dependency versions and model revisions. Do not copy package versions between profiles merely because they share Python.
