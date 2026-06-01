from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas
import os

os.makedirs("artifacts/seed_pdfs", exist_ok=True)

# PDF içerikleri
pdf_data = [
    ("12_exponents.pdf", [
        "EXPONENTS (USLU SAYILAR)", "",
        "Basic exponents:",
        "2^1 = 2", "2^2 = 4", "2^3 = 8", "2^4 = 16", "2^5 = 32",
        "2^6 = 64", "2^7 = 128", "2^8 = 256", "2^9 = 512", "2^10 = 1024",
        "", "3^2 = 9", "3^3 = 27", "", "4^2 = 16", "4^3 = 64",
        "", "5^2 = 25", "5^3 = 125", "", "10^2 = 100", "10^3 = 1000", "10^4 = 10000",
        "", "Special exponents:", "2^0 = 1", "5^0 = 1", "10^0 = 1",
        "", "Negative exponents:", "2^-1 = 0.5", "2^-2 = 0.25", "10^-1 = 0.1",
        "", "Exponent rules:",
        "x^a * x^b = x^(a+b)",
        "x^a / x^b = x^(a-b)",
        "(x^a)^b = x^(a*b)"
    ]),
    ("13_factorial.pdf", [
        "FACTORIAL (FAKTORIYEL)", "",
        "Definition: n! = n x (n-1) x (n-2) x ... x 1", "",
        "Values:",
        "0! = 1", "1! = 1", "2! = 2", "3! = 6", "4! = 24",
        "5! = 120", "6! = 720", "7! = 5040", "8! = 40320",
        "9! = 362880", "10! = 3628800", "11! = 39916800", "12! = 479001600", "",
        "Examples:",
        "5! = 5 x 4 x 3 x 2 x 1 = 120",
        "7! = 5040",
        "10! = 3628800", "",
        "Factorial rules:",
        "0! = 1 (by definition)",
        "n! = n x (n-1)!"
    ]),
    ("14_modulus.pdf", [
        "MODULUS (MODULUS / KALAN)", "",
        "Definition: a mod b = remainder when a is divided by b", "",
        "Examples:",
        "10 mod 3 = 1", "20 mod 7 = 6", "15 mod 5 = 0",
        "7 mod 4 = 3", "9 mod 2 = 1", "100 mod 10 = 0",
        "100 mod 9 = 1", "25 mod 4 = 1", "30 mod 8 = 6",
        "17 mod 5 = 2", "",
        "Properties:",
        "(a + b) mod m = (a mod m + b mod m) mod m",
        "(a x b) mod m = (a mod m x b mod m) mod m"
    ]),
    ("15_absolute_value.pdf", [
        "ABSOLUTE VALUE (MUTLAK DEGER)", "",
        "Definition: |x| = x if x >= 0, |x| = -x if x < 0", "",
        "Examples:",
        "|5| = 5", "|-5| = 5", "|0| = 0", "|3.5| = 3.5",
        "|-3.5| = 3.5", "|100| = 100", "|-100| = 100", "",
        "Properties:",
        "|x| >= 0", "|-x| = |x|", "|x x y| = |x| x |y|",
        "|x / y| = |x| / |y|", "|x + y| <= |x| + |y|", "",
        "Solving equations:",
        "|x| = 5 -> x = 5 or x = -5",
        "|x - 3| = 4 -> x = 7 or x = -1",
        "|x| = 0 -> x = 0"
    ])
]

for name, lines in pdf_data:
    c = canvas.Canvas(f"artifacts/seed_pdfs/{name}", pagesize=A4)
    c.setFont("Helvetica", 9)
    y = 800
    for line in lines:
        if y < 50:
            c.showPage()
            y = 800
            c.setFont("Helvetica", 9)
        c.drawString(30, y, line)
        y -= 12
    c.save()
    print(f"Created: {name}")

print("\nAll 4 seed PDFs created successfully!")
print(f"Total PDFs in seed_pdfs: {len(os.listdir('artifacts/seed_pdfs'))}")
