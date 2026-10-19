FROM python:3.12-slim

# openssh-client — мост ходит на ноды по SSH (provision-channel.sh, systemctl, cat link).
# mkdir /root/.ssh — чтобы ssh мог сам принять host key ноды (StrictHostKeyChecking=accept-new).
RUN apt-get update \
    && apt-get install -y --no-install-recommends openssh-client \
    && rm -rf /var/lib/apt/lists/* \
    && mkdir -p /root/.ssh && chmod 700 /root/.ssh

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 8099
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8099"]
