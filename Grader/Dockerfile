FROM python:3.12-slim

WORKDIR /app

COPY requirements-api.txt .
RUN pip install --no-cache-dir -r requirements-api.txt

COPY db.py llm.py sandbox.py grader.py api.py ./
COPY .env .env

# No Docker daemon runs in this image -- api.py/sandbox.py talk to the
# *host's* daemon over /var/run/docker.sock. Run this container with
# -v /var/run/docker.sock:/var/run/docker.sock to provide it standalone.

EXPOSE 8000
CMD ["uvicorn", "api:app", "--host", "0.0.0.0", "--port", "8000"]
