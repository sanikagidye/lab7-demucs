FROM python:3.11-slim

WORKDIR /app

RUN apt-get update && \
    apt-get install -y --no-install-recommends \
    ffmpeg libsndfile1 && \
    rm -rf /var/lib/apt/lists/*

COPY requirements.txt .

RUN pip install --no-cache-dir \
    torch==2.6.0+cpu torchaudio==2.6.0+cpu \
    --index-url https://download.pytorch.org/whl/cpu

RUN pip install --no-cache-dir -r requirements.txt

COPY worker-server.py .

RUN python -c "import torch, torchaudio, demucs; print('PyTorch:', torch.__version__); print('CUDA:', torch.version.cuda)"

CMD ["python", "-u", "worker-server.py"]
