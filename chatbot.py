import whisper
import sounddevice as sd
from scipy.io.wavfile import write
import json
import os
import time
import sys
from reportlab.lib.pagesizes import letter, landscape
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph
from reportlab.lib import colors
import re
import hashlib
import getpass
from pymongo import MongoClient
from bson.objectid import ObjectId
from cryptography.fernet import Fernet
import base64
from gtts import gTTS
from langdetect import detect, detect_langs
import pygame
import torch
from transformers import AutoTokenizer, AutoModelForCausalLM, GenerationConfig
from llama_cpp import Llama


# MongoDB connection setup
client = MongoClient("mongodb+srv://Rap2006:Rap%402006@healthchatbot.ipyrc.mongodb.net/?retryWrites=true&w=majority&appName=HealthChatbot")
db = client["HealthChatbot"]
patient_collection = db["patients"]
doctor_collection = db["doctors"]
admin_collection = db["admins"]
conversation_choice = 1
language = 'en'
language_map = {
            "english": "en", "spanish": "es", "french": "fr", "german": "de",
            "italian": "it", "portuguese": "pt", "russian": "ru", "japanese": "ja",
            "chinese": "zh", "korean": "ko", "arabic": "ar", "hindi": "hi"
        }

lang_change = 0
supp_langs = ", ".join([lang for lang in language_map])



# Initialize whisper model for speech recognition
model = whisper.load_model("base")


model_name = "mradermacher/Mistral-Small-Sisyphus-24b-2503-i1-GGUF"

from huggingface_hub import login

login(token="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")


try:
    with open("knowledge_base.json", 'r') as f:
        knowledge_base  = json.load(f)
except:
    print("error loading symptoms!")

common_symptoms = knowledge_base['symptoms']
try:
    import subprocess
    import sys
    
    required_packages = ["transformers", "optimum", "auto-gptq", "ctransformers"]
    for package in required_packages:
        try:
            __import__(package)
        except ImportError:
            print(f"Installing required package: {package}")
            subprocess.check_call([sys.executable, "-m", "pip", "install", package])
    
    print("Loading LLM model...")
    
    from transformers import AutoTokenizer
    from ctransformers import AutoModelForCausalLM

    tokenizer = AutoTokenizer.from_pretrained("mistralai/Mistral-7B-v0.1")
    
    llm = AutoModelForCausalLM.from_pretrained(
        model_name,
        model_type="mistral",  # Specify model architecture
        gpu_layers=50,         # Offload as many layers as possible to GPU
        context_length=4096,   # Maximum context length
    )
    
    print("LLM model loaded successfully!")
    use_llm = True
    
except Exception as e:
    print(f"Error loading Mistral model: {e}")
    print("Falling back to simpler health assistant questions...")
    use_llm = False


def out(text):
    """Output text and optionally speak it."""
    try:
        from deep_translator import GoogleTranslator
        text = GoogleTranslator(source='auto', target=language).translate(text)
    except:
        pass
    print(text)
    if conversation_choice == 1:
        try:
            if os.path.exists("output.mp3"):
                os.remove("output.mp3")
            tts = gTTS(text)
            tts.save("output.mp3")
            pygame.mixer.init()
            pygame.mixer.music.load("output.mp3")
            pygame.mixer.music.play()
            while pygame.mixer.music.get_busy():
                time.sleep(0.5)
            pygame.mixer.quit()
            time.sleep(0.5)
        except Exception as e:
            print(f"Speech output failed: {e}")

def input_text(exp="YOU :", speech=0, detect_lang=0):
    """Get input from user via text or speech with improved language detection."""
    global language, lang_change
    
    if conversation_choice == 1 and speech:
        txt = speech_input().strip().lower()
    else:
        txt = input(exp).strip().lower()
    
    if "change language" in txt:
        lang_change = 1
        print(f"Chatbot : Enter langauge ({supp_langs})")
        requested_lang = input("YOU : ")
        
        if requested_lang in language_map:
            language = language_map[requested_lang]
            out(f"Language changed to {requested_lang.capitalize()}.")
            # Ask the previous question again
            return "LANGUAGE_CHANGE"
        else:
            out("I don't recognize that language. Continuing in current language.")
    
    # Normal language detection and translation
    try:
        if detect_lang and ("change language" not in txt):
            detected = detect_langs(txt)[0]
            if detected.lang != language and detected.prob>0.9:
                # out(f"I noticed you're typing in a different language. Switching to that language.")
                language = detected
    except Exception as e:
        pass
    
    try:
        from deep_translator import GoogleTranslator
        if "change language" not in txt:
            return GoogleTranslator(source='auto', target='en').translate(txt)
        else:
            return txt
    except Exception as e:
        return txt



def speech_input():
    """Record and transcribe user's speech."""
    fs = 44100  # Higher sample rate for better quality
    seconds = 5
    filename = "input.wav"
    
    out("🎤 Recording your input...")
    try:
        # Record audio
        audio = sd.rec(int(seconds * fs), samplerate=fs, channels=1, dtype='int16')
        sd.wait()  # Wait until recording is finished
        
        # Save as WAV file
        write(filename, fs, audio)
        
        # Load and process with Whisper
        audio = whisper.load_audio(filename)
        audio = whisper.pad_or_trim(audio)
        mel = whisper.log_mel_spectrogram(audio).to(model.device)
        
        # Detect language
        _, probs = model.detect_language(mel)
        global language
        language = max(probs, key=probs.get)
        
        # Decode the audio
        options = whisper.DecodingOptions(language=language, fp16=False)
        result = whisper.decode(model, mel, options)
        
        out(f"YOU: {result.text}")
        return result.text
        
    except Exception as e:
        out(f"Error in speech input: {e}")
        return input("Fallback to text input: ")  # Fallback if speech fails

# Encryption key setup and functions
def get_encryption_key():
    """Get or create encryption key."""
    key_file = "encryption_key.key"
    try:
        # Try to load existing key
        with open(key_file, "rb") as f:
            key = f.read()
    except FileNotFoundError:
        # Generate a new key if none exists
        key = Fernet.generate_key()
        with open(key_file, "wb") as f:
            f.write(key)
    
    return key

# Initialize Fernet with our key
cipher_suite = Fernet(get_encryption_key())

# User Authentication Functions
def hash_password(password):
    """Create a SHA-256 hash of the password."""
    return hashlib.sha256(password.encode()).hexdigest()

def verify_password(stored_hash, provided_password):
    """Verify a stored password hash against a provided password."""
    return stored_hash == hash_password(provided_password)

# Encryption functions
def encrypt_data(data_string):
    """Encrypt a string using Fernet (AES)."""
    if not data_string:
        return data_string
    encrypted_data = cipher_suite.encrypt(data_string.encode('utf-8'))
    return base64.b64encode(encrypted_data).decode('utf-8')

def decrypt_data(encrypted_data):
    """Decrypt a string that was encrypted with Fernet."""
    if not encrypted_data:
        return encrypted_data
    decrypted_data = cipher_suite.decrypt(base64.b64decode(encrypted_data.encode('utf-8')))
    return decrypted_data.decode('utf-8')

# Helper function to encrypt nested dictionaries
def encrypt_dict(data_dict):
    """Recursively encrypt values in a dictionary."""
    encrypted_dict = {}
    for key, value in data_dict.items():
        if isinstance(value, dict):
            encrypted_dict[key] = encrypt_dict(value)
        elif isinstance(value, list):
            # Handle lists (for symptoms severity)
            encrypted_dict[key] = [encrypt_data(item) if isinstance(item, str) else item for item in value]
        elif isinstance(value, str):
            encrypted_dict[key] = encrypt_data(value)
        else:
            encrypted_dict[key] = value
    return encrypted_dict

# Helper function to decrypt nested dictionaries
def decrypt_dict(encrypted_dict):
    """Recursively decrypt values in a dictionary."""
    decrypted_dict = {}
    for key, value in encrypted_dict.items():
        if isinstance(value, dict):
            decrypted_dict[key] = decrypt_dict(value)
        elif isinstance(value, list):
            # Handle lists (for symptoms severity)
            decrypted_dict[key] = [decrypt_data(item) if isinstance(item, str) else item for item in value]
        elif isinstance(value, str):
            try:
                decrypted_dict[key] = decrypt_data(value)
            except Exception:
                # If decryption fails (might not be encrypted), keep original
                decrypted_dict[key] = value
        else:
            decrypted_dict[key] = value
    return decrypted_dict

# LLM utility functions for health conversation
def get_llm_response(prompt):
    """Get a response from the Mistral model using ctransformers."""
    if not use_llm:
        return "I'm sorry, but I cannot provide personalized health information as the LLM model is not available."
    
    try:
        # Create a chat format that the model understands
        system_prompt = "You are a warm, empathetic healthcare assistant that helps patients. Be professional but approachable. Respond in the same language as the user's query."
        
        # Format the prompt with system instruction and user query
        formatted_prompt = f"""<|im_start|>system
{system_prompt}
<|im_end|>
<|im_start|>user
{prompt}
<|im_end|>
<|im_start|>assistant
"""
        
        # Generate response
        generated_text = llm(
            formatted_prompt,
            max_new_tokens=500,
            temperature=0.7,
            top_p=0.95,
            stop=["<|im_end|>"]
        )
        
        # Extract just the model's response part
        response = generated_text.split("<|im_start|>assistant")[-1].strip()
        response = response.split("<|im_end|>")[0].strip() if "<|im_end|>" in response else response
        
        return response
    except Exception as e:
        print(f"Error getting LLM response: {e}")
        return "I apologize, but I'm having trouble generating a response. Let's continue with our health assessment."


def ask_follow_up_questions(symptom, patient_data):
    global lang_change
    """Generate and ask follow-up questions about a symptom using the Mistral model."""
    # Create a prompt that instructs the model to generate follow-up questions
    prompt = f"""
You are a healthcare assistant collecting information about a patient's symptoms.
The patient has mentioned experiencing: {symptom}

Generate 4 specific follow-up questions that would help gather important clinical information about this symptom.
Include questions about:
1. Duration (how long they've had this symptom)
2. Severity (how intense or disruptive it is)
3. Frequency (how often it occurs)
4. Associated factors (what makes it better or worse)

Format your response as a numbered list of questions only. No introduction or explanation text.
"""
    
    # Get follow-up questions from the model
    if use_llm:
        follow_up_questions = get_llm_response(prompt)
        
        # Extract questions from the response
        # First, try to extract numbered questions using regex
        questions = re.findall(r'^\s*\d+\.\s*(.*?)(?=^\s*\d+\.|\Z)', follow_up_questions, re.MULTILINE | re.DOTALL)
        
        # If that doesn't work well, try line by line approach
        if not questions or len(questions) < 2:
            lines = follow_up_questions.strip().split('\n')
            questions = []
            for line in lines:
                line = line.strip()
                if re.match(r'^\d+\.', line):
                    questions.append(re.sub(r'^\d+\.\s*', '', line))
        
        # If we still don't have good questions, fallback to default
        if not questions or len(questions) < 2:
            questions = [
                f"How long have you been experiencing {symptom}?",
                f"On a scale of 1-10, how would you rate the severity of your {symptom}?",
                f"How frequently do you experience {symptom}?",
                f"Have you noticed anything that triggers or worsens your {symptom}?"
            ]
    else:
        # Fallback questions if model is not available
        questions = [
            f"How long have you been experiencing {symptom}?",
            f"On a scale of 1-10, how would you rate the severity of your {symptom}?",
            f"How frequently do you experience {symptom}?",
            f"Have you noticed anything that triggers or worsens your {symptom}?"
        ]
    
    # Ask each follow-up question and collect responses
    symptom_data = {}
    le = len(questions)
    i=0
    while i<le:
        question = questions[i]
        out(f"Health Assistant: {question}")
        response = input_text(speech=1, detect_lang=1)
        if lang_change:
            lang_change=0
            continue
        i += 1
        # # Handle language change requests
        # while response == "LANGUAGE_CHANGE":
        #     # Ask the question again in the new language
        #     translated_question = question
        #     try:
        #         from deep_translator import GoogleTranslator
        #         translated_question = GoogleTranslator(source='en', target=language).translate(question)
        #     except Exception as e:
        #         print(f"Translation error: {e}")
            
        #     out(f"Health Assistant: {translated_question}")
        #     response = input_text(speech=1, detect_lang=1)
        
        # Determine what category this question belongs to
        if re.search(r'(how long|duration|when.*start|since when)', question.lower()):
            symptom_data["Duration"] = response
        elif re.search(r'(severity|scale|rate|intense|bad|disrupt)', question.lower()):
            symptom_data["Severity"] = response
        elif re.search(r'(how often|frequency)', question.lower()):
            symptom_data["Frequency"] = response
        elif re.search(r'(trigger|worse|better|improve|alleviate)', question.lower()):
            symptom_data["Factors"] = response
        else:
            # For questions that don't fit into our predefined categories
            key = "Additional Notes"
            if key not in symptom_data:
                symptom_data[key] = response
            else:
                symptom_data[key] += f"; {response}"
    

    while True:
        # Ask for any additional information
        additional_prompt = f"Is there anything else you'd like to share about your {symptom} that I haven't asked about?"
        try:
            from deep_translator import GoogleTranslator
            translated_prompt = GoogleTranslator(source='en', target=language).translate(additional_prompt)
            out(f"Health Assistant: {translated_prompt}")
        except:
            out(f"Health Assistant: {additional_prompt}")
            
        additional_info = input_text(speech=1, detect_lang=1)
        
        if lang_change:
            lang_change=0
            continue

        # # Handle language change request
        # while additional_info == "LANGUAGE_CHANGE":
        #     try:
        #         from deep_translator import GoogleTranslator
        #         translated_prompt = GoogleTranslator(source='en', target=language).translate(additional_prompt)
        #         out(f"Health Assistant: {translated_prompt}")
        #     except:
        #         out(f"Health Assistant: {additional_prompt}")
        #     additional_info = input_text(speech=1, detect_lang=1)

        if additional_info and additional_info.lower() not in ["no", "not really", "nothing else"]:
            if "Additional Notes" not in symptom_data:
                symptom_data["Additional Notes"] = additional_info
            else:
                symptom_data["Additional Notes"] += f"; {additional_info}"
        break
    
    return symptom_data



def summarize_patient_condition(patient_data):
    """Use the Mistral model to generate a brief summary of the patient's condition."""
    if not use_llm:
        return ""
    
    # Create a structured summary of the patient's symptoms
    symptom_summary = ""
    for symptom, details in patient_data["per_symptom"].items():
        symptom_summary += f"\n- {symptom}:\n"
        for key, value in details.items():
            symptom_summary += f"  * {key}: {value}\n"
    
    general_health = ""
    for question, answer in patient_data["Gen_questions"].items():
        general_health += f"- {question}: {answer}\n"
    
    prompt = f"""
You are a healthcare professional summarizing a patient's condition based on the following information.
Provide a concise summary of the patient's health status that highlights key concerns. Be factual and clinical without diagnosing.

Patient Demographics:
{patient_data["demographic"]}

Reported Symptoms:
{symptom_summary}

General Health Information:
{general_health}

Create a brief professional summary (3-5 sentences) that highlights the key health concerns, potential patterns, and important factors.
"""
    
    summary = get_llm_response(prompt)
    
    # Clean up the summary
    # Remove any preamble text like "Here is a summary:" or "Patient Summary:"
    summary = re.sub(r'^.*?(summary|assessment).*?:\s*', '', summary, flags=re.IGNORECASE|re.DOTALL)
    
    # Remove any concluding notes like "Note:" or "Remember:"
    summary = re.sub(r'(note|remember|please).*$', '', summary, flags=re.IGNORECASE|re.DOTALL)
    
    return summary.strip()


def identify_symptoms_from_text(text):
    global common_symptoms
    """Use the Mistral model to identify potential symptoms from free text."""
    if not use_llm:
        found_symptoms = [symptom for symptom in common_symptoms if symptom in text.lower()]
        return found_symptoms
    
    prompt = f"""
You are a healthcare assistant identifying symptoms from a patient's description.

Patient statement: "{text}"

Identify all possible symptoms mentioned in the patient's statement. 
List each symptom as a single word or short phrase.
Only include actual symptoms, not diagnoses or conditions.
Format your response as a comma-separated list without numbering, explanations, or any other text.
"""
    
    response = get_llm_response(prompt)
    
    # Process the response to extract symptoms
    # First, clean up the response
    response = response.strip()
    
    # Try different parsing approaches to extract symptoms reliably
    # Method 1: Look for comma-separated items
    if "," in response:
        symptoms = [s.strip() for s in response.split(",") if s.strip()]
    # Method 2: Look for line breaks
    elif "\n" in response:
        symptoms = [s.strip() for s in response.split("\n") if s.strip()]
        # Remove any numbering or bullet points
        symptoms = [re.sub(r'^[\d\-•*]+\.?\s*', '', s) for s in symptoms]
    # Method 3: If still not parsed, use the whole response
    else:
        symptoms = [response]
    
    # Filter out any lines that look like instructions or clarifications
    symptoms = [s for s in symptoms if not re.search(r'^(note|here|the following|symptoms include)', s.lower())]
    
    # If still no symptoms, fallback to keyword matching
    if not symptoms:
        common_symptoms = [
            "headache", "fever", "cough", "fatigue", "pain", "nausea", 
            "dizziness", "rash", "vomiting", "diarrhea", "breathing difficulty"
        ]
        found_symptoms = [symptom for symptom in common_symptoms if symptom.lower() in text.lower()]
        return found_symptoms
    
    return symptoms


def generate_general_health_questions():
    """Generate general health questions using the Mistral model."""
    if not use_llm:
        # Fallback to basic questions
        return [
            "Do you have any chronic health conditions?",
            "Are you currently taking any medications?",
            "Have you had any surgeries in the past?",
            "Do you have any allergies?",
            "How would you describe your overall health?"
        ]
    
    prompt = """
You are a healthcare assistant conducting an initial patient assessment.

Please generate 5 important general health questions that would help understand a patient's overall health status.
Include questions about:
- Medical history
- Medications
- Lifestyle factors
- Family history
- General wellbeing

Format your response as a numbered list of questions only. No introduction or explanation text.
"""
    
    response = get_llm_response(prompt)
    
    # Extract just the questions
    questions = []
    
    # Method 1: Try to extract numbered questions
    numbered_questions = re.findall(r'^\s*\d+\.\s*(.*?)(?=^\s*\d+\.|\Z)', response, re.MULTILINE | re.DOTALL)
    if numbered_questions and len(numbered_questions) >= 3:
        questions = [q.strip() for q in numbered_questions]
    
    # Method 2: Try line by line
    if not questions or len(questions) < 3:
        lines = response.strip().split('\n')
        questions = []
        for line in lines:
            line = line.strip()
            if re.match(r'^\d+\.', line) and '?' in line:
                questions.append(re.sub(r'^\d+\.\s*', '', line))
    
    # Method 3: Just split by question marks
    if not questions or len(questions) < 3:
        question_parts = response.split('?')
        questions = [q.strip() + '?' for q in question_parts if q.strip()]
    
    # Ensure we have at least some questions if parsing fails
    if not questions or len(questions) < 3:
        questions = [
            "Do you have any chronic health conditions?",
            "Are you currently taking any medications?",
            "Have you had any surgeries in the past?",
            "Do you have any allergies?",
            "How would you describe your overall health?"
        ]
    
    # Limit to 5 questions
    return questions[:5]


def generate_report(collected_data):
    """Generate a PDF report from the collected patient data."""
    file_name = f"{collected_data['demographic']['name']}_Diagnosis_Report.pdf"
    doc = SimpleDocTemplate(file_name, pagesize=landscape(letter))

    styles = getSampleStyleSheet()
    normal_style = styles['Normal']
    header_style = ParagraphStyle(
        'HeaderStyle',
        parent=styles['Heading1'],
        fontSize=14,
        spaceAfter=30
    )

    story = []
    title = Paragraph("PATIENT SCREENING REPORT", header_style)
    story.append(title)

    # Patient details section
    story.append(Paragraph("Patient Details", styles['Heading2']))
    details_data = [[Paragraph("Field", styles['Heading3']), Paragraph("Information", styles['Heading3'])]]
    for label, data in collected_data["demographic"].items():
        details_data.append([
            Paragraph(label, normal_style),
            Paragraph(str(data), normal_style)
        ])

    details_table = Table(details_data, colWidths=[200, 400])
    details_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.grey),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
        ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, 0), 12),
        ('BOTTOMPADDING', (0, 0), (-1, 0), 12),
        ('GRID', (0, 0), (-1, -1), 1, colors.black),
        ('PADDING', (0, 0), (-1, -1), 6),
    ]))
    story.append(details_table)
    story.append(Paragraph("<br/><br/>", normal_style))

    # Add AI generated summary if available
    if "summary" in collected_data and collected_data["summary"]:
        story.append(Paragraph("Summary Assessment", styles['Heading2']))
        story.append(Paragraph(collected_data["summary"], normal_style))
        story.append(Paragraph("<br/><br/>", normal_style))

    # Symptoms summary section
    story.append(Paragraph("Symptoms Summary", styles['Heading2']))
    symptoms_table_data = [[
        Paragraph("Symptom", styles['Heading3']),
        Paragraph("Frequency", styles['Heading3']),
        Paragraph("Severity", styles['Heading3']),
        Paragraph("Duration", styles['Heading3']),
        Paragraph("Additional Notes", styles['Heading3'])
    ]]

    for symptom, details in collected_data["per_symptom"].items():
        row = [
            Paragraph(str(symptom), normal_style),
            Paragraph(str(details.get("Frequency", "N/A")), normal_style),
            Paragraph(str(details.get("Severity", "N/A")), normal_style),
            Paragraph(str(details.get("Duration", "N/A")), normal_style),
            Paragraph(str(details.get("Additional Notes", "N/A")), normal_style)
        ]
        symptoms_table_data.append(row)

    symptoms_table = Table(symptoms_table_data, colWidths=[140, 140, 140, 140, 140])
    symptoms_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.grey),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
        ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, 0), 12),
        ('BOTTOMPADDING', (0, 0), (-1, 0), 12),
        ('GRID', (0, 0), (-1, -1), 1, colors.black),
        ('PADDING', (0, 0), (-1, -1), 6),
    ]))
    story.append(symptoms_table)
    story.append(Paragraph("<br/><br/>", normal_style))

    # General health questions section
    story.append(Paragraph("General Health Information", styles['Heading2']))
    gen_questions_table_data = [[
        Paragraph("Question", styles['Heading3']),
        Paragraph("Answer", styles['Heading3'])
    ]]

    for question, answer in collected_data["Gen_questions"].items():
        gen_questions_table_data.append([
            Paragraph(str(question), normal_style),
            Paragraph(str(answer), normal_style)
        ])

    gen_questions_table = Table(gen_questions_table_data, colWidths=[350, 350])
    gen_questions_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.grey),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
        ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, 0), 12),
        ('BOTTOMPADDING', (0, 0), (-1, 0), 12),
        ('GRID', (0, 0), (-1, -1), 1, colors.black),
        ('PADDING', (0, 0), (-1, -1), 6),
    ]))
    story.append(gen_questions_table)

    doc.build(story)
    out(f"Report saved as {file_name}")

    # Ask for a password for the patient
    out("Please set a password for accessing your health records:")
    password = getpass.getpass("Password: ")
    confirm_password = getpass.getpass("Confirm Password: ")
    
    while password != confirm_password:
        out("Passwords do not match. Please try again.")
        password = getpass.getpass("Password: ")
        confirm_password = getpass.getpass("Confirm Password: ")
    
    # Encrypt data before saving to MongoDB
    encrypted_data = {
        "demographic": encrypt_dict(collected_data["demographic"]),
        "per_symptom": encrypt_dict(collected_data["per_symptom"]),
        "Gen_questions": encrypt_dict(collected_data["Gen_questions"]),
        "password": hash_password(password),  # Store hashed password
        "created_at": time.time()
    }
    
    # Add summary if available
    if "summary" in collected_data and collected_data["summary"]:
        encrypted_data["summary"] = encrypt_data(collected_data["summary"])
    
    # Save encrypted data to MongoDB
    patient_collection.insert_one(encrypted_data)
    out("✅ Patient data saved to MongoDB in encrypted form.")

def collect_data():
    global lang_change
    """
    Main function to collect patient data using the LLM for dynamic health conversations.
    This replaces the original hard-coded question flow with dynamic LLM-generated conversations.
    """
    collected_data = {"demographic": {}, "per_symptom": {}, "Gen_questions": {}}
    
    # Welcome the patient with a warm AI-generated introduction
    welcome_prompt = """
    You are an empathetic healthcare virtual assistant conducting an initial patient interview.
    Write a brief, warm welcome message (3-4 sentences) introducing yourself to a new patient.
    Explain that you'll be asking about their health concerns and symptoms to provide better care.
    Use simple, friendly language and be reassuring. Do not diagnose or give medical advice.
    """
    
    welcome_message = "Welcome to our health assessment. I'm your virtual health assistant and I'll be asking you some questions about your health concerns to better understand your situation." if not use_llm else get_llm_response(welcome_prompt)
    
    out(f"Health Assistant: {welcome_message}")
    
    # Collect basic demographic information
    out("Health Assistant: Let's start with some basic information about you.")
    
    # Define the demographic fields we need
    demographic_fields = {
        "name": "What is your full name?",
        "age": "What is your age?",
        "gender": "What is your gender?",
        "email": "What is your email address? This will be used for login purposes.",
        "phone": "What is your phone number?"
    }


    # Collect demographic information
    ques = list(demographic_fields.items())
    le = len(ques)
    i=0
    while i<le:
        field, question = ques[i]
        out(f"Health Assistant: {question}")
        user_input = input_text()
        if lang_change:
            lang_change = 0
            continue
        if user_input.lower() in ["exit", "exit."]:
            return 0
        collected_data["demographic"][field] = user_input
        i += 1
    
    while True:
        # Collect chief complaints/symptoms
        out("Health Assistant: Now, please tell me about your symptoms or health concerns. What brings you in today?")
        
        chief_complaint = input_text(speech=1, detect_lang=1)
        if lang_change:
            lang_change=0
            continue
        if chief_complaint.lower() in ["exit", "exit."]:
            return 0
        break
        
    # Use the LLM to identify symptoms from the patient's description
    identified_symptoms = identify_symptoms_from_text(chief_complaint)
    while True:
        if not identified_symptoms:
            out("Health Assistant: I didn't catch any specific symptoms. Could you please describe what you're experiencing again?")
            additional_info = input_text(speech=1, detect_lang=1)
            if lang_change:
                lang_change=0
                continue
            if additional_info.lower() in ["exit", "exit."]:
                return 0
            identified_symptoms = identify_symptoms_from_text(additional_info)
        break
    
    # Confirm identified symptoms with the patient
    if identified_symptoms:
        symptom_list = ", ".join(identified_symptoms)
        out(f"Health Assistant: I understand you're experiencing {symptom_list}. Is that correct?")
        confirmation = input_text(speech=1)
        
        if confirmation.lower() not in ["yes", "yes.", "correct", "that's right", "yeah"]:
            out("Health Assistant: I apologize for misunderstanding. Could you please clarify your symptoms?")
            new_symptoms = input_text(speech=1, detect_lang=1)
            if new_symptoms.lower() in ["exit", "exit."]:
                return 0
            identified_symptoms = identify_symptoms_from_text(new_symptoms)
    
    # Check if we still don't have any symptoms
    if not identified_symptoms:
        out("Health Assistant: Let me ask more specifically. What symptoms or health issues are you experiencing right now?")
        direct_symptoms = input_text(speech=1, detect_lang=1)
        if direct_symptoms.lower() in ["exit", "exit."]:
            return 0
        identified_symptoms = identify_symptoms_from_text(direct_symptoms)
        
        # If still no symptoms, add a generic entry
        if not identified_symptoms:
            identified_symptoms = ["general health concern"]
    
    # For each identified symptom, ask follow-up questions using the LLM
    le = len(identified_symptoms)
    i=0
    while i<le:
        symptom = identified_symptoms[i]
        out(f"Health Assistant: Let's talk more about your {symptom}.")
        symptom_details = ask_follow_up_questions(symptom, collected_data)
        collected_data["per_symptom"][symptom] = symptom_details
        i+=1
    
    # Ask general health questions generated by the LLM
    out("Health Assistant: Now I'd like to ask some general questions about your health.")
    general_questions = generate_general_health_questions()
    
    le = len(general_questions)
    i=0
    while i<le:
        question = general_questions[i]
        out(f"Health Assistant: {question}")
        answer = input_text(speech=1, detect_lang=1)
        if answer.lower() in ["exit", "exit."]:
            return 0
        if lang_change:
            lang_change=0
            continue
        collected_data["Gen_questions"][question] = answer
        i+=1
    
    # Generate a summary of the patient's condition if using LLM
    if use_llm:
        out("Health Assistant: Thank you for providing all this information. Let me generate a brief summary of your health assessment.")
        summary = summarize_patient_condition(collected_data)
        collected_data["summary"] = summary
        
        # Share the summary with the patient
        out(f"Health Assistant: Based on the information you've provided, here's a brief summary:\n{summary}")
        out("Health Assistant: Is there anything else you'd like to add or correct about this summary?")
        
        additional_feedback = input_text(speech=1, detect_lang=1)
        if additional_feedback.lower() not in ["no", "that's correct", "looks good", "no, thank you"]:
            # Add the feedback to our notes
            collected_data["patient_feedback"] = additional_feedback
    
    # Create the patient report and save to MongoDB
    out("Health Assistant: Thank you for sharing all this information. I'll now generate your health assessment report.")
    generate_report(collected_data)
    
    # Final message
    closing_prompt = """
    You are a warm, empathetic healthcare assistant finishing a patient assessment.
    Write a brief closing message (2-3 sentences) thanking the patient for their time.
    Remind them that this assessment is not a diagnosis and they should consult with a healthcare professional.
    Be professional but caring.
    """
    
    closing_message = "Thank you for completing this health assessment. Remember that this is not a diagnosis, and you should follow up with a healthcare professional. Take care!" if not use_llm else get_llm_response(closing_prompt)
    
    out(f"Health Assistant: {closing_message}")
    return 1


def patient_login():
    """Patient login function."""
    out("\n🔒 Patient Login")
    email = input_text("Enter your email: ")
    password = getpass.getpass("Enter your password: ")
    
    # Find the patient by email (need to search through encrypted data)
    found_patient = None
    
    for patient in patient_collection.find():
        try:
            decrypted_demographic = decrypt_dict(patient.get("demographic", {}))
            if "email" in decrypted_demographic and decrypted_demographic["email"].lower() == email.lower():
                found_patient = patient
                break
        except Exception as e:
            continue  # Skip any records that can't be decrypted
    
    if not found_patient:
        out("❌ No account found with that email.")
        return None
        
    # Check password
    if verify_password(found_patient.get("password", ""), password):
        out("✅ Login successful!")
        return found_patient
    else:
        out("❌ Incorrect password.")
        return None

def patient_menu(patient_doc):
    """Menu for patient access."""
    # Decrypt patient data for display
    decrypted_patient = {
        "_id": patient_doc["_id"],
        "demographic": decrypt_dict(patient_doc["demographic"]),
        "per_symptom": decrypt_dict(patient_doc["per_symptom"]),
        "Gen_questions": decrypt_dict(patient_doc["Gen_questions"])
    }
    
    # Decrypt summary if available
    if "summary" in patient_doc:
        try:
            decrypted_patient["summary"] = decrypt_data(patient_doc["summary"])
        except:
            decrypted_patient["summary"] = ""
    
    while True:
        out("\n👤 Patient Portal")
        out(f"Welcome, {decrypted_patient['demographic'].get('name', 'Patient')}!")
        out("\n1. View My Profile")
        out("2. View My Health Records")
        out("3. Update My Information")
        out("4. Change Password")
        out("5. Log Out")
        
        choice = input_text("Enter choice: ")
        
        if choice == '1':
            out("\n📋 Your Profile Information")
            for key, value in decrypted_patient["demographic"].items():
                out(f"{key.capitalize()}: {value}")
                
        elif choice == '2':
            out("\n🩺 Your Health Records")
            
            # Display summary if available
            if "summary" in decrypted_patient and decrypted_patient["summary"]:
                out("\nSummary Assessment:")
                out(decrypted_patient["summary"])
            
            out("\nSymptoms:")
            for symptom, details in decrypted_patient["per_symptom"].items():
                out(f"\n{symptom.upper()}:")
                for key, value in details.items():
                    out(f"  - {key}: {value}")
            
            out("\nGeneral Health Information:")
            for question, answer in decrypted_patient["Gen_questions"].items():
                out(f"Q: {question}")
                out(f"A: {answer}\n")
                
        elif choice == '3':
            # Update patient information
            update_patient_info(patient_doc, decrypted_patient)
            
            # Refresh the decrypted patient data after update
            patient_doc = patient_collection.find_one({"_id": patient_doc["_id"]})
            decrypted_patient = {
                "_id": patient_doc["_id"],
                "demographic": decrypt_dict(patient_doc["demographic"]),
                "per_symptom": decrypt_dict(patient_doc["per_symptom"]),
                "Gen_questions": decrypt_dict(patient_doc["Gen_questions"])
            }
            if "summary" in patient_doc:
                try:
                    decrypted_patient["summary"] = decrypt_data(patient_doc["summary"])
                except:
                    decrypted_patient["summary"] = ""
                
        elif choice == '4':
            current_password = getpass.getpass("Enter current password: ")
            
            # Verify current password
            if verify_password(patient_doc.get("password", ""), current_password):
                new_password = getpass.getpass("Enter new password: ")
                confirm_password = getpass.getpass("Confirm new password: ")
                
                if new_password == confirm_password:
                    # Update password in database
                    patient_collection.update_one(
                        {"_id": patient_doc["_id"]},
                        {"$set": {"password": hash_password(new_password)}}
                    )
                    out("✅ Password updated successfully!")
                else:
                    out("❌ Passwords do not match.")
            else:
                out("❌ Incorrect current password.")
                
        elif choice == '5':
            out("Logging out...")
            break
        else:
            out("Invalid choice. Please try again.")

def update_patient_info(patient_doc, decrypted_patient):
    """Allow patient to update their information."""
    while True:
        out("\n🔄 Update My Information")
        out("1. Update Profile Information")
        out("2. Update Symptom Details")
        out("3. Update General Health Information")
        out("4. Back to Main Menu")
        
        update_choice = input_text("Enter choice: ")
        
        if update_choice == '1':
            # Update demographic information
            update_demographic(patient_doc, decrypted_patient)
            
        elif update_choice == '2':
            # Update symptom information
            update_symptoms(patient_doc, decrypted_patient)
            
        elif update_choice == '3':
            # Update general health information
            update_general_health(patient_doc, decrypted_patient)
            
        elif update_choice == '4':
            out("Returning to main menu...")
            break
            
        else:
            out("Invalid choice. Please try again.")

def update_demographic(patient_doc, decrypted_patient):
    """Update patient demographic information."""
    demographic = decrypted_patient["demographic"]
    
    out("\n👤 Current Profile Information:")
    field_options = []
    for i, (key, value) in enumerate(demographic.items(), 1):
        out(f"{i}. {key.capitalize()}: {value}")
        field_options.append(key)
    
    field_choice = input_text("\nEnter the number of the field to update (or 0 to cancel): ")
    
    if field_choice == '0' or not field_choice.isdigit():
        out("Operation canceled.")
        return
        
    field_idx = int(field_choice) - 1
    if field_idx < 0 or field_idx >= len(field_options):
        out("Invalid option selected.")
        return
        
    field_to_update = field_options[field_idx]
    
    # Email requires special validation
    if field_to_update.lower() == "email":
        new_value = input_text(f"Enter new email (current: {demographic[field_to_update]}): ")
        
        # Check if email is already in use by another patient
        for patient in patient_collection.find({"_id": {"$ne": patient_doc["_id"]}}):
            try:
                other_demographic = decrypt_dict(patient.get("demographic", {}))
                if "email" in other_demographic and other_demographic["email"].lower() == new_value.lower():
                    out("❌ This email is already in use by another account.")
                    return
            except Exception as e:
                continue  # Skip any records that can't be decrypted
    else:
        new_value = input_text(f"Enter new value for {field_to_update} (current: {demographic[field_to_update]}): ")
    
    if not new_value.strip():
        out("❌ Value cannot be empty.")
        return
        
    # Update the specific field
    updated_demographic = decrypted_patient["demographic"].copy()
    updated_demographic[field_to_update] = new_value
    
    # Encrypt and save to database
    encrypted_demographic = encrypt_dict(updated_demographic)
    patient_collection.update_one(
        {"_id": patient_doc["_id"]},
        {"$set": {"demographic": encrypted_demographic}}
    )
    
    out(f"✅ {field_to_update.capitalize()} updated successfully!")

def update_symptoms(patient_doc, decrypted_patient):
    """Update patient symptom information."""
    symptoms = decrypted_patient["per_symptom"]
    
    if not symptoms:
        out("You don't have any recorded symptoms to update.")
        return
        
    out("\n🩺 Your Symptoms:")
    symptom_list = list(symptoms.keys())
    for i, symptom in enumerate(symptom_list, 1):
        out(f"{i}. {symptom}")
    
    symptom_choice = input_text("\nEnter the number of the symptom to update (or 0 to cancel): ")
    
    if symptom_choice == '0' or not symptom_choice.isdigit():
        out("Operation canceled.")
        return
        
    symptom_idx = int(symptom_choice) - 1
    if symptom_idx < 0 or symptom_idx >= len(symptom_list):
        out("Invalid option selected.")
        return
        
    symptom_to_update = symptom_list[symptom_idx]
    symptom_details = symptoms[symptom_to_update]
    
    out(f"\nDetails for '{symptom_to_update}':")
    detail_keys = list(symptom_details.keys())
    for i, (key, value) in enumerate(symptom_details.items(), 1):
        out(f"{i}. {key}: {value}")
    
    detail_choice = input_text("\nEnter the number of the detail to update (or 0 to cancel): ")
    
    if detail_choice == '0' or not detail_choice.isdigit():
        out("Operation canceled.")
        return
        
    detail_idx = int(detail_choice) - 1
    if detail_idx < 0 or detail_idx >= len(detail_keys):
        out("Invalid option selected.")
        return
        
    detail_to_update = detail_keys[detail_idx]
    new_value = input_text(f"Enter new value for {detail_to_update} (current: {symptom_details[detail_to_update]}): ")
    
    # Update the specific symptom detail
    updated_symptoms = decrypted_patient["per_symptom"].copy()
    updated_symptoms[symptom_to_update][detail_to_update] = new_value
    
    # Get updated summary if LLM is available
    if use_llm and "summary" in decrypted_patient:
        # Create a temporary data structure with updated info
        temp_data = {
            "demographic": decrypted_patient["demographic"],
            "per_symptom": updated_symptoms,
            "Gen_questions": decrypted_patient["Gen_questions"]
        }
        new_summary = summarize_patient_condition(temp_data)
    else:
        new_summary = decrypted_patient.get("summary", "")
    
    # Encrypt and save to database
    encrypted_symptoms = encrypt_dict(updated_symptoms)
    update_dict = {"per_symptom": encrypted_symptoms}
    
    if new_summary:
        update_dict["summary"] = encrypt_data(new_summary)
    
    patient_collection.update_one(
        {"_id": patient_doc["_id"]},
        {"$set": update_dict}
    )
    
    out(f"✅ {detail_to_update} for {symptom_to_update} updated successfully!")

def update_general_health(patient_doc, decrypted_patient):
    """Update patient general health information."""
    gen_questions = decrypted_patient["Gen_questions"]
    
    if not gen_questions:
        out("You don't have any recorded general health information to update.")
        return
        
    out("\n🩺 General Health Questions:")
    question_list = list(gen_questions.keys())
    for i, question in enumerate(question_list, 1):
        out(f"{i}. {question}: {gen_questions[question]}")
    
    question_choice = input_text("\nEnter the number of the question to update (or 0 to cancel): ")
    
    if question_choice == '0' or not question_choice.isdigit():
        out("Operation canceled.")
        return
        
    question_idx = int(question_choice) - 1
    if question_idx < 0 or question_idx >= len(question_list):
        out("Invalid option selected.")
        return
        
    question_to_update = question_list[question_idx]
    current_answer = gen_questions[question_to_update]
    
    new_answer = input_text(f"Enter new answer for '{question_to_update}' (current: {current_answer}): ")
    
    # Update the specific general health question
    updated_gen_questions = decrypted_patient["Gen_questions"].copy()
    updated_gen_questions[question_to_update] = new_answer
    
    # Get updated summary if LLM is available
    if use_llm and "summary" in decrypted_patient:
        # Create a temporary data structure with updated info
        temp_data = {
            "demographic": decrypted_patient["demographic"],
            "per_symptom": decrypted_patient["per_symptom"],
            "Gen_questions": updated_gen_questions
        }
        new_summary = summarize_patient_condition(temp_data)
    else:
        new_summary = decrypted_patient.get("summary", "")
    
    # Encrypt and save to database
    encrypted_gen_questions = encrypt_dict(updated_gen_questions)
    update_dict = {"Gen_questions": encrypted_gen_questions}
    
    if new_summary:
        update_dict["summary"] = encrypt_data(new_summary)
    
    patient_collection.update_one(
        {"_id": patient_doc["_id"]},
        {"$set": update_dict}
    )
    
    out(f"✅ Answer updated successfully!")

# Doctor access functions
def create_doctor_account():
    """Create a new doctor account (requires admin approval)."""
    out("\n👨‍⚕️ New Doctor Registration")
    
    doctor_data = {}
    doctor_data["name"] = input_text("Enter your full name: ")
    doctor_data["email"] = input_text("Enter your email: ")
    doctor_data["specialization"] = input_text("Enter your specialization: ")
    doctor_data["license_number"] = input_text("Enter your medical license number: ")
    
    password = getpass.getpass("Create a password: ")
    confirm_password = getpass.getpass("Confirm password: ")
    
    if password != confirm_password:
        out("❌ Passwords do not match.")
        return
        
    # Create doctor record with pending approval status
    doctor_record = {
        "name": doctor_data["name"],
        "email": doctor_data["email"],
        "specialization": doctor_data["specialization"],
        "license_number": doctor_data["license_number"],
        "password": hash_password(password),
        "status": "pending",  # Requires admin approval
        "created_at": time.time()
    }
    
    doctor_collection.insert_one(doctor_record)
    out("✅ Doctor registration submitted for admin approval.")
    out("You'll be able to log in once an administrator approves your account.")

def doctor_login():
    """Doctor login function."""
    out("\n👨‍⚕️ Doctor Login")
    email = input_text("Enter your email: ")
    password = getpass.getpass("Enter your password: ")
    
    doctor = doctor_collection.find_one({"email": email})
    
    if not doctor:
        out("❌ No doctor account found with that email.")
        return None
        
    # Check account status
    if doctor.get("status") != "approved":
        out("❌ Your account is pending approval by an administrator.")
        return None
        
    # Check password
    if verify_password(doctor.get("password", ""), password):
        out("✅ Login successful!")
        return doctor
    else:
        out("❌ Incorrect password.")
        return None

def doctor_menu(doctor_doc):
    """Menu for doctor access."""
    while True:
        out(f"\n👨‍⚕️ Doctor Portal - Dr. {doctor_doc['name']}")
        out("1. View All Patients")
        out("2. Search Patient by Name")
        out("3. Search Patient by Email")
        out("4. Change Password")
        out("5. Log Out")
        
        choice = input_text("Enter choice: ")
        
        if choice == '1':
            # View all patients (with all their data decrypted)
            out("\n📋 All Patients:")
            for i, patient in enumerate(patient_collection.find(), 1):
                try:
                    decrypted_demographic = decrypt_dict(patient["demographic"])
                    out(f"{i}. {decrypted_demographic.get('name', 'Unknown')} (ID: {patient['_id']})")
                except Exception as e:
                    out(f"Error decrypting patient {patient['_id']}: {e}")
            
            patient_choice = input_text("\nEnter patient number to view details (or 0 to go back): ")
            if patient_choice.isdigit() and int(patient_choice) > 0:
                try:
                    selected_patient = list(patient_collection.find())[int(patient_choice) - 1]
                    view_patient_details(selected_patient)
                except IndexError:
                    out("Invalid patient number.")
                    
        elif choice == '2':
            # Search by name
            name = input_text("Enter patient name to search: ")
            found_patients = []
            
            for patient in patient_collection.find():
                try:
                    decrypted_demographic = decrypt_dict(patient["demographic"])
                    if "name" in decrypted_demographic and name.lower() in decrypted_demographic["name"].lower():
                        found_patients.append(patient)
                except Exception as e:
                    out(f"Error processing patient record: {e}")
            
            if found_patients:
                out(f"\nFound {len(found_patients)} patient(s):")
                for i, patient in enumerate(found_patients, 1):
                    decrypted_demographic = decrypt_dict(patient["demographic"])
                    out(f"{i}. {decrypted_demographic.get('name', 'Unknown')} (ID: {patient['_id']})")
                
                patient_choice = input_text("\nEnter patient number to view details (or 0 to go back): ")
                if patient_choice.isdigit() and 0 < int(patient_choice) <= len(found_patients):
                    view_patient_details(found_patients[int(patient_choice) - 1])
            else:
                out("No patients found with that name.")
                
        elif choice == '3':
            # Search by email
            email = input_text("Enter patient email to search: ")
            
            # We need to decrypt and check each record since the email is encrypted
            found_patients = []
            for patient in patient_collection.find():
                try:
                    decrypted_demographic = decrypt_dict(patient["demographic"])
                    if "email" in decrypted_demographic and email.lower() in decrypted_demographic["email"].lower():
                        found_patients.append(patient)
                except Exception as e:
                    out(f"Error processing patient record: {e}")
            
            if found_patients:
                out(f"\nFound {len(found_patients)} patient(s):")
                for i, patient in enumerate(found_patients, 1):
                    decrypted_demographic = decrypt_dict(patient["demographic"])
                    out(f"{i}. {decrypted_demographic.get('name', 'Unknown')} - {decrypted_demographic.get('email', 'No email')} (ID: {patient['_id']})")
                
                patient_choice = input_text("\nEnter patient number to view details (or 0 to go back): ")
                if patient_choice.isdigit() and 0 < int(patient_choice) <= len(found_patients):
                    view_patient_details(found_patients[int(patient_choice) - 1])
            else:
                out("No patients found with that email.")
                
        elif choice == '4':
            current_password = getpass.getpass("Enter current password: ")
            
            # Verify current password
            if verify_password(doctor_doc.get("password", ""), current_password):
                new_password = getpass.getpass("Enter new password: ")
                confirm_password = getpass.getpass("Confirm new password: ")
                
                if new_password == confirm_password:
                    # Update password in database
                    doctor_collection.update_one(
                        {"_id": doctor_doc["_id"]},
                        {"$set": {"password": hash_password(new_password)}}
                    )
                    out("✅ Password updated successfully!")
                else:
                    out("❌ Passwords do not match.")
            else:
                out("❌ Incorrect current password.")
                
        elif choice == '5':
            out("Logging out...")
            break
        else:
            out("Invalid choice. Please try again.")

def view_patient_details(patient_doc):
    """View detailed patient information for doctors."""
    try:
        # Decrypt all patient data
        decrypted_patient = {
            "demographic": decrypt_dict(patient_doc["demographic"]),
            "per_symptom": decrypt_dict(patient_doc["per_symptom"]),
            "Gen_questions": decrypt_dict(patient_doc["Gen_questions"]),
        }
        
        # Decrypt summary if available
        if "summary" in patient_doc:
            try:
                decrypted_patient["summary"] = decrypt_data(patient_doc["summary"])
            except:
                pass
        
        out("\n🧾 Patient Details:")
        out("\nDemographic Information:")
        for key, value in decrypted_patient["demographic"].items():
            out(f"{key.capitalize()}: {value}")
        
        # Display summary if available
        if "summary" in decrypted_patient and decrypted_patient["summary"]:
            out("\nSummary Assessment:")
            out(decrypted_patient["summary"])
        
        out("\nSymptoms and Health Data:")
        for symptom, details in decrypted_patient["per_symptom"].items():
            out(f"\n{symptom.upper()}:")
            for key, value in details.items():
                out(f"  - {key}: {value}")
        
        out("\nGeneral Health Questionnaire:")
        for question, answer in decrypted_patient["Gen_questions"].items():
            out(f"Q: {question}")
            out(f"A: {answer}\n")
        
        # Use LLM to provide additional insights if available
        if use_llm:
            out("\nWould you like an AI-assisted clinical interpretation of this patient's data? (yes/no)")
            ai_assist = input_text()
            
            if ai_assist.lower() in ["yes", "y", "yeah", "sure"]:
                prompt = f"""
                You are a medical assistant helping a doctor review patient data.
                Based on the following patient information, provide 3-4 clinical insights that might be relevant for the doctor.
                Focus on potential connections between symptoms, possible areas to investigate further, and any patterns in the data.
                Be professional and avoid definitive diagnoses. Use phrases like "may suggest", "could indicate", or "might be worth exploring".
                
                Patient Demographics:
                {decrypted_patient["demographic"]}
                
                Patient Symptoms:
                {decrypted_patient["per_symptom"]}
                
                General Health Information:
                {decrypted_patient["Gen_questions"]}
                
                Format your response as bullet points, focusing only on clinically relevant insights.
                """
                
                ai_insights = get_llm_response(prompt)
                out("\nAI-Assisted Clinical Insights:")
                out(ai_insights)
                
        input_text("\nPress Enter to continue...")
    except Exception as e:
        out(f"Error displaying patient data: {e}")

# Admin access functions
def create_admin_account():
    """Create the first admin account if none exists."""
    if admin_collection.count_documents({}) == 0:
        out("\n🔑 First-time Setup: Creating Admin Account")
        admin_email = input_text("Enter admin email: ")
        admin_name = input_text("Enter admin name: ")
        admin_password = getpass.getpass("Create admin password: ")
        confirm_password = getpass.getpass("Confirm password: ")
        
        if admin_password != confirm_password:
            out("❌ Passwords do not match.")
            return False
            
        admin_record = {
            "name": admin_name,
            "email": admin_email,
            "password": hash_password(admin_password),
            "created_at": time.time()
        }
        
        admin_collection.insert_one(admin_record)
        out("✅ Admin account created successfully!")
        return True
    return False

def admin_login():
    """Admin login function."""
    out("\n🔑 Administrator Login")
    email = input_text("Enter admin email: ")
    password = getpass.getpass("Enter password: ")
    
    admin = admin_collection.find_one({"email": email})
    
    if not admin:
        out("❌ No admin account found with that email.")
        return None
        
    # Check password
    if verify_password(admin.get("password", ""), password):
        out("✅ Login successful!")
        return admin
    else:
        out("❌ Incorrect password.")
        return None

def admin_menu(admin_doc):
    """Menu for admin access."""
    while True:
        out(f"\n🔑 Admin Portal - {admin_doc['name']}")
        out("1. View All Patient Demographics")
        out("2. Approve Doctor Accounts")
        out("3. Manage Doctor Accounts")
        out("4. Add Admin Account")
        out("5. Change Password")
        out("6. Log Out")
        
        choice = input_text("Enter choice: ")
        
        if choice == '1':
            # View all patient demographics (only demographic data, not medical)
            out("\n👥 Patient Demographics:")
            for i, patient in enumerate(patient_collection.find(), 1):
                try:
                    # Decrypt only demographic data
                    decrypted_demographic = decrypt_dict(patient["demographic"])
                    out(f"\nPatient #{i} (ID: {patient['_id']})")
                    for key, value in decrypted_demographic.items():
                        out(f"{key.capitalize()}: {value}")
                except Exception as e:
                    out(f"Error decrypting patient {patient['_id']}: {e}")
            
            input_text("\nPress Enter to continue...")
                
        elif choice == '2':
            # Approve pending doctor accounts
            pending_doctors = list(doctor_collection.find({"status": "pending"}))
            
            if not pending_doctors:
                out("No pending doctor accounts to approve.")
                continue
                
            out("\n👨‍⚕️ Pending Doctor Applications:")
            for i, doctor in enumerate(pending_doctors, 1):
                out(f"{i}. {doctor['name']} - {doctor['email']}")
                out(f"   Specialization: {doctor['specialization']}")
                out(f"   License Number: {doctor['license_number']}")
                out(f"   Applied on: {time.ctime(doctor['created_at'])}\n")
            
            doctor_choice = input_text("Enter doctor number to approve (or 0 to go back): ")
            if doctor_choice.isdigit() and 0 < int(doctor_choice) <= len(pending_doctors):
                selected_doctor = pending_doctors[int(doctor_choice) - 1]
                
                out(f"\nSelected Doctor: {selected_doctor['name']}")
                approve = input_text("Approve this doctor? (yes/no): ").lower()
                
                if approve == "yes":
                    doctor_collection.update_one(
                        {"_id": selected_doctor["_id"]},
                        {"$set": {"status": "approved", "approved_by": admin_doc["name"], "approved_at": time.time()}}
                    )
                    out("✅ Doctor account approved!")
                else:
                    out("Operation canceled.")
                    
        elif choice == '3':
            # Manage existing doctor accounts
            out("\n👨‍⚕️ Manage Doctor Accounts:")
            out("1. View All Doctors")
            out("2. Search by Name")
            out("3. Disable/Enable Doctor Account")
            out("4. Back to Main Menu")
            
            subchoice = input_text("Enter choice: ")
            
            if subchoice == '1':
                doctors = list(doctor_collection.find())
                if not doctors:
                    out("No doctor accounts found.")
                    continue
                    
                out("\nAll Doctor Accounts:")
                for i, doctor in enumerate(doctors, 1):
                    status = "🟢 Active" if doctor.get("status") == "approved" else "🔴 Pending"
                    out(f"{i}. {doctor['name']} - {doctor['email']} ({status})")
                    out(f"   Specialization: {doctor['specialization']}")
                    out(f"   License: {doctor['license_number']}\n")
                
                input_text("Press Enter to continue...")
                
            elif subchoice == '2':
                name = input_text("Enter doctor name to search: ")
                doctors = list(doctor_collection.find({"name": {"$regex": name, "$options": "i"}}))
                
                if not doctors:
                    out("No matching doctors found.")
                    continue
                    
                out("\nMatching Doctors:")
                for i, doctor in enumerate(doctors, 1):
                    status = "🟢 Active" if doctor.get("status") == "approved" else "🔴 Pending"
                    out(f"{i}. {doctor['name']} - {doctor['email']} ({status})")
                
                input_text("Press Enter to continue...")
                
            elif subchoice == '3':
                doctors = list(doctor_collection.find())
                if not doctors:
                    out("No doctor accounts found.")
                    continue
                    
                out("\nDoctor Accounts:")
                for i, doctor in enumerate(doctors, 1):
                    status = "🟢 Active" if doctor.get("status") == "approved" else "🔴 Pending/Disabled"
                    out(f"{i}. {doctor['name']} - {doctor['email']} ({status})")
                
                doctor_choice = input_text("Enter doctor number to toggle status (or 0 to go back): ")
                if doctor_choice.isdigit() and 0 < int(doctor_choice) <= len(doctors):
                    selected_doctor = doctors[int(doctor_choice) - 1]
                    
                    new_status = "disabled" if selected_doctor.get("status") == "approved" else "approved"
                    action = "disable" if new_status == "disabled" else "enable"
                    
                    confirm = input_text(f"Are you sure you want to {action} Dr. {selected_doctor['name']}'s account? (yes/no): ").lower()
                    if confirm == "yes":
                        doctor_collection.update_one(
                            {"_id": selected_doctor["_id"]},
                            {"$set": {"status": new_status, "modified_by": admin_doc["name"], "modified_at": time.time()}}
                        )
                        out(f"✅ Doctor account {action}d successfully!")
                    else:
                        out("Operation canceled.")
            
            elif subchoice == '4':
                continue
            else:
                out("Invalid choice.")
                
        elif choice == '4':
            # Add new admin account
            out("\n➕ Add New Administrator:")
            admin_name = input_text("Enter name: ")
            admin_email = input_text("Enter email: ")
            
            # Check if email already exists
            if admin_collection.find_one({"email": admin_email}):
                out("❌ An admin with this email already exists.")
                continue
                
            admin_password = getpass.getpass("Create password: ")
            confirm_password = getpass.getpass("Confirm password: ")
            
            if admin_password != confirm_password:
                out("❌ Passwords do not match.")
                continue
                
            new_admin = {
                "name": admin_name,
                "email": admin_email,
                "password": hash_password(admin_password),
                "created_by": admin_doc["name"],
                "created_at": time.time()
            }
            
            admin_collection.insert_one(new_admin)
            out("✅ New admin account created successfully!")
            
        elif choice == '5':
            # Change admin password
            current_password = getpass.getpass("Enter current password: ")
            
            if verify_password(admin_doc.get("password", ""), current_password):
                new_password = getpass.getpass("Enter new password: ")
                confirm_password = getpass.getpass("Confirm new password: ")
                
                if new_password == confirm_password:
                    admin_collection.update_one(
                        {"_id": admin_doc["_id"]},
                        {"$set": {"password": hash_password(new_password)}}
                    )
                    out("✅ Password updated successfully!")
                else:
                    out("❌ Passwords do not match.")
            else:
                out("❌ Incorrect current password.")
                
        elif choice == '6':
            out("Logging out...")
            break
            
        else:
            out("Invalid choice. Please try again.")

def login_menu():
    """Main login menu for all user types."""
    while True:
        out("\n🏥 Health Chatbot System Login")
        out("1. Patient Login")
        out("2. Doctor Login")
        out("3. Admin Login")
        out("4. Register as New Patient")
        out("5. Register as New Doctor")
        out("6. Exit")
        
        choice = input_text("Enter choice: ")
        
        if choice == '1':
            patient_doc = patient_login()
            if patient_doc:
                patient_menu(patient_doc)
                
        elif choice == '2':
            doctor_doc = doctor_login()
            if doctor_doc:
                doctor_menu(doctor_doc)
                
        elif choice == '3':
            # Check if admin collection is empty (first-time setup)
            if admin_collection.count_documents({}) == 0:
                out("No admin accounts found. Setting up first admin account.")
                if not create_admin_account():
                    continue
            
            admin_doc = admin_login()
            if admin_doc:
                admin_menu(admin_doc)
                
        elif choice == '4':
            # Register as new patient - will run the chatbot interview process
            out("\n👤 New Patient Registration")
            out("You'll be guided through a health interview to create your record.")
            result = collect_data()
            if result == 0:
                out("Registration canceled.")
                
        elif choice == '5':
            # Register as new doctor
            create_doctor_account()
            
        elif choice == '6':
            out("Exiting system. Goodbye!")
            break
            
        else:
            out("Invalid choice. Please try again.")



def handle_api_rate_limits(retry_count=3, delay=2):
    """Decorator to handle API rate limits and retry requests."""
    def decorator(func):
        def wrapper(*args, **kwargs):
            for attempt in range(retry_count):
                try:
                    return func(*args, **kwargs)
                except Exception as e:
                    if "rate limit" in str(e).lower() and attempt < retry_count - 1:
                        print(f"Rate limit hit, retrying in {delay} seconds...")
                        time.sleep(delay)
                        continue
                    else:
                        print(f"API error: {e}")
                        # Return a fallback response
                        return "I apologize, but I'm having temporary technical difficulties. Let's continue with basic questions."
            return func(*args, **kwargs)
        return wrapper
    return decorator

# Apply the decorator to the get_llm_response function
get_llm_response = handle_api_rate_limits()(get_llm_response)



def Chatbot():
    """Main chatbot function with improved language handling."""
    global conversation_choice, language
    out("(enter \"exit\" to quit chat)\n")
    
    # Initialize with language detection
    welcome_options = "Which mode would you like to talk to me in?\n\t1. Speech (Speaking to bot)\n\t2. Text (Writing to bot)"
    out(f"Chatbot: {welcome_options}")
    
    try:
        choice_input = input_text("Enter choice: ")
        conversation_choice = int(choice_input)
    except ValueError:
        out("Invalid choice. Defaulting to text mode.")
        conversation_choice = 2
    
    print(f"Chatbot : Which language would you like me to talk in?\nChatbot : languages - {supp_langs}")
    lang_choice = input("YOU : ").lower()
    language = language_map[lang_choice] if lang_choice in supp_langs else print("Chatbot : Language not supported!")
    print("Language set. You can change anytime by typing 'change language'")
    
    # Welcome message using Claude if available
    if use_llm:
        welcome_prompt = """
        You are a warm, empathetic healthcare chatbot. Write a brief welcome message (2-3 sentences)
        introducing yourself to a new user. Explain that you're a health assistant that can help with
        health assessments or provide access to existing health records. Keep it friendly and professional.
        """
        welcome_message = get_llm_response(welcome_prompt)
    else:
        welcome_message = "Hi there! I'm your health assistant here to help you with health diagnosis and record access."
    
    # Translate welcome message to user's language if not English
    if language != 'en':
        try:
            from deep_translator import GoogleTranslator
            welcome_message = GoogleTranslator(source='en', target=language).translate(welcome_message)
        except Exception as e:
            print(f"Translation error: {e}")
    
    out(f"Health Assistant: {welcome_message}")
    
    options_text = "Would you like to:\n\t1. Complete a health assessment\n\t2. Access the system as an existing user"
    
    # Translate options if needed
    if language != 'en':
        try:
            from deep_translator import GoogleTranslator
            options_text = GoogleTranslator(source='en', target=language).translate(options_text)
        except Exception as e:
            print(f"Translation error: {e}")
    
    out(f"Health Assistant: {options_text}")
    
    try:
        choice_input = input_text("Enter choice: ").lower()
        
        # Check for language change request
        # while choice_input == "change language":
        #     # Translate options again with the new language
        #     try:
        #         from deep_translator import GoogleTranslator
        #         options_text = GoogleTranslator(source='en', target=language).translate(
        #             "Would you like to:\n\t1. Complete a health assessment\n\t2. Access the system as an existing user"
        #         )
        #     except Exception as e:
        #         print(f"Translation error: {e}")
                
        #     out(f"Health Assistant: {options_text}")
        #     choice_input = input_text("Enter choice: ")
        
        user_choice = int(choice_input)
    except ValueError:
        out("Invalid choice. Defaulting to health assessment.")
        user_choice = 1
    
    if user_choice == 1:
        collect_data()
    elif user_choice == 2:
        login_menu()
    else:
        out("Invalid choice. Exiting.")
    
    # Farewell message using Claude if available
    if use_llm:
        farewell_prompt = """
        You are a warm, empathetic healthcare chatbot ending a conversation. Write a brief farewell message (1-2 sentences)
        thanking the user for their time and wishing them good health. Keep it friendly and professional.
        """
        farewell_message = get_llm_response(farewell_prompt)
        
        # Translate farewell message if needed
        if language != 'en':
            try:
                from deep_translator import GoogleTranslator
                farewell_message = GoogleTranslator(source='en', target=language).translate(farewell_message)
            except Exception as e:
                print(f"Translation error: {e}")
    else:
        farewell_message = "Thank you for using our health assistant. Wishing you good health!"
    
    out(f"Health Assistant: {farewell_message}")


# Initialize database with default admin if needed
def initialize_system():
    """Initialize the system by creating collections and default admin if needed."""
    # Check if admin collection exists and has at least one admin
    if admin_collection.count_documents({}) == 0:
        out("🔧 First-time system setup")
        create_admin_account()

# Main entry point
if __name__ == "__main__":
    try:
        # Setup pygame for audio
        pygame.init()
        
        # Initialize system
        initialize_system()
        
        # Start the chatbot
        Chatbot()
        
    except KeyboardInterrupt:
        out("\nExiting the Health Assistant. Goodbye!")
    except Exception as e:
        out(f"An unexpected error occurred: {e}")
    finally:
        # Clean up resources
        try:
            pygame.quit()
            client.close()  # Close MongoDB connection
            if os.path.exists("input.wav"):
                os.remove("input.wav")
            if os.path.exists("output.mp3"):
                os.remove("output.mp3")
        except:
            pass




