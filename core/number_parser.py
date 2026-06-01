"""Number parser for decomposition and arithmetic support.

Handles decomposing numbers into place values, parsing decimals,
scientific notation, and number validation/tokenization.
"""

import re
from typing import Optional, Union


class NumberParser:
    """Parse and decompose numbers of any length up to trillions."""

    PLACE_VALUES = {
        0: "ones", 1: "tens", 2: "hundreds",
        3: "thousands", 4: "ten_thousands", 5: "hundred_thousands",
        6: "millions", 7: "ten_millions", 8: "hundred_millions",
        9: "billions", 10: "ten_billions", 11: "hundred_billions",
        12: "trillions",
    }

    BASE_VALUES = [10 ** i for i in range(13)]

    @classmethod
    def decompose_integer(cls, n: int) -> dict[int, int]:
        if n == 0:
            return {0: 0}
        result = {}
        remaining = abs(n)
        sign = -1 if n < 0 else 1
        for base in sorted(cls.BASE_VALUES, reverse=True):
            if remaining >= base:
                coeff = (remaining // base) % 10
                if coeff > 0:
                    result[base * sign] = coeff
                remaining %= base
        return result

    @classmethod
    def decompose_decimal(cls, value: float) -> dict[float, int]:
        result = {}
        integer_part = int(value)
        if integer_part != 0:
            result[1] = integer_part
        fractional = value - integer_part
        if fractional > 0:
            remaining = fractional
            for divisor in [10, 100, 1000, 10000, 100000, 1000000]:
                place = 1.0 / divisor
                if remaining >= place - 1e-12:
                    coeff = int(remaining / place + 0.5)
                    if coeff > 0:
                        result[place] = coeff
                        remaining -= coeff * place
                if remaining < 1e-12:
                    break
        return result

    @classmethod
    def parse_scientific(cls, text: str) -> Optional[float]:
        text = text.strip().lower()
        match = re.search(r'([+-]?\d+(?:\.\d+)?)[eE]([+-]?\d+)', text)
        if match:
            return float(match.group(1)) * (10 ** int(match.group(2)))
        match = re.search(r'([+-]?\d+(?:\.\d+)?)\s*[x]\s*10\^([+-]?\d+)', text)
        if match:
            return float(match.group(1)) * (10 ** int(match.group(2)))
        match = re.search(r'10\^([+-]?\d+)', text)
        if match:
            return 10 ** int(match.group(1))
        return None

    @classmethod
    def parse_number(cls, text: str) -> Optional[Union[int, float]]:
        text = text.strip()
        sci_value = cls.parse_scientific(text)
        if sci_value is not None:
            return sci_value
        if ',' in text and '.' not in text:
            text = text.replace(',', '.')
        try:
            return int(text)
        except ValueError:
            pass
        try:
            return float(text)
        except ValueError:
            pass
        return None

    @classmethod
    def tokenize_number(cls, value: Union[int, float]) -> list[str]:
        if isinstance(value, int):
            decomposition = cls.decompose_integer(value)
            tokens = []
            for place, coeff in decomposition.items():
                if abs(place) >= 1:
                    token = str(abs(place) * coeff)
                    if value < 0:
                        token = f"-{token}"
                    tokens.append(token)
            return tokens
        else:
            decomposition = cls.decompose_decimal(value)
            tokens = []
            for place, coeff in decomposition.items():
                if place == 1:
                    token = str(coeff)
                else:
                    token = f"{coeff * place:.10f}".rstrip('0').rstrip('.')
                tokens.append(token)
            return tokens

    @classmethod
    def known_tokens(cls) -> set[str]:
        tokens = set()
        for i in range(10):
            tokens.add(str(i))
        for exp in range(1, 13):
            for i in range(1, 10):
                tokens.add(str(i * 10 ** exp))
        for i in range(1, 10):
            tokens.add(f"0.{i}")
            tokens.add(f"0.0{i}")
            tokens.add(f"0.00{i}")
        return tokens
