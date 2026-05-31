"""Test all 6 symbolic math features."""
import os
os.environ['PYTHONIOENCODING'] = 'utf-8'

import api
from fastapi.testclient import TestClient

client = TestClient(api.app)

tests = [
    ("Definite Integral", "integral from 0 to 1 x^2 dx", "0.333"),
    ("Derivative sin(x)", "d/dx sin(x)", "cos(x)"),
    ("Chain sin(x^2)", "d/dx sin(x^2)", "cos(x^2) * (2*x)"),
    ("Product x*sin(x)", "d/dx x*sin(x)", "(1)*sin(x)"),
    ("det [[1,2],[3,4]]", "det [[1,2],[3,4]]", "-2"),
    ("solve x^2-4=0", "solve x^2-4=0", "-2"),
    ("solve 2*x+3=7", "solve 2*x+3=7", "2"),
]

passed = 0
failed = 0

for name, query, expected in tests:
    r = client.get("/semantic/search", params={"query": query})
    if r.status_code != 200:
        print(f"FAIL [{name}]: HTTP {r.status_code}")
        failed += 1
        continue
    data = r.json()
    facts = data.get("facts", [])
    if not facts:
        print(f"FAIL [{name}]: No facts returned")
        failed += 1
        continue
    result = facts[0].get("triple", ["", "", ""])[2]
    if expected.lower() in result.lower():
        print(f"OK   [{name}]: {result}")
        passed += 1
    else:
        print(f"FAIL [{name}]: expected '{expected}' in '{result}'")
        failed += 1

print(f"\n{passed} passed, {failed} failed")
