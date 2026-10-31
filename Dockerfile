# ==============================================================================
# 构建 Python 3.11 运行时环境（集成 Linux 开源中文字体与 Node.js 运行时）
# ==============================================================================
FROM python:3.11-slim

WORKDIR /app

# 1. 替换为阿里云 Debian 镜像源，大幅提升国内服务器 apt 下载速度
RUN if [ -f /etc/apt/sources.list.d/debian.sources ]; then \
        sed -i 's/deb.debian.org/mirrors.aliyun.com/g' /etc/apt/sources.list.d/debian.sources; \
    fi; \
    if [ -f /etc/apt/sources.list ]; then \
        sed -i 's/deb.debian.org/mirrors.aliyun.com/g' /etc/apt/sources.list; \
    fi

# 2. 安装系统级依赖、中文字体库与 Node.js 运行时 (同花顺 pywencai 必须)
RUN apt-get update && apt-get install -y --no-install-recommends \
    fonts-wqy-zenhei \
    fonts-wqy-microhei \
    fontconfig \
    nodejs \
    curl \
    gcc \
    g++ \
    libssl-dev \
    && fc-cache -fv \
    && rm -rf /var/lib/apt/lists/*

# 设置核心生产环境变量：强制无缓冲、UTF-8 编码、静默浏览器弹窗
ENV PYTHONUNBUFFERED=1 \
    PYTHONIOENCODING=utf-8 \
    NO_BROWSER=1 \
    FAST_MODE=1

# 3. 安装 Python 核心依赖（配置阿里云 PyPI 镜像源高速下载）
COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip -i https://mirrors.aliyun.com/pypi/simple/ \
    && pip install --no-cache-dir -r requirements.txt -i https://mirrors.aliyun.com/pypi/simple/

# 4. 拷贝工程源码与已预编译好的前端 React 静态页面 (frontend/dist)
COPY . /app

# 暴露端口：8000 (FastAPI + React SPA + WebSocket), 8888 (实时分时16宫格服务)
EXPOSE 8000 8888

# 启动后端服务
CMD ["python", "server.py"]
