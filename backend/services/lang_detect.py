import re

# Devanagari (Hindi) and Tamil Unicode block character matches
RE_HINDI_SCRIPT = re.compile(r"[\u0900-\u097f]")
RE_TAMIL_SCRIPT = re.compile(r"[\u0b80-\u0bff]")

# Heuristic vocabulary lists for transliterated text (excluding English words like doctor, book, etc.)
HINDI_ROMAN_KEYWORDS = {
    "mujhe", "milna", "karna", "karana", "kal", "parso", 
    "aaj", "hai", "hoga", "chahiye", "cancal", "badal",
    "samay", "baje", "ji", "namaste", "namaskar"
}

TAMIL_ROMAN_KEYWORDS = {
    "nalai", "maruthuvar", "paarka", "vendum", "santhippu", "pathivu", "seiya", "enakkul",
    "doctora", "enaku", "naalai", "seiyavum", "en",
    "matra", "maruthuvamanai", "apollo", "vanakkam"
}

def detect_language(text: str) -> str:
    """Detects whether input is English, Hindi, or Tamil. Low latency heuristic (under 1ms)."""
    if not text or not isinstance(text, str):
        return "English"
        
    cleaned_text = text.strip()
    
    # 1. Native script detection
    if RE_TAMIL_SCRIPT.search(cleaned_text):
        return "Tamil"
    if RE_HINDI_SCRIPT.search(cleaned_text):
        return "Hindi"
        
    # 2. Transliterated roman analysis
    words = set(re.findall(r"\b\w+\b", cleaned_text.lower()))
    
    hindi_score = len(words.intersection(HINDI_ROMAN_KEYWORDS))
    tamil_score = len(words.intersection(TAMIL_ROMAN_KEYWORDS))
    
    if tamil_score > 0 and tamil_score >= hindi_score:
        return "Tamil"
    if hindi_score > 0 and hindi_score > tamil_score:
        return "Hindi"
        
    # Default fallback
    return "English"

if __name__ == "__main__":
    # Rapid quick tests
    print(detect_language("நாளை மருத்துவரை பார்க்க வேண்டும்"))  # Tamil
    print(detect_language("मुझे कल डॉक्टर से मिलना है"))      # Hindi
    print(detect_language("Mujhe kal Dr. Sharma se milna hai")) # Hindi (Transliterated)
    print(detect_language("Nalai maruthuvarai paarka vendum"))   # Tamil (Transliterated)
    print(detect_language("Book an appointment tomorrow with Dr. John")) # English
