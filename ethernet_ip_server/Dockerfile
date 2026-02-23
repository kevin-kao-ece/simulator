###############################################################################
# Server
##############################################################################
FROM python:3.13-slim
RUN apt update && apt install -y vim iputils-ping && rm -rf /var/lib/apt/lists/*
ENV APP ethernet_ip_server
COPY . /${APP}
WORKDIR /${APP}
RUN pip3 install -r requirements.txt

# Run the cpppo module directly. 
# -u: unbuffered output so you see logs in 'docker logs'
# -a: bind to 0.0.0.0 so the container is reachable from the outside
CMD ["python3", "-u", "-m", "cpppo.server.enip", \
     "-a", "0.0.0.0:6003", \
     "Motor_Control=BOOL", \
     "Motor_Run=BOOL", \
     "Mode=SINT", \
     "Target_Speed=INT", \
     "Current_Speed=INT", \
     "Current_Temperature=REAL", \
     "Name=STRING"]
