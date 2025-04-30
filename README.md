
# Project Title: Medicare – Intelligent Health Assistant Chatbot

## 1. Description / Objective

This project implements a multilingual, AI-powered healthcare chatbot that facilitates natural conversation with patients. It helps collect symptom information, performs intent recognition, asks follow-up health questions, and generates a professional summary of the patient's condition. The backend integrates speech input/output, translation, and a secure MongoDB-based record system.

---

## 2. Necessary Libraries / Installation Requirements

Install the required libraries by running:

```bash
pip install -r requirements.txt
```

Alternatively, manually install the libraries:

```bash
pip install torch transformers whisper gtts pygame pymongo langdetect reportlab deep-translator sounddevice
```

---

## 3. Commands to Run the Project

Copy and paste the following commands into your terminal:

```bash
# Step 1: Clone the repository
git clone https://github.com/Akshat-24057/Medicare_health_assistant.git

# Step 2: Navigate into the project directory
cd health-assistant-chatbot

# Step 3: Install dependencies
pip install -r requirements.txt

# Step 4: Run the chatbot
python chatbot.py
```

---

## 4. File Structure

```
health-assistant-chatbot/
│
├── README.md                   # Project overview and setup instructions
├── requirements.txt            # List of dependencies
├── chatbot.py                  # Main Python script for chatbot logic
├── knowledge_base.json         # Symptom definitions and structure
├── encryption_key.key          # Symmetric key used for encryption
├── reports/                    # Generated patient reports (PDF)
├── data/                       # Placeholder for input/output audio files
└── models/                     # Language model and Whisper integration
```

---

> **Note:** Ensure you have internet access for Hugging Face model loading and Google Translate APIs. Also, MongoDB must be running or accessible through the provided URI in the code.

Happy diagnosing! 💬🩺
