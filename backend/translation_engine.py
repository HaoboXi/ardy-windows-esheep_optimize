"""Neural clause translation plus conservative domain checks; no dictionary fallback."""
import re
from translation_text import validate_english,semantic_warnings

NUMBERS={'零':0,'一':1,'两':2,'二':2,'三':3,'四':4,'五':5,'六':6,'七':7,'八':8,'九':9,'十':10}
EN_NUMBERS=['zero','one','two','three','four','five','six','seven','eight','nine','ten']

def quantity(n):
    if n in NUMBERS:return NUMBERS[n]
    if n.isdigit():return int(n)
    m=re.fullmatch(r'([一二两三四五六七八九]?)十([一二两三四五六七八九]?)',n)
    if m:return (NUMBERS[m[1]] if m[1] else 1)*10+(NUMBERS[m[2]] if m[2] else 0)
    return n

def number_word(value):
    if not isinstance(value,int):return str(value)
    small=EN_NUMBERS+['eleven','twelve','thirteen','fourteen','fifteen','sixteen','seventeen','eighteen','nineteen']
    if value<20:return small[value]
    if value<100:return ['','','twenty','thirty','forty','fifty','sixty','seventy','eighty','ninety'][value//10]+(' '+small[value%10] if value%10 else '')
    return str(value)

def atomic_correction(part):
    """Exact atomic phrases with measured MT errors, never a complex-sentence fallback."""
    def count(n):
        v=quantity(n)
        return 'once' if v==1 else 'twice' if v==2 else number_word(v)+' times'
    m=re.fullmatch(r'(?:角色)?(快速|慢慢)?向(前|后)(走|退)([一二两三四五六七八九十\d]+)步',part)
    if m:
        n=number_word(quantity(m[4]))
        return 'A person takes '+n+' steps '+('forward' if m[2]=='前' else 'backward')+({'快速':' quickly','慢慢':' slowly'}.get(m[1],''))
    m=re.fullmatch(r'(慢慢|缓慢地?)?蹲下(?:([一二两三四五六七八九十\d]+)次)?',part)
    if m:return 'A person squats down'+(' slowly' if m[1] else '')+(' '+count(m[2]) if m[2] else '')
    m=re.fullmatch(r'举起([左右])手挥动([一二两三四五六七八九十\d]+)次',part)
    if m:return 'A person raises the '+('left' if m[1]=='左' else 'right')+' hand and waves '+count(m[2])
    m=re.fullmatch(r'原地跳([一二两三四五六七八九十\d]+)次',part)
    if m:return 'A person jumps in place '+count(m[1])
    return {'抬头':'A person raises their head','放下':'Lower it'}.get(part)

def neural_translate(text,sp,tr):
    tokens=sp.encode(text,out_type=str)
    if len(tokens)>140:raise ValueError('A clause exceeds the offline model limit. Split the prompt into shorter segments or enter English.')
    r=tr.translate_batch([tokens],beam_size=4,length_penalty=.2,replace_unknowns=True,max_decoding_length=256)[0]
    # The package has a Chinese-only SentencePiece vocabulary; target pieces
    # must be joined as Argos 1.9 did, not decoded through that source vocabulary.
    return ''.join(r.hypotheses[0]).replace('\u2581',' ').strip()

def translate(text,sp,tr):
    parts=re.split(r'[，,；;。！？!?\n]+',text);results=[];warnings=[]
    for part in parts:
        part=part.strip()
        if not part:continue
        if not re.search('[\u3400-\u9fff]',part):results.append(part);continue
        # Preserve explicit temporal connectives outside neural decoding.
        connector=''
        for prefix,en in [('然后','then'),('最后','finally'),('接着','then'),('再','then'),('先','first')]:
            if prefix=='再' and (not results or part.startswith(('再次','再也','再不'))):continue
            if part.startswith(prefix):connector=en;part=part[len(prefix):];break
        # Domain normalization only; the full clause is still neurally translated.
        normalized=part.replace('角色先','角色首先').replace('角色','他')
        implicit=not re.match(r'(他|她|它|这|那|人|角色|男人|女人|男孩|女孩)',part)
        if implicit:normalized='他'+normalized
        # A small domain glossary disambiguates common MT errors ("underground"
        # for a squat). Neural translation still handles each complete clause.
        normalized=normalized.replace('蹲下','squat down').replace('一圈','one full turn')
        en=neural_translate(normalized+'。',sp,tr)
        en=atomic_correction(part) or en
        if implicit or part.startswith('角色'):
            en=re.sub(r"^He's right foot",'Their right foot',en);en=re.sub(r"^He's left foot",'Their left foot',en)
            en=re.sub(r"^He's\b",'A person is',en);en=re.sub(r'^He\b','A person',en)
            en=re.sub(r'\bhis\b','their',en)
        if '前面的人' in part:en=en.replace('the front man','the person in front')
        # English terms in mixed input must survive verbatim; otherwise require review.
        for phrase in re.findall(r'[A-Za-z][A-Za-z0-9_-]*(?: +[A-Za-z][A-Za-z0-9_-]*)*',part):
            if phrase not in en:
                match=re.search(re.escape(phrase),en,re.I)
                if match:en=en[:match.start()]+phrase+en[match.end():]
                else:warnings.append('English term was changed: '+phrase)
        warnings.extend(semantic_warnings(part,en))
        lower=en.lower()
        if any(x in part for x in ['再次','重复','反复']) and not re.search(r'again|repeat|repeated|over and over',lower):warnings.append('Check repetition: keep repeated actions')
        for n,unit in re.findall(r'([零一二两三四五六七八九十百千万]+|\d+(?:\.\d+)?)(步|次|秒|圈)',part):
            value=quantity(n);word=number_word(value)
            alternatives=[str(value),word]
            if value==1:alternatives+=['once','a step','a second','a circle','a full','one']
            if value==2 and unit=='次':alternatives+=['twice']
            if not any(re.search(r'\b'+re.escape(x).replace(r'\ ',r'[ -]')+r'\b',lower) for x in alternatives):warnings.append('Check count/time: '+n+unit)
        for zh,pattern in [('快',r'quick|fast|rapid'),('慢',r'slow|gradual'),('停止',r'stop|halt'),('停下',r'stop|halt'),('跳',r'jump|hop'),('挥',r'wav'),('蹲',r'squat|crouch'),('拥抱',r'hug|embrac'),('举起',r'rais|lift|hands? up'),('抬起',r'rais|lift'),('踢',r'kick'),('跑',r'run|ran|jog'),('走',r'walk|step|mov|go|went'),('向前',r'forward|ahead'),('向后',r'back'),('原地',r'in place|on the spot'),('站姿',r'stand'),('保持',r'keep|hold|stay|remain|still')]:
            if zh in part and not re.search(pattern,lower):warnings.append('Check action/speed: '+zh)
        if connector:en=connector+', '+en
        results.append(en.rstrip('.'))
    english=validate_english('; '.join(results)+'.')
    return dict(translated_prompt=english,translation_status='NEEDS_REVIEW' if warnings else 'TRANSLATED',warnings=warnings)
