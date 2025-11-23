# Dockerfile content:
# Use a slim version of Python 3.11
FROM python:3.11-slim

# Set environment variable for unbuffered output
ENV PYTHONUNBUFFERED 1

# Install basic system dependencies (only needed for base image stability)
RUN apt-get update && \
    apt-get install -y git && \
    rm -rf /var/lib/apt/lists/*

# Set the working directory inside the container
WORKDIR /app

# Copy requirements file and install python packages
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy the rest of the application code
COPY . .

# Command to run your bot using the main file name
# IMPORTANT: Replace "your_mod_bot.py" with the exact name of your Python file.
CMD ["python", "Spam_Warden.py"]