# Build from the repo root: docker build -f webapp/Dockerfile .
# (docker-compose.yml's `webapp` service does this for you.)

FROM python:3.12-slim

WORKDIR /app

COPY webapp/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

# The canonical, unmodified Grader/db.py -- see webapp/data.py's module
# docstring for why this app imports it directly instead of forking it.
COPY Grader/db.py ./db.py
COPY webapp/ ./webapp/

EXPOSE 8080
CMD ["python", "-m", "webapp.main"]
