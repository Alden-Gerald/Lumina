"""CPU-only token accounting, with a conservative fallback and template reserve."""
import functools
import json
from .settings import DATA_ROOT

@functools.lru_cache(maxsize=2)
def tokenizer(profile):
    name={'power':'qwen3-coder.json','quality':'qwen2.5-coder.json'}.get(profile)
    if not name:return None
    path=DATA_ROOT/'tokenizers'/name
    if not path.exists():return None
    from tokenizers import Tokenizer
    return Tokenizer.from_file(str(path))

def estimate(messages,schema,profile):
    text=json.dumps([messages,schema],ensure_ascii=False)
    encoder=tokenizer(profile)
    if encoder is None:return len(text.encode())
    # Counting serialized message/schema metadata overestimates raw content.
    # The separate 2500-token reserve covers the chat template and generation.
    return len(encoder.encode(text,add_special_tokens=False).ids)
