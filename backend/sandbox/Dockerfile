# 沙箱基础镜像：模型生成的代码在此执行（非 root、无网络、限额由运行参数施加）
FROM python:3.12-slim

# 数据处理常用库（经国内镜像加速构建）
RUN pip install --no-cache-dir \
    -i https://pypi.tuna.tsinghua.edu.cn/simple \
    numpy pandas openpyxl

# 非 root 执行用户；工作目录归其所有（代码注入 / 产出发送均经 tar 归档）
RUN useradd -m -u 1000 -s /usr/sbin/nologin sandbox
USER 1000:1000
WORKDIR /home/sandbox

# 代码写 main.py，产物统一写到 out/ 目录
CMD ["python", "main.py"]
