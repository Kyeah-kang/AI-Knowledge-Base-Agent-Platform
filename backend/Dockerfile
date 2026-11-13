# ---------- 阶段 1：只负责装依赖 ----------
FROM python:3.13-slim AS deps
ENV PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1
WORKDIR /build
COPY requirements.txt .
RUN pip install --no-cache-dir --prefix=/install -r requirements.txt

# ---------- 阶段 2：运行时（不带 pip 缓存、不带编译工具） ----------
FROM python:3.13-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 TZ=Asia/Shanghai
WORKDIR /app

# 非 root 运行
RUN groupadd -r app && useradd -r -g app -m app

# 依赖从阶段 1 搬过来
COPY --from=deps /install /usr/local

# 代码（chown 给 app 用户）
COPY --chown=app:app . .

# 上传与日志目录必须可写：UPLOAD_DIR=uploads、LOG_DIR=logs 都相对 /app
RUN mkdir -p /app/uploads /app/logs && chown -R app:app /app/uploads /app/logs

USER app
EXPOSE 8000

# 给 compose 的 depends_on / 负载均衡用
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=3).status==200 else 1)"

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]