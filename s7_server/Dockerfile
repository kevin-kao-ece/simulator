###############################################################################
# Server
##############################################################################
FROM python:3.13-slim
RUN apt update
RUN apt install -y vim
ENV APP s7_server
COPY . /${APP}
WORKDIR /${APP}
RUN pip3 install -r requirements.txt

CMD ["python3", "-u" , "./main.py" ]
