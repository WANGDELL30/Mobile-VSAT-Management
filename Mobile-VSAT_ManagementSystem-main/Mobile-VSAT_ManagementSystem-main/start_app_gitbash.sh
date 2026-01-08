#!/bin/bash

echo "=========================================="
echo "Starting Mobile VSAT Management System"
echo "=========================================="

# Get the script's directory
DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
cd "$DIR"

# Activate Virtual Environment
# We use the relative path ../../.venv as established
VENV_PATH="../../.venv"

if [ -f "$VENV_PATH/Scripts/activate" ]; then
    echo "Activating virtual environment..."
    source "$VENV_PATH/Scripts/activate"
else
    echo "Error: Virtual environment not found at $VENV_PATH"
    echo "Please run the setup first."
    read -p "Press Enter to exit..."
    exit 1
fi

echo ""
echo "Current Directory Contents:"
ls -l
echo ""

echo "Launching application..."
python main.py
