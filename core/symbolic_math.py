from __future__ import annotations

import ast
import math
import re
from dataclasses import dataclass


_ALLOWED_BINOPS = (ast.Add, ast.Sub, ast.Mult, ast.Div)
_ALLOWED_UNARY = (ast.UAdd, ast.USub)


@dataclass
class ArithmeticResult:
    expression: str
    key: str
    value: str
    steps: list[str]


@dataclass
class CalculusResult:
    kind: str
    variable: str
    expression: str
    result: str
    steps: list[str]


def _format_number(value: float) -> str:
    if float(value).is_integer():
        return str(int(value))
    return f"{value:.8f}".rstrip("0").rstrip(".")


def _normalize_arithmetic_text(text: str) -> str:
    q = (text or "").lower()
    replacements = {
        "toplama": "+",
        "topla": "+",
        "arti": "+",
        "plus": "+",
        "add": "+",
        "cikarma": "-",
        "cikar": "-",
        "eksi": "-",
        "minus": "-",
        "subtract": "-",
        "carpma": "*",
        "carp": "*",
        "times": "*",
        "multiply": "*",
        "bolme": "/",
        "bol": "/",
        "divide": "/",
    }
    for old, new in replacements.items():
        q = re.sub(rf"\b{old}\b", f" {new} ", q)

    # "9x8" or "9 x 8" as multiplication, but keep symbolic x in calculus terms.
    q = re.sub(r"(?<=\d)\s*x\s*(?=\d)", " * ", q)
    q = re.sub(r"\s+", " ", q).strip()
    return q


def extract_arithmetic_expression(text: str) -> str | None:
    q = _normalize_arithmetic_text(text)
    # Keep only characters useful for arithmetic expression extraction.
    q = re.sub(r"[^0-9+\-*/(). ]", " ", q)
    q = re.sub(r"\s+", " ", q).strip()
    if not q:
        return None

    # Prefer full candidate string if it looks expression-like.
    if re.fullmatch(r"[0-9+\-*/(). ]+", q) and re.search(r"[+\-*/]", q):
        return q.replace(" ", "")

    # Fallback: first expression fragment.
    m = re.search(r"\d[0-9+\-*/(). ]*", q)
    if not m:
        return None
    candidate = m.group(0).strip().replace(" ", "")
    if re.search(r"[+\-*/]", candidate):
        return candidate
    return None


def _safe_eval(node: ast.AST) -> float:
    if isinstance(node, ast.Expression):
        return _safe_eval(node.body)
    if isinstance(node, ast.Constant):
        if isinstance(node.value, (int, float)):
            return float(node.value)
        raise ValueError("invalid constant")
    if isinstance(node, ast.BinOp) and isinstance(node.op, _ALLOWED_BINOPS):
        left = _safe_eval(node.left)
        right = _safe_eval(node.right)
        if isinstance(node.op, ast.Add):
            return left + right
        if isinstance(node.op, ast.Sub):
            return left - right
        if isinstance(node.op, ast.Mult):
            return left * right
        if isinstance(node.op, ast.Div):
            if right == 0:
                raise ZeroDivisionError("division by zero")
            return left / right
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, _ALLOWED_UNARY):
        val = _safe_eval(node.operand)
        return val if isinstance(node.op, ast.UAdd) else -val
    raise ValueError("unsupported expression")


def _node_to_text(node: ast.AST) -> str:
    try:
        return ast.unparse(node)
    except Exception:
        return str(node)


def _column_addition_steps(left: int, right: int) -> list[str]:
    a = str(left)
    b = str(right)
    width = max(len(a), len(b))
    a = a.zfill(width)
    b = b.zfill(width)

    carry = 0
    result_digits: list[str] = []
    steps: list[str] = [f"Use column addition for {left} + {right}."]

    for idx in range(width - 1, -1, -1):
        da = int(a[idx])
        db = int(b[idx])
        total = da + db + carry
        digit = total % 10
        next_carry = total // 10
        position = width - idx

        if carry:
            steps.append(
                f"Column {position}: {da} + {db} + carry {carry} = {total}; write {digit}, carry {next_carry}."
            )
        else:
            steps.append(
                f"Column {position}: {da} + {db} = {total}; write {digit}, carry {next_carry}."
            )

        result_digits.append(str(digit))
        carry = next_carry

    if carry:
        steps.append(f"Final carry is {carry}; prepend it.")
        result_digits.append(str(carry))

    result = "".join(reversed(result_digits)).lstrip("0") or "0"
    steps.append(f"Combine digits to get {result}.")
    return steps


def _eval_with_steps(node: ast.AST) -> tuple[float, list[str]]:
    if isinstance(node, ast.Expression):
        return _eval_with_steps(node.body)

    if isinstance(node, ast.Constant):
        if isinstance(node.value, (int, float)):
            return float(node.value), [f"Read constant {_format_number(float(node.value))}."]
        raise ValueError("invalid constant")

    if isinstance(node, ast.UnaryOp) and isinstance(node.op, _ALLOWED_UNARY):
        val, steps = _eval_with_steps(node.operand)
        if isinstance(node.op, ast.UAdd):
            return val, steps + [f"Apply unary plus: +{_format_number(val)} = {_format_number(val)}."]
        return -val, steps + [f"Apply unary minus: -{_format_number(val)} = {_format_number(-val)}."]

    if isinstance(node, ast.BinOp) and isinstance(node.op, _ALLOWED_BINOPS):
        left_val, left_steps = _eval_with_steps(node.left)
        right_val, right_steps = _eval_with_steps(node.right)
        steps = left_steps + right_steps
        expr_text = _node_to_text(node)

        if isinstance(node.op, ast.Add):
            result = left_val + right_val
            if (
                isinstance(node.left, ast.Constant)
                and isinstance(node.right, ast.Constant)
                and isinstance(node.left.value, int)
                and isinstance(node.right.value, int)
                and node.left.value >= 0
                and node.right.value >= 0
            ):
                steps.extend(_column_addition_steps(int(node.left.value), int(node.right.value)))
            else:
                steps.append(f"Evaluate {expr_text}: {_format_number(left_val)} + {_format_number(right_val)} = {_format_number(result)}.")
            return result, steps

        if isinstance(node.op, ast.Sub):
            result = left_val - right_val
            steps.append(f"Evaluate {expr_text}: {_format_number(left_val)} - {_format_number(right_val)} = {_format_number(result)}.")
            return result, steps

        if isinstance(node.op, ast.Mult):
            result = left_val * right_val
            steps.append(f"Evaluate {expr_text}: {_format_number(left_val)} * {_format_number(right_val)} = {_format_number(result)}.")
            return result, steps

        if isinstance(node.op, ast.Div):
            if right_val == 0:
                raise ZeroDivisionError("division by zero")
            result = left_val / right_val
            steps.append(f"Evaluate {expr_text}: {_format_number(left_val)} / {_format_number(right_val)} = {_format_number(result)}.")
            return result, steps

    raise ValueError("unsupported expression")


def _ast_to_key(node: ast.AST) -> str:
    if isinstance(node, ast.Expression):
        return _ast_to_key(node.body)
    if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
        return _format_number(float(node.value)).replace("-", "neg_").replace(".", "dot")
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.USub):
        return f"neg_{_ast_to_key(node.operand)}"
    if isinstance(node, ast.BinOp):
        op_map = {
            ast.Add: "plus",
            ast.Sub: "minus",
            ast.Mult: "multiply",
            ast.Div: "divide",
        }
        op_token = op_map.get(type(node.op))
        if op_token is None:
            raise ValueError("unsupported operator")
        return f"{op_token}_{_ast_to_key(node.left)}_{_ast_to_key(node.right)}"
    raise ValueError("unsupported key expression")


def compute_arithmetic(text: str) -> ArithmeticResult | None:
    expr = extract_arithmetic_expression(text)
    if not expr:
        return None
    try:
        tree = ast.parse(expr, mode="eval")
        value, steps = _eval_with_steps(tree)
        key = _ast_to_key(tree)
    except Exception:
        return None
    return ArithmeticResult(expression=expr, key=key, value=_format_number(value), steps=steps)


def _normalize_calculus_expression(expr: str) -> str:
    text = (expr or "").lower().strip()
    text = text.replace("^", "**")
    text = re.sub(r"\s+", "", text)
    # 2x -> 2*x, 3y -> 3*y
    text = re.sub(r"(\d)([a-z])", r"\1*\2", text)
    return text


def _poly_add(target: dict[int, float], source: dict[int, float], sign: float = 1.0) -> None:
    for power, coeff in source.items():
        target[power] = target.get(power, 0.0) + sign * coeff


def _parse_term(term: str, variable: str) -> dict[int, float] | None:
    if not term:
        return None
    if variable not in term:
        if re.search(r"[a-z]", term):
            return None
        try:
            return {0: float(term)}
        except Exception:
            return None

    m = re.fullmatch(rf"([+-]?\d*\.?\d*)\*?{re.escape(variable)}(?:\*\*([+-]?\d+))?", term)
    if not m:
        if term == variable:
            return {1: 1.0}
        if term == f"-{variable}":
            return {1: -1.0}
        return None
    coeff_txt = m.group(1)
    pow_txt = m.group(2)
    if coeff_txt in ("", "+"):
        coeff = 1.0
    elif coeff_txt == "-":
        coeff = -1.0
    else:
        coeff = float(coeff_txt)
    power = int(pow_txt) if pow_txt is not None else 1
    return {power: coeff}


def _parse_polynomial(expr: str, variable: str) -> dict[int, float] | None:
    normalized = _normalize_calculus_expression(expr)
    if not normalized:
        return None

    # split into signed terms
    chunks = re.findall(r"[+-]?[^+-]+", normalized)
    poly: dict[int, float] = {}
    for chunk in chunks:
        if not chunk:
            continue
        parsed = _parse_term(chunk, variable)
        if parsed is None:
            return None
        _poly_add(poly, parsed, 1.0)
    return poly


def _describe_integral_term(term: str, variable: str, index: int) -> tuple[str, dict[int, float]] | None:
    parsed = _parse_term(term, variable)
    if parsed is None:
        return None

    source = term.replace("**", "^")
    if 0 in parsed and len(parsed) == 1:
        coeff = parsed[0]
        integral_poly = {1: coeff}
        result_text = _poly_to_string(integral_poly, variable)
        return (
            f"Term {index}: ∫{source} d{variable} = {result_text}.",
            integral_poly,
        )

    if len(parsed) != 1:
        return None

    power, coeff = next(iter(parsed.items()))
    new_power = power + 1
    integral_poly = {new_power: coeff / new_power}
    source_power = f"{variable}^{power}" if power != 1 else variable
    if abs(coeff - 1.0) < 1e-12:
        source_text = source_power
    elif abs(coeff + 1.0) < 1e-12:
        source_text = f"-{source_power}"
    else:
        source_text = f"{_format_number(coeff)}*{source_power}"

    result_text = _poly_to_string(integral_poly, variable)
    if abs(coeff - 1.0) < 1e-12:
        calc_text = f"1/{new_power} * {variable}^{new_power}"
    else:
        calc_text = f"{_format_number(coeff)}/{new_power} * {variable}^{new_power}"
    return (
        f"Term {index}: ∫{source_text} d{variable} = {calc_text} = {result_text}.",
        integral_poly,
    )


def _poly_to_string(poly: dict[int, float], variable: str, with_constant: bool = False) -> str:
    parts: list[str] = []
    for power in sorted(poly.keys(), reverse=True):
        coeff = poly[power]
        if abs(coeff) < 1e-12:
            continue
        sign = "+" if coeff >= 0 else "-"
        c = abs(coeff)
        if power == 0:
            term = _format_number(c)
        elif power == 1:
            if abs(c - 1.0) < 1e-12:
                term = variable
            else:
                term = f"{_format_number(c)}*{variable}"
        else:
            if abs(c - 1.0) < 1e-12:
                term = f"{variable}^{power}"
            else:
                term = f"{_format_number(c)}*{variable}^{power}"
        parts.append((sign, term))

    if not parts:
        text = "0"
    else:
        first_sign, first_term = parts[0]
        text = ("-" if first_sign == "-" else "") + first_term
        for sign, term in parts[1:]:
            text += f" {sign} {term}"

    if with_constant:
        if text == "0":
            return "C"
        return f"{text} + C"
    return text


def _extract_derivative_expression(query: str) -> tuple[str, str] | None:
    q = (query or "").strip()
    m = re.search(r"d/d([a-z])\s*(.+)", q, flags=re.I)
    if m:
        return m.group(1).lower(), m.group(2).strip()

    m = re.search(r"derivative\s+of\s+(.+?)\s+(?:wrt|with\s+respect\s+to)\s+([a-z])$", q, flags=re.I)
    if m:
        return m.group(2).lower(), m.group(1).strip()

    m = re.search(r"derivative\s+of\s+(.+)", q, flags=re.I)
    if m:
        return "x", m.group(1).strip()

    m = re.search(r"turev\s+(.+)", q, flags=re.I)
    if m:
        return "x", m.group(1).strip()

    return None


def _extract_integral_expression(query: str) -> tuple[str, str] | None:
    q = (query or "").strip()
    m = re.search(r"integral\s+of\s+(.+?)\s*d([a-z])$", q, flags=re.I)
    if m:
        return m.group(2).lower(), m.group(1).strip()

    m = re.search(r"integral\s+(.+?)\s*d([a-z])$", q, flags=re.I)
    if m:
        return m.group(2).lower(), m.group(1).strip()

    m = re.search(r"integrate\s+(.+)$", q, flags=re.I)
    if m:
        return "x", m.group(1).strip()

    m = re.search(r"integral\s+(.+)$", q, flags=re.I)
    if m:
        return "x", m.group(1).strip()

    return None


def _extract_log_expression(query: str) -> tuple[float | str, str] | None:
    q = (query or "").strip()

    m = re.search(r"log\s*base\s*([0-9]+(?:\.[0-9]+)?)\s*of\s*([0-9]+(?:\.[0-9]+)?)$", q, flags=re.I)
    if m:
        return float(m.group(1)), m.group(2)

    m = re.search(r"log_([0-9]+(?:\.[0-9]+)?)\s*\(?\s*([0-9]+(?:\.[0-9]+)?)\s*\)?$", q, flags=re.I)
    if m:
        return float(m.group(1)), m.group(2)

    m = re.search(r"(?:^|\b)(ln)\s*\(?\s*([0-9]+(?:\.[0-9]+)?|e)\s*\)?$", q, flags=re.I)
    if m:
        return math.e, m.group(2)

    m = re.search(r"(?:^|\b)(?:logarithm|log)\s+of\s+([0-9]+(?:\.[0-9]+)?)$", q, flags=re.I)
    if m:
        return 10.0, m.group(1)

    m = re.search(r"(?:^|\b)log10\s*\(?\s*([0-9]+(?:\.[0-9]+)?)\s*\)?$", q, flags=re.I)
    if m:
        return 10.0, m.group(1)

    m = re.search(r"(?:^|\b)log\s*\(?\s*([0-9]+(?:\.[0-9]+)?)\s*\)?$", q, flags=re.I)
    if m:
        return 10.0, m.group(1)

    return None


def compute_calculus(query: str) -> CalculusResult | None:
    log_info = _extract_log_expression(query)
    if log_info:
        base, value = log_info
        if isinstance(base, float) and value == "e":
            value = str(math.e)
        base_num = float(base)
        value_num = float(value)
        if value_num <= 0 or base_num <= 0 or base_num == 1.0:
            return None
        result = _format_number(math.log(value_num, base_num))
        base_label = "e" if abs(base_num - math.e) < 1e-12 else _format_number(base_num)
        value_label = str(math.e) if abs(value_num - math.e) < 1e-12 else _format_number(value_num)
        steps = [
            f"Detect logarithm with base {base_label}.",
            f"Normalize value: {value_label}.",
            f"Apply logarithm identity: log_{base_label}({value_label}) = {result}.",
        ]
        return CalculusResult(kind="logarithm", variable="", expression=f"log_{base_label}({value_label})", result=result, steps=steps)

    deriv_info = _extract_derivative_expression(query)
    if deriv_info:
        variable, deriv_expr = deriv_info
        normalized = _normalize_calculus_expression(deriv_expr)
        steps = [f"Detect derivative with respect to {variable}.", f"Normalize expression: {normalized}"]

        if normalized == f"ln({variable})":
            return CalculusResult(
                kind="derivative",
                variable=variable,
                expression=deriv_expr,
                result=f"1/{variable}",
                steps=steps + [f"Use rule d/d{variable}[ln({variable})] = 1/{variable}."]
            )
        if normalized == f"log({variable})":
            return CalculusResult(
                kind="derivative",
                variable=variable,
                expression=deriv_expr,
                result=f"1/({variable}*ln(10))",
                steps=steps + [f"Use rule d/d{variable}[log({variable})] = 1/({variable}*ln(10))."]
            )

        if normalized == f"sin({variable})":
            return CalculusResult(
                kind="derivative",
                variable=variable,
                expression=deriv_expr,
                result=f"cos({variable})",
                steps=steps + [f"Use rule d/d{variable}[sin({variable})] = cos({variable})."],
            )
        if normalized == f"cos({variable})":
            return CalculusResult(
                kind="derivative",
                variable=variable,
                expression=deriv_expr,
                result=f"-sin({variable})",
                steps=steps + [f"Use rule d/d{variable}[cos({variable})] = -sin({variable})."],
            )
        if normalized in {f"exp({variable})", f"e**{variable}"}:
            return CalculusResult(
                kind="derivative",
                variable=variable,
                expression=deriv_expr,
                result=f"exp({variable})",
                steps=steps + [f"Use rule d/d{variable}[exp({variable})] = exp({variable})."],
            )

        poly = _parse_polynomial(deriv_expr, variable)
        if poly is None:
            return None
        out: dict[int, float] = {}
        for power, coeff in poly.items():
            if power == 0:
                continue
            out[power - 1] = out.get(power - 1, 0.0) + (coeff * power)
        result = _poly_to_string(out, variable)
        steps.append("Apply power rule term-by-term and combine coefficients.")
        return CalculusResult(kind="derivative", variable=variable, expression=deriv_expr, result=result, steps=steps)

    integ_info = _extract_integral_expression(query)
    if integ_info:
        variable, integ_expr = integ_info
        normalized = _normalize_calculus_expression(integ_expr)
        steps = [f"Detect integral with respect to {variable}.", f"Normalize expression: {normalized}"]

        if normalized == f"sin({variable})":
            return CalculusResult(
                kind="integral",
                variable=variable,
                expression=integ_expr,
                result=f"-cos({variable}) + C",
                steps=steps + [f"Use rule ∫sin({variable}) d{variable} = -cos({variable}) + C."],
            )
        if normalized == f"cos({variable})":
            return CalculusResult(
                kind="integral",
                variable=variable,
                expression=integ_expr,
                result=f"sin({variable}) + C",
                steps=steps + [f"Use rule ∫cos({variable}) d{variable} = sin({variable}) + C."],
            )
        if normalized in {f"exp({variable})", f"e**{variable}"}:
            return CalculusResult(
                kind="integral",
                variable=variable,
                expression=integ_expr,
                result=f"exp({variable}) + C",
                steps=steps + [f"Use rule ∫exp({variable}) d{variable} = exp({variable}) + C."],
            )
        if normalized in {f"1/{variable}", f"1/({variable})", f"{variable}^-1", f"{variable}**-1"}:
            return CalculusResult(
                kind="integral",
                variable=variable,
                expression=integ_expr,
                result=f"ln|{variable}| + C",
                steps=steps + [f"Use rule ∫1/{variable} d{variable} = ln|{variable}| + C."],
            )

        poly = _parse_polynomial(integ_expr, variable)
        if poly is None:
            return None
        out: dict[int, float] = {}
        term_chunks = [chunk for chunk in re.findall(r"[+-]?[^+-]+", normalized) if chunk]
        detailed_steps: list[str] = []
        for index, chunk in enumerate(term_chunks, start=1):
            described = _describe_integral_term(chunk, variable, index)
            if described is None:
                return None
            step_text, integral_poly = described
            detailed_steps.append(step_text)
            _poly_add(out, integral_poly, 1.0)
        result = _poly_to_string(out, variable, with_constant=True)
        steps.extend(detailed_steps)
        steps.append("Apply reverse power rule term-by-term and add integration constant C.")
        steps.append(f"Combine integrated terms to get {result}.")
        return CalculusResult(kind="integral", variable=variable, expression=integ_expr, result=result, steps=steps)

    return None


# ── Definite Integral ─────────────────────────────────────────────────────────

@dataclass
class DefiniteIntegralResult:
    expression: str
    lower: float
    upper: float
    variable: str
    antiderivative: str
    result: str
    steps: list[str]


def _extract_definite_integral(query: str) -> tuple[str, float, float, str] | None:
    q = (query or "").strip().lower()
    m = re.search(
        r"integral\s+from\s+([0-9.]+)\s+to\s+([0-9.]+)\s+(.+?)\s*d([a-z])$",
        q, flags=re.I,
    )
    if not m:
        m = re.search(
            r"int_\{([0-9.]+)\}\^\{([0-9.]+)\}\s*(.+?)\s*\,d([a-z])",
            q, flags=re.I,
        )
    if not m:
        return None
    lower = float(m.group(1))
    upper = float(m.group(2))
    expr = m.group(3).strip()
    variable = m.group(4).lower()
    return expr, lower, upper, variable


def _eval_poly_at(poly: dict[int, float], x: float) -> float:
    total = 0.0
    for power, coeff in poly.items():
        total += coeff * (x ** power)
    return total


def compute_definite_integral(query: str) -> DefiniteIntegralResult | None:
    info = _extract_definite_integral(query)
    if not info:
        return None
    expr, lower, upper, variable = info
    normalized = _normalize_calculus_expression(expr)
    steps: list[str] = [
        f"Detect definite integral from {lower} to {upper}.",
        f"Normalize expression: {normalized}",
    ]

    poly = _parse_polynomial(expr, variable)
    if poly is None:
        return None

    antiderivative_poly: dict[int, float] = {}
    term_chunks = [chunk for chunk in re.findall(r"[+-]?[^+-]+", normalized) if chunk]
    for index, chunk in enumerate(term_chunks, start=1):
        described = _describe_integral_term(chunk, variable, index)
        if described is None:
            return None
        step_text, integral_poly = described
        steps.append(step_text)
        _poly_add(antiderivative_poly, integral_poly, 1.0)

    antiderivative_str = _poly_to_string(antiderivative_poly, variable)
    steps.append(f"Antiderivative F({variable}) = {antiderivative_str}")

    f_upper = _eval_poly_at(antiderivative_poly, upper)
    f_lower = _eval_poly_at(antiderivative_poly, lower)
    result_val = f_upper - f_lower

    steps.append(f"F({upper}) = {_format_number(f_upper)}")
    steps.append(f"F({lower}) = {_format_number(f_lower)}")
    steps.append(f"Result = F({upper}) - F({lower}) = {_format_number(result_val)}")

    return DefiniteIntegralResult(
        expression=expr,
        lower=lower,
        upper=upper,
        variable=variable,
        antiderivative=antiderivative_str,
        result=_format_number(result_val),
        steps=steps,
    )


# ── Chain Rule & Advanced Derivatives ─────────────────────────────────────────

def _extract_inner_function(normalized: str, variable: str) -> tuple[str, str, str] | None:
    """Detect patterns like sin(2*x), cos(x^2), exp(3*x), ln(x^2+1).
    Returns (outer_func, inner_expr, inner_normalized) or None.
    """
    m = re.match(r"(sin|cos|tan|exp|ln|log)\((.+)\)$", normalized)
    if not m:
        return None
    outer = m.group(1)
    inner_raw = m.group(2).strip()
    return outer, inner_raw, inner_raw


def _derivative_of(expr: str, variable: str) -> tuple[str, list[str]] | None:
    """Compute derivative of a single expression (no product rule)."""
    normalized = _normalize_calculus_expression(expr)
    steps: list[str] = [f"Compute derivative of {expr} with respect to {variable}."]

    # Pure variable
    if normalized == variable:
        return "1", steps + [f"d/d{variable}({variable}) = 1"]

    # Constant
    try:
        float(normalized)
        return "0", steps + [f"d/d{variable}({normalized}) = 0 (constant)"]
    except ValueError:
        pass

    # Trig / exp / ln basics
    basic_rules: dict[str, str] = {
        f"sin({variable})": f"cos({variable})",
        f"cos({variable})": f"-sin({variable})",
        f"tan({variable})": f"sec^2({variable})",
        f"exp({variable})": f"exp({variable})",
        f"ln({variable})": f"1/({variable})",
        f"log({variable})": f"1/({variable}*ln(10))",
    }
    if normalized in basic_rules:
        return basic_rules[normalized], steps + [f"Use basic derivative rule: d/d{variable}({normalized}) = {basic_rules[normalized]}"]

    # Power rule: x^n
    pow_m = re.fullmatch(rf"{re.escape(variable)}\*\*([+-]?\d+\.?\d*)", normalized)
    if pow_m:
        n = float(pow_m.group(1))
        result = f"{_format_number(n)}*{variable}^{_format_number(n-1)}" if (n - 1) != 1 else f"{_format_number(n)}*{variable}"
        if n == 2:
            result = f"2*{variable}"
        elif n == 1:
            result = "1"
        steps.append(f"Apply power rule: d/d{variable}({variable}^{_format_number(n)}) = {result}")
        return result, steps

    # Chain rule: sin(expr), cos(expr), etc.
    chain = _extract_inner_function(normalized, variable)
    if chain:
        outer, inner_raw, inner_norm = chain
        inner_deriv, inner_steps = _derivative_of(inner_raw, variable) if inner_raw != variable else ("1", [f"d/d{variable}({variable}) = 1"])
        inner_str = inner_raw.replace("**", "^")

        deriv_rules = {
            "sin": f"cos({inner_str})",
            "cos": f"-sin({inner_str})",
            "tan": f"sec^2({inner_str})",
            "exp": f"exp({inner_str})",
            "ln": f"1/({inner_str})",
            "log": f"1/({inner_str}*ln(10))",
        }
        outer_deriv = deriv_rules.get(outer)
        if not outer_deriv:
            return None

        if inner_deriv == "1":
            result = outer_deriv
            steps.append(f"Apply chain rule: d/d{variable}({outer}({inner_str})) = {outer_deriv}")
        else:
            result = f"{outer_deriv} * ({inner_deriv})"
            steps.extend(inner_steps)
            steps.append(f"Apply chain rule: d/d{variable}({outer}({inner_str})) = {outer_deriv} * d/d{variable}({inner_str}) = {result}")
        return result, steps

    return None


def compute_derivative_advanced(query: str) -> CalculusResult | None:
    """Extended derivative computation with chain rule and product rule."""
    deriv_info = _extract_derivative_expression(query)
    if not deriv_info:
        return None
    variable, deriv_expr = deriv_info
    normalized = _normalize_calculus_expression(deriv_expr)

    # Product rule detection: f(x)*g(x) where both contain variable
    prod_parts = re.findall(r"[^+]+", normalized)
    # Look for multiplication pattern
    prod_match = re.fullmatch(r"([a-z0-9*.^()]+)\*([a-z0-9*.^()]+)", normalized)
    if prod_match:
        left = prod_match.group(1)
        right = prod_match.group(2)
        left_has_var = variable in left
        right_has_var = variable in right
        if left_has_var and right_has_var:
            left_deriv, left_steps = _derivative_of(left, variable)
            right_deriv, right_steps = _derivative_of(right, variable)
            if left_deriv and right_deriv:
                left_str = left.replace("**", "^")
                right_str = right.replace("**", "^")
                result = f"({left_deriv})*{right_str} + {left_str}*({right_deriv})"
                steps = [
                    f"Detect product: {left_str} * {right_str}",
                    f"f = {left_str}, f' = {left_deriv}",
                    f"g = {right_str}, g' = {right_deriv}",
                    f"Apply product rule: f'*g + f*g' = {result}",
                ]
                return CalculusResult(kind="derivative", variable=variable, expression=deriv_expr, result=result, steps=steps)

    # Chain rule or basic derivative
    result = _derivative_of(deriv_expr, variable)
    if result:
        result_str, steps = result
        return CalculusResult(kind="derivative", variable=variable, expression=deriv_expr, result=result_str, steps=steps)

    return None


# ── Algebra / Matrix Detection ────────────────────────────────────────────────

@dataclass
class AlgebraResult:
    kind: str  # "determinant", "matrix_multiply", "matrix_add", "equation"
    expression: str
    result: str
    steps: list[str]


def _extract_matrix_expr(query: str) -> str | None:
    """Detect matrix expressions like [[1,2],[3,4]] or det([[1,2],[3,4]])."""
    q = (query or "").strip().lower()
    # det([[1,2],[3,4]])
    m = re.search(r"det\s*\(?\s*(\[\[.+\]\])\s*\)?", q, flags=re.I)
    if m:
        return m.group(1)
    return None


def compute_algebra(query: str) -> AlgebraResult | None:
    q = (query or "").strip().lower()
    matrix_expr = _extract_matrix_expr(q)
    if matrix_expr:
        from core.matrix_math import matrix_determinant
        import json
        try:
            mat = json.loads(matrix_expr)
            mat = [[float(x) for x in row] for row in mat]
            det, steps = matrix_determinant(mat)
            return AlgebraResult(
                kind="determinant",
                expression=matrix_expr,
                result=_format_number(det),
                steps=[f"Detect determinant of {len(mat)}x{len(mat)} matrix."] + steps,
            )
        except Exception:
            return None
    return None


# ── Equation Solving ──────────────────────────────────────────────────────────

@dataclass
class EquationResult:
    equation: str
    variable: str
    solutions: list[float]
    steps: list[str]


def _extract_equation(query: str) -> tuple[str, str] | None:
    """Detect patterns like 'solve x^2 - 4 = 0' or '2*x + 3 = 7'."""
    q = (query or "").strip()
    q_lower = q.lower()

    # "solve ..." pattern
    m = re.match(r"solve\s+(.+?)\s*=\s*(.+)$", q, flags=re.I)
    if m:
        return m.group(1).strip(), m.group(2).strip()

    # Bare equation with "=" but not calculus/matrix
    if "=" in q_lower and not re.search(r"d/d[a-z]|integral|integrate|det\s*\[|matrix", q_lower):
        m = re.match(r"^(.+?)\s*=\s*(.+)$", q, flags=re.I)
        if m:
            return m.group(1).strip(), m.group(2).strip()

    return None


def _normalize_for_poly(text: str, variable: str = "x") -> dict[int, float] | None:
    """Parse an expression into {power: coeff} dict, handling parentheses."""
    normalized = _normalize_calculus_expression(text)
    if not normalized:
        return None

    # Handle parentheses by wrapping for _parse_polynomial
    # Replace ( with -, ) with + to handle simple grouping
    # e.g. (x+1) -> treated as x+1
    # e.g. -(x^2-4) -> negate each term inside
    if "(" in normalized:
        # Try to unwrap simple parenthesized expressions
        # e.g. "(x**2-4)" -> "x**2-4"
        # e.g. "2*(x**2-4)" -> "2*x**2-8"
        parts = re.findall(r"[^()]+", normalized)
        if len(parts) == 1:
            normalized = parts[0]
        else:
            return None  # Complex parenthesized expression

    poly = _parse_polynomial(normalized, variable)
    return poly


def _poly_to_dict(poly: dict[int, float]) -> dict[int, float]:
    return {k: v for k, v in poly.items() if abs(v) > 1e-12}


def solve_equation(query: str) -> EquationResult | None:
    info = _extract_equation(query)
    if not info:
        return None
    left_str, right_str = info
    variable = "x"
    steps: list[str] = [
        f"Detect equation: {left_str} = {right_str}",
        "Move all terms to left side.",
    ]

    left_norm = _normalize_for_poly(left_str, variable)
    right_norm = _normalize_for_poly(right_str, variable)
    if left_norm is None or right_norm is None:
        return None

    # Compute left - right = 0
    poly: dict[int, float] = {}
    for power, coeff in left_norm.items():
        poly[power] = poly.get(power, 0.0) + coeff
    for power, coeff in right_norm.items():
        poly[power] = poly.get(power, 0.0) - coeff

    poly = _poly_to_dict(poly)
    if not poly:
        return None

    poly_str = _poly_to_string(poly, variable)
    steps.append(f"Combined expression: {poly_str} = 0")

    coeff2 = poly.get(2, 0.0)
    coeff1 = poly.get(1, 0.0)
    const = poly.get(0, 0.0)

    if coeff2 != 0 and all(p in (0, 1, 2) for p in poly):
        # Quadratic: ax^2 + bx + c = 0
        a, b, c = coeff2, coeff1, const
        disc = b * b - 4 * a * c
        steps.append(f"Quadratic formula: a={_format_number(a)}, b={_format_number(b)}, c={_format_number(c)}")
        steps.append(f"Discriminant = {_format_number(b)}^2 - 4*({_format_number(a)})*({_format_number(c)}) = {_format_number(disc)}")
        if disc < 0:
            steps.append(f"Discriminant < 0, no real solutions.")
            return EquationResult(equation=query, variable=variable, solutions=[], steps=steps)
        sqrt_disc = math.sqrt(disc)
        steps.append(f"sqrt({_format_number(disc)}) = {_format_number(sqrt_disc)}")
        s1 = round((-b + sqrt_disc) / (2 * a), 6)
        s2 = round((-b - sqrt_disc) / (2 * a), 6)
        solutions = sorted([s1, s2])
        steps.append(f"{variable} = [{_format_number(-b)} +/- {_format_number(sqrt_disc)}] / {_format_number(2*a)}")
        steps.append(f"Solutions: {variable} = {_format_number(s1)}, {_format_number(s2)}")
        return EquationResult(equation=query, variable=variable, solutions=solutions, steps=steps)

    if coeff1 != 0 and const != 0 and all(p in (0, 1) for p in poly):
        # Linear: ax + b = 0
        steps.append(f"Linear equation: {_format_number(coeff1)}*{variable} + {_format_number(const)} = 0")
        sol = round(-const / coeff1, 6)
        steps.append(f"{variable} = {_format_number(-const)} / {_format_number(coeff1)} = {_format_number(sol)}")
        return EquationResult(equation=query, variable=variable, solutions=[sol], steps=steps)

    if coeff1 != 0 and all(p in (0, 1) for p in poly):
        steps.append(f"Linear equation: {_format_number(coeff1)}*{variable} = 0")
        return EquationResult(equation=query, variable=variable, solutions=[0.0], steps=steps)

    if const == 0 and coeff1 == 0 and all(p == 0 for p in poly):
        steps.append("Identity: 0 = 0, all values are solutions.")
        return EquationResult(equation=query, variable=variable, solutions=[], steps=steps)

    return None

    return EquationResult(equation=query, variable=variable, solutions=solutions, steps=steps)
