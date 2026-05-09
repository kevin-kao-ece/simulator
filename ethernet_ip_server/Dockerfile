###############################################################################
# Server
##############################################################################
FROM python:3.13-slim
RUN apt update && apt install -y vim iputils-ping && rm -rf /var/lib/apt/lists/*
ENV APP ethernet_ip_server
COPY . /${APP}
WORKDIR /${APP}
RUN pip3 install -r requirements.txt

# 使用本專案的 main.py（含 motor background logic）
CMD ["python3", "-u", "./main.py"]
