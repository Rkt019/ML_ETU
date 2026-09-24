#!/bin/bash
# start_backend.sh — Run from the /backend directory

set -e
cd "$(dirname "$0")/backend"

echo "📦 Installing Python dependencies..."
pip install -r requirements.txt

echo ""
echo "🎬 Extracting head pose from teacher video (first-time only)..."
if [ ! -f "reference/reference.json" ]; then
  python services/extract_reference.py --video reference/teacher.mp4 --output reference/reference.json
else
  echo "   reference.json already exists — skipping extraction."
fi

echo ""
echo "🚀 Starting FastAPI server on http://localhost:8000 ..."
uvicorn main:app --host 0.0.0.0 --port 8000 --reload
