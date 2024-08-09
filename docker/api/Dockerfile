# Stage 1: Build Stage
FROM python:3.12@sha256:c7862834f921957523cc4dab6d7795a7a0d19f1cd156c1ecd3a3a08c1108c9a4 AS app-base

# Set environment variables
ENV PYTHONDONTWRITEBYTECODE 1
ENV PYTHONUNBUFFERED 1

# Install system dependencies for building
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        # Add any necessary system dependencies here \
    && rm -rf /var/lib/apt/lists/*

# Install Poetry
RUN pip install poetry

# Set the working directory in the build stage
WORKDIR /app

# Copy only the pyproject.toml and poetry.lock files to leverage Docker cache
COPY ./apps/api/pyproject.toml ./apps/api/poetry.lock /app/

# Install dependencies
RUN poetry config virtualenvs.create false \
    && poetry install --no-dev --no-interaction --no-ansi

# Stage 2: Runtime Stage
FROM python:3.12-slim@sha256:105e9d85a67db1602e70fa2bbb49c1e66bae7e3bdcb6259344fe8ca116434f74 AS app-runtime

# Set environment variables
ENV PYTHONDONTWRITEBYTECODE 1
ENV PYTHONUNBUFFERED 1

# Copy installed dependencies from the build stage
COPY --from=app-base /usr/local/lib/python3.12/site-packages/ /usr/local/lib/python3.12/site-packages/
COPY --from=app-base /usr/local/bin/ /usr/local/bin/

# Set the working directory in the runtime stage
WORKDIR /app

# Copy application code
COPY ./apps/api/discovery /app/discovery

