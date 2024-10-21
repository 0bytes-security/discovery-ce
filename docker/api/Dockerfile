# Stage 1: Build Stage
FROM python:3.13@sha256:a31cbb4db18c6f09e3300fa85b77f6d56702501fcb9bdb8792ec702a39ba6200 AS app-base

# Set environment variables
ENV PYTHONDONTWRITEBYTECODE 1
ENV PYTHONUNBUFFERED 1

# Install system dependencies for building
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        # Add any necessary system dependencies here \
    && rm -rf /var/lib/apt/lists/*

# Install Poetry
RUN pip install poetry==1.8.3
# Set the working directory in the build stage
WORKDIR /app

# Copy only the pyproject.toml and poetry.lock files to leverage Docker cache
COPY ./apps/api/pyproject.toml ./apps/api/poetry.lock /app/

# Install dependencies
RUN poetry config virtualenvs.create false \
    && poetry install --no-dev --no-interaction --no-ansi

# Stage 2: Runtime Stage
FROM app-base AS app-runtime

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

