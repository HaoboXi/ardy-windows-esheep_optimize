"""Conservative validity checks; these do not claim to prove translation semantics."""
import re

def validate_english(text):
    if not isinstance(text,str) or not 1<=len(text.strip())<=2000 or not re.search('[A-Za-z]',text):raise ValueError('Translation produced no usable English. Edit the English prompt.')
    if re.search('[\u3400-\u9fff]',text) or any(ord(c)<32 and c not in '\r\n\t' for c in text):raise ValueError('Translation contains Chinese or control characters. Confirm an English prompt before generation.')
    return text

def semantic_warnings(source,target):
    warnings=[];en=target.lower()
    for zh,word in [('左','left'),('右','right'),('不','not'),('别','not'),('勿','not'),('禁止','not'),('没有','not')]:
        if zh in source and word not in en and not (word=='not' and re.search(r"\b(no|never|without|avoid|don't|doesn't|cannot|can't)\b",en)):
            warnings.append('Missing direction/negation: '+zh)
    return warnings
