import os
import pdfplumber
from docx import Document
from utils_data import clean_text

def extract_from_pdf(path):
    text = []
    with pdfplumber.open(path) as pdf:
        for page in pdf.pages:
            text.append(page.extract_text() or "")
    return clean_text("\n".join(text))

def extract_from_docx(path):
    doc = Document(path)
    paragraphs = [p.text for p in doc.paragraphs]
    return clean_text("\n".join(paragraphs))

def extract_from_txt(path):
    with open(path, encoding="utf-8") as f:
        return clean_text(f.read())

def extract_document(path):
    ext = os.path.splitext(path)[1].lower()
    if ext == ".pdf":
        return extract_from_pdf(path)
    elif ext in [".docx", ".doc"]:
        return extract_from_docx(path)
    elif ext == ".txt":
        return extract_from_txt(path)
    else:
        raise ValueError(f"Unsupported document type: {ext}")
