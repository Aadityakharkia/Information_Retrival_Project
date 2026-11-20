.PHONY: install run test bench bench-kp data lint
install:  ; pip install -r requirements.txt
run:      ; python -m uvicorn app.server:app --port 8000
test:     ; pytest -q
bench:    ; python experiments/run_benchmark.py
bench-kp: ; python experiments/keyphrase_benchmark.py
data:     ; python scripts/prepare_cs_library.py && python scripts/download_cranfield.py
lint:     ; ruff check searchbridge app experiments tests scripts
