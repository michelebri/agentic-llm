# Multi-Agent Document Generation System

Automated document generation from unstructured PDFs using a modular four-step pipeline with vision-language models and deterministic rule-based filling.

## Overview

This system transforms scanned or digital Italian public administration (PA) documents into clean, structured, fillable PDFs. It intelligently extracts document structure, classifies documents, and fills placeholders with data from citizen records and user input.

**Key Features:**
- 🔍 **Adaptive Layout Detection**: Hybrid native PDF extraction + OCR fallback
- 🤖 **Intelligent Document Understanding**: LLM-based classification and structure reconstruction
- 📝 **Deterministic Field Filling**: Rule-based substitution with complete provenance tracking
- ✅ **Comprehensive Validation**: Format checks, field completeness, cross-field consistency
- 🎨 **Clean PDF Rendering**: Flow-layout rendering for legibility and consistency
- 🔐 **Privacy-First**: Open-source models only, zero data retention

## Architecture

```
Step 1: Adaptive Layout Detection
    ├─ Native PDF extraction (PyMuPDF)
    └─ OCR Fallback (DeepSeek-OCR-2)
         ↓
Step 2: Document Understanding & Structure Reconstruction
    ├─ Document Classification (metadata + complexity)
    └─ Blueprint Extraction (typed logical blocks)
         ↓
Step 3: Rule-Based Field Instantiation
    └─ Deterministic field filling with provenance tracking
         ↓
Step 4: Validation & Rendering
    ├─ Rule-based quality checks
    └─ PDF rendering with consistent styling
```
