#FROM andres77872/ubuntu_api:20.10-12.20
#FROM andres77872/ubuntu_base:23.04-80322
FROM python:3.12

WORKDIR /nn

COPY requirements.txt /nn

RUN pip install -r requirements.txt

COPY src /nn/src
