"""Xiao'e double-pinyin search utilities."""

import pypinyin
from pypinyin import Style


XIAO_E_FINALS = {
    'a': 'a', 'ai': 'd', 'an': 'j', 'ang': 'h', 'ao': 'c',
    'e': 'e', 'ei': 'w', 'en': 'f', 'eng': 'g', 'er': 'r',
    'i': 'i',
    'ia': 'x', 'ian': 'm', 'iang': 'l', 'iao': 'n', 'ie': 'p',
    'in': 'b', 'ing': 'k', 'iong': 's', 'iu': 'q',
    'o': 'o', 'ong': 's', 'ou': 'z',
    'u': 'u', 'ua': 'x', 'uai': 'k', 'uan': 'r', 'uang': 'l',
    'ue': 't', 'ui': 'v', 'un': 'y', 'uo': 'o',
    'v': 'v', 've': 't', 'vn': 'y',
}

XIAO_E_INITIALS = {
    'b': 'b', 'p': 'p', 'm': 'm', 'f': 'f',
    'd': 'd', 't': 't', 'n': 'n', 'l': 'l',
    'g': 'g', 'k': 'k', 'h': 'h',
    'j': 'j', 'q': 'q', 'x': 'x',
    'r': 'r',
    'z': 'z', 'c': 'c', 's': 's',
    'y': 'y', 'w': 'w',
    'zh': 'v', 'ch': 'i', 'sh': 'u',
}

ZERO_INITIAL_MAP = {
    'a': 'aa', 'ai': 'ad', 'an': 'aj', 'ang': 'ah', 'ao': 'ac',
    'e': 'ee', 'ei': 'ew', 'en': 'ef', 'eng': 'eg', 'er': 'er',
    'o': 'oo', 'ou': 'oz',
}


def _split_pinyin(syllable: str) -> tuple:
    syllable = syllable.lower().strip()
    for init in ['zh', 'ch', 'sh']:
        if syllable.startswith(init):
            return init, syllable[len(init):]
    if syllable and syllable[0] in 'bpmfdtnlgkhjqxrzcsyw':
        return syllable[0], syllable[1:]
    return '', syllable


def _pinyin_to_xiao_e(syllable: str) -> str:
    syllable = syllable.lower().strip()
    if syllable in ZERO_INITIAL_MAP:
        return ZERO_INITIAL_MAP[syllable]
    initial, final = _split_pinyin(syllable)
    init_key = XIAO_E_INITIALS.get(initial, initial)
    final_key = XIAO_E_FINALS.get(final, final)
    return init_key + final_key


def text_to_xiao_e(text: str) -> str:
    pinyins = pypinyin.pinyin(text, style=Style.NORMAL)
    result = []
    for py_list in pinyins:
        py = py_list[0]
        if py and py[0].isalpha():
            result.append(_pinyin_to_xiao_e(py))
        else:
            result.append(py)
    return ''.join(result)


def text_to_abbreviation(text: str) -> str:
    pinyins = pypinyin.pinyin(text, style=Style.FIRST_LETTER)
    result = []
    for py_list in pinyins:
        result.append(py_list[0])
    return ''.join(result)


class PinyinSearch:
    """Search utility supporting xiao'e double-pinyin and abbreviation matching."""

    @staticmethod
    def matches(query: str, text: str) -> bool:
        if not query:
            return True
        query = query.lower()
        if query in text.lower():
            return True
        try:
            if query in text_to_xiao_e(text).lower():
                return True
        except Exception:
            pass
        try:
            if query in text_to_abbreviation(text).lower():
                return True
        except Exception:
            pass
        return False
