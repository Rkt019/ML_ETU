#!/bin/bash
# start_frontend.sh — Run from the project root

set -e
cd "$(dirname "$0")/frontend"

echo "📦 Installing npm packages..."
npm install

echo ""
echo "🌐 Starting React dev server on http://localhost:3000 ..."
npm start
